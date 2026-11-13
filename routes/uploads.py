"""Administrator uploads: covers, banners and whole chapters (images, PDF, CBZ, ZIP, CBT).

Images are optimised and stored in PostgreSQL (table media_blobs), then served by GET /api/uploads/<id>.jpg
with a long cache lifetime. Nothing is ever written to the (ephemeral) disk except a temporary PDF."""
import os
import re
import secrets
import shutil
import tempfile
import threading
from datetime import datetime, timedelta

from flask import Blueprint, Response, current_app, jsonify, request

from config import Config
from database import db
from models.media import ImportJob, MediaBlob
from services.chapter_import import DiskFile, ImportFailure, MAX_PAGES, ensure_supported, iter_pages, kind_of, natural_key, optimise
from utils.authz import require_admin
from utils.http import fail

uploads_bp = Blueprint("uploads", __name__)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
URL_ID_RE = re.compile(r"/api/uploads/([A-Za-z0-9_-]{16,40})\.jpg(?:[?#].*)?$")
WIDTHS = {"cover": 900, "banner": 1600, "page": 1600}


STALE_SECONDS = 150          # a job that has not moved for this long is considered dead (worker restarted / out of memory)


def _public_base():
    return Config.PUBLIC_BACKEND_URL.rstrip("/") if Config.PUBLIC_BACKEND_URL.startswith("http") else request.url_root.rstrip("/")


def _public_url(blob_id, base=None):
    return f"{base or _public_base()}/api/uploads/{blob_id}.jpg"


def _save(raw, max_width):
    data, w, h = optimise(raw, max_width=max_width)
    blob = MediaBlob(id=secrets.token_urlsafe(16), mime="image/jpeg", size=len(data), width=w, height=h, data=data)
    db.session.add(blob)
    return blob


def release_urls(urls):
    """Delete the stored images behind these URLs (only ours). Call when a chapter / title / cover goes away."""
    ids = {m.group(1) for u in (urls or []) if isinstance(u, str) for m in [URL_ID_RE.search(u)] if m}
    if ids:
        MediaBlob.query.filter(MediaBlob.id.in_(ids)).delete(synchronize_session=False)


@uploads_bp.get("/<file_id>.jpg")
def serve(file_id):
    """Public on purpose (used by <img>, which cannot send a token): ids are unguessable."""
    if not ID_RE.match(file_id):
        return fail("Fichier introuvable", 404)
    blob = MediaBlob.query.get(file_id)
    if not blob:
        return fail("Fichier introuvable", 404)
    resp = Response(blob.data, mimetype=blob.mime)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    resp.set_etag(file_id)
    return resp.make_conditional(request)


@uploads_bp.post("/image")
@require_admin
def upload_image():
    """One image (cover, banner or page). form fields: file, kind=cover|banner|page."""
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("Fichier obligatoire")
    if kind_of(f) != "image":
        return fail("Choisis une image (jpg, png, webp, gif).")
    try:
        blob = _save(f.stream.read(), WIDTHS.get(request.form.get("kind"), 1600))
        db.session.commit()
    except ImportFailure as exc:
        db.session.rollback()
        return fail(str(exc))
    return jsonify(success=True, url=_public_url(blob.id), width=blob.width, height=blob.height, size=blob.size)


@uploads_bp.post("/chapter")
@require_admin
def upload_chapter():
    """Many files at once (images, PDF, CBZ, ZIP, CBT). The files are saved, a background job converts the pages, and
    this request answers at once with the job id; the admin page then polls GET /jobs/<id>."""
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return fail("Choisis au moins un fichier.")
    try:
        kinds = [ensure_supported(f) for f in files]
    except ImportFailure as exc:
        return fail(str(exc))
    if all(k == "image" for k in kinds):
        files.sort(key=lambda f: natural_key(f.filename))

    folder = tempfile.mkdtemp(prefix="mgfr_import_")
    try:
        entries = []
        for i, f in enumerate(files):
            path = os.path.join(folder, f"{i}.bin")
            f.save(path)
            entries.append((path, f.filename))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    ImportJob.query.filter(ImportJob.created_at < datetime.utcnow() - timedelta(days=1)).delete(synchronize_session=False)
    job = ImportJob(id=secrets.token_urlsafe(16), status="processing", done=0)
    db.session.add(job)
    db.session.commit()
    app = current_app._get_current_object()
    threading.Thread(target=_run_job, args=(app, job.id, folder, entries, _public_base()), name="chapter-import", daemon=True).start()
    return jsonify(success=True, job_id=job.id), 202


def _touch(job_id, **fields):
    fields["updated_at"] = datetime.utcnow()
    ImportJob.query.filter_by(id=job_id).update(fields)
    db.session.commit()


def _run_job(app, job_id, folder, entries, base):
    created, opened = [], []
    with app.app_context():
        try:
            pages, skipped = [], []
            for path, filename in entries:
                df = DiskFile(path, filename)
                opened.append(df)
                for name, raw in iter_pages(df):
                    if len(pages) >= MAX_PAGES:
                        raise ImportFailure(f"Trop de pages ({MAX_PAGES} maximum par envoi). Envoie le chapitre en plusieurs fois.")
                    try:
                        blob = _save(raw, WIDTHS["page"])
                    except ImportFailure:
                        skipped.append(name)
                        continue
                    created.append(blob.id)
                    pages.append(_public_url(blob.id, base))
                    if len(pages) % 3 == 0:
                        _touch(job_id, done=len(pages))        # commits the blobs too + heartbeat
            if not pages:
                raise ImportFailure("Images illisibles : " + ", ".join(skipped[:3]) if skipped
                                    else "Aucune image trouvée dans les fichiers envoyés.")
            _touch(job_id, status="done", done=len(pages), pages=pages, skipped=skipped)
        except ImportFailure as exc:
            _fail_job(job_id, created, str(exc))
        except Exception as exc:
            app.logger.exception("Chapter import failed")
            _fail_job(job_id, created, f"Erreur inattendue sur le serveur ({type(exc).__name__}). Essaie avec un fichier plus léger "
                                       "ou en plusieurs parties.")
        finally:
            for df in opened:
                df.close()
            shutil.rmtree(folder, ignore_errors=True)
            db.session.remove()


def _fail_job(job_id, created, message):
    db.session.rollback()
    if created:
        MediaBlob.query.filter(MediaBlob.id.in_(created)).delete(synchronize_session=False)
    _touch(job_id, status="error", error=message)


@uploads_bp.get("/jobs/<job_id>")
@require_admin
def job_status(job_id):
    job = ImportJob.query.get(job_id)
    if not job:
        return fail("Traitement introuvable", 404)
    if job.status == "processing" and (datetime.utcnow() - job.updated_at).total_seconds() > STALE_SECONDS:
        job.status = "error"
        job.error = ("Le traitement s'est interrompu (serveur redémarré ou mémoire insuffisante). "
                     "Réessaie avec un fichier plus léger ou en plusieurs parties.")
        db.session.commit()
    out = {"success": True, "status": job.status, "done": job.done}
    if job.status == "done":
        out.update(pages=job.pages or [], count=len(job.pages or []), skipped=job.skipped or [])
    elif job.status == "error":
        out["error"] = job.error
    return jsonify(out)


@uploads_bp.post("/discard")
@require_admin
def discard():
    """Forget images that were uploaded but never saved (modal closed, page removed before saving)."""
    urls = (request.get_json(silent=True) or {}).get("urls")
    if isinstance(urls, list):
        release_urls(urls[:600])
        db.session.commit()
    return jsonify(success=True)
