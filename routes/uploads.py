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
from models.chapter import Chapter
from models.manga import Manga
from models.media import ImportJob, MediaBlob
from services.chapter_import import DiskFile, ImportFailure, MAX_PAGES, PROFILES, ensure_supported, iter_pages, kind_of, natural_key, optimise, optimise_page
from utils.authz import require_admin
from utils.http import fail

uploads_bp = Blueprint("uploads", __name__)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
URL_ID_RE = re.compile(r"/api/uploads/([A-Za-z0-9_-]{16,40})\.(?:jpg|webp)(?:[?#].*)?$")
def _widths():
    return {"cover": 900, "banner": Config.PAGE_MAX_WIDTH, "page": Config.PAGE_MAX_WIDTH}


_SLOTS = threading.BoundedSemaphore(Config.IMPORT_WORKERS)      # conversions running at once; the other uploads wait their turn
STALE_SECONDS = 150          # a job that has not moved for this long is considered dead (worker restarted / out of memory)


def _public_base():
    return Config.PUBLIC_BACKEND_URL.rstrip("/") if Config.PUBLIC_BACKEND_URL.startswith("http") else request.url_root.rstrip("/")


def _public_url(blob_id, base=None, mime=None):
    return f"{base or _public_base()}/api/uploads/{blob_id}.{'webp' if mime == 'image/webp' else 'jpg'}"


def _save(raw, max_width, profile=None):
    """Covers and banners stay JPEG (Telegram shows them). With `profile` the image is a chapter page: converted to WebP."""
    if profile:
        data, w, h, mime = optimise_page(raw, profile)
    else:
        (data, w, h), mime = optimise(raw, max_width=max_width), "image/jpeg"
    blob = MediaBlob(id=secrets.token_urlsafe(16), mime=mime, size=len(data), width=w, height=h, data=data)
    db.session.add(blob)
    return blob


def release_urls(urls):
    """Delete the stored images behind these URLs (only ours). Call when a chapter / title / cover goes away."""
    ids = {m.group(1) for u in (urls or []) if isinstance(u, str) for m in [URL_ID_RE.search(u)] if m}
    if ids:
        MediaBlob.query.filter(MediaBlob.id.in_(ids)).delete(synchronize_session=False)


@uploads_bp.get("/<file_id>.jpg")
@uploads_bp.get("/<file_id>.webp")
def serve(file_id):
    """Public on purpose (used by <img>, which cannot send a token): ids are unguessable."""
    if not ID_RE.match(file_id):
        return fail("Fichier introuvable", 404)
    blob = MediaBlob.query.get(file_id)
    if not blob:
        return fail("Fichier introuvable", 404)
    resp = Response(blob.data, mimetype=blob.mime)           # image/webp for converted chapter pages, image/jpeg otherwise
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    resp.set_etag(file_id)
    return resp.make_conditional(request)


@uploads_bp.post("/image")
@require_admin
def upload_image():
    """One image (cover, banner or page). form fields: file, kind=cover|banner|page."""
    if storage_full():
        return fail(FULL_MESSAGE, 507)
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("Fichier obligatoire")
    if kind_of(f) != "image":
        return fail("Choisis une image (jpg, png, webp, gif).")
    try:
        blob = _save(f.stream.read(), _widths().get(request.form.get("kind"), Config.PAGE_MAX_WIDTH))
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
    if storage_full():
        return fail(FULL_MESSAGE, 507)
    profile = request.form.get("quality") if request.form.get("quality") in PROFILES else Config.PAGE_PROFILE
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
    threading.Thread(target=_run_job, args=(app, job.id, folder, entries, _public_base(), profile), name="chapter-import", daemon=True).start()
    return jsonify(success=True, job_id=job.id), 202


def _touch(job_id, **fields):
    fields["updated_at"] = datetime.utcnow()
    ImportJob.query.filter_by(id=job_id).update(fields)
    db.session.commit()


def _run_job(app, job_id, folder, entries, base, profile):
    created, opened, has_slot = [], [], False
    with app.app_context():
        try:
            while not _SLOTS.acquire(timeout=20):
                _touch(job_id)                      # waiting in line behind other chapters: keep the job alive (see STALE_SECONDS)
            has_slot = True
            pages, skipped = [], []
            for path, filename in entries:
                df = DiskFile(path, filename)
                opened.append(df)
                for name, raw in iter_pages(df):
                    if len(pages) >= MAX_PAGES:
                        raise ImportFailure(f"Trop de pages ({MAX_PAGES} maximum par envoi). Envoie le chapitre en plusieurs fois.")
                    try:
                        blob = _save(raw, _widths()["page"], profile)
                    except ImportFailure:
                        skipped.append(name)
                        continue
                    created.append(blob.id)
                    pages.append(_public_url(blob.id, base, blob.mime))
                    if len(pages) % 3 == 0:
                        _touch(job_id, done=len(pages))        # commits the blobs too + heartbeat
            if not pages:
                raise ImportFailure("Images illisibles : " + ", ".join(skipped[:3]) if skipped
                                    else "Aucune image trouvée dans les fichiers envoyés.")
            _touch(job_id, status="done", done=len(pages), pages=pages, skipped=skipped)
            try:
                alert_admin_if_needed(storage_usage())
            except Exception:                         # the chapter is saved: never fail the job because of the storage meter
                db.session.rollback()
        except ImportFailure as exc:
            _fail_job(job_id, created, str(exc))
        except Exception as exc:
            app.logger.exception("Chapter import failed")
            _fail_job(job_id, created, f"Erreur inattendue sur le serveur ({type(exc).__name__}). Essaie avec un fichier plus léger "
                                       "ou en plusieurs parties.")
        finally:
            if has_slot:
                _SLOTS.release()
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
        ids = [m.group(1) for u in (job.pages or []) for m in [URL_ID_RE.search(u)] if m]
        stored = db.session.query(db.func.coalesce(db.func.sum(MediaBlob.size), 0)).filter(MediaBlob.id.in_(ids)).scalar() if ids else 0
        out.update(pages=job.pages or [], count=len(job.pages or []), skipped=job.skipped or [], bytes=int(stored))
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


# ------------------------------------------------------------------ storage meter, alerts, cleanup
_ALERT = {"level": 0}
FULL_PERCENT = 97


def storage_usage():
    """Database size vs capacity. On PostgreSQL the whole database counts (that is what Render limits), elsewhere only the images."""
    db_bytes = None
    try:
        if db.engine.dialect.name == "postgresql":
            db_bytes = db.session.execute(db.text("SELECT pg_database_size(current_database())")).scalar()
    except Exception:
        db.session.rollback()
    media_bytes, media_count = db.session.query(db.func.coalesce(db.func.sum(MediaBlob.size), 0), db.func.count(MediaBlob.id)).one()
    used = int(db_bytes or media_bytes or 0)
    capacity = Config.DB_CAPACITY_MB * 1024 * 1024
    percent = round(used * 100 / capacity, 1)
    uploaded_chapters = Chapter.query.filter(Chapter.source.is_(None)).count()
    per_chapter = (media_bytes / uploaded_chapters) if uploaded_chapters and media_bytes else 0
    return {"used_bytes": used, "capacity_bytes": capacity, "percent": percent, "media_bytes": int(media_bytes), "media_count": int(media_count),
            "level": "critical" if percent >= 95 else "warn" if percent >= 80 else "ok",
            "uploaded_chapters": uploaded_chapters, "avg_chapter_bytes": int(per_chapter),
            "chapters_left": int(max(0, capacity - used) / per_chapter) if per_chapter else None}


def alert_admin_if_needed(usage):
    """One Telegram message to the administrator when the storage crosses 80 % and again at 95 %."""
    level = 95 if usage["percent"] >= 95 else 80 if usage["percent"] >= 80 else 0
    if level > _ALERT["level"] and Config.TELEGRAM_BOT_TOKEN and Config.ADMIN_TELEGRAM_ID:
        try:
            from services.telegram_service import tg_call
            mb = lambda b: f"{b / 1048576:.0f} Mo"
            tg_call("sendMessage", {"chat_id": Config.ADMIN_TELEGRAM_ID, "parse_mode": "HTML", "text":
                    f"⚠️ <b>Stockage à {usage['percent']:.0f} %</b> ({mb(usage['used_bytes'])} / {mb(usage['capacity_bytes'])}).\n\n"
                    "Ouvre l'admin → « Nettoyer » pour supprimer les images inutilisées, privilégie l'import MangaDex (il ne stocke pas les pages), "
                    "ou passe à une base plus grande."})
        except Exception:
            pass
    if usage["percent"] < 70:
        _ALERT["level"] = 0
    else:
        _ALERT["level"] = max(_ALERT["level"], level)


def storage_full():
    """True when an upload should be refused (the database would hit its limit and every page of the app would fail)."""
    try:
        return storage_usage()["percent"] >= FULL_PERCENT
    except Exception:
        db.session.rollback()
        return False


FULL_MESSAGE = ("Stockage presque plein : l'envoi est refusé pour ne pas bloquer l'application. Utilise « Nettoyer » dans le menu, "
                "supprime d'anciens chapitres, ou passe à une base plus grande.")


@uploads_bp.get("/usage")
@require_admin
def usage():
    data = storage_usage()
    alert_admin_if_needed(data)
    return jsonify(success=True, **data)


@uploads_bp.post("/cleanup")
@require_admin
def cleanup():
    """Delete uploaded images that no cover, banner or chapter uses (cancelled uploads, replaced covers). Images younger than an hour
    are kept: they may belong to a form that is still open."""
    in_use = set()
    for row in db.session.query(Manga.cover_url, Manga.banner_url):
        in_use.update(m.group(1) for u in row for m in [URL_ID_RE.search(u or "")] if m)
    for (pages,) in db.session.query(Chapter.pages).filter(Chapter.source.is_(None)):
        in_use.update(m.group(1) for u in (pages or []) if isinstance(u, str) for m in [URL_ID_RE.search(u)] if m)
    limit = datetime.utcnow() - timedelta(hours=1)
    unused = [(i, n) for i, n, created in db.session.query(MediaBlob.id, MediaBlob.size, MediaBlob.created_at) if i not in in_use and created < limit]
    for start in range(0, len(unused), 200):
        MediaBlob.query.filter(MediaBlob.id.in_([i for i, _ in unused[start:start + 200]])).delete(synchronize_session=False)
    db.session.commit()
    return jsonify(success=True, deleted=len(unused), freed_bytes=int(sum(n or 0 for _, n in unused)))
