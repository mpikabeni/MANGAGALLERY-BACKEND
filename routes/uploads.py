"""Administrator uploads: covers, banners and whole chapters (images, PDF, CBZ, ZIP, CBT).

Images are optimised and stored in PostgreSQL (table media_blobs), then served by GET /api/uploads/<id>.jpg
with a long cache lifetime. Nothing is ever written to the (ephemeral) disk except a temporary PDF."""
import re
import secrets

from flask import Blueprint, Response, jsonify, request

from config import Config
from database import db
from models.media import MediaBlob
from services.chapter_import import ImportFailure, MAX_PAGES, iter_pages, kind_of, natural_key, optimise
from utils.authz import require_admin
from utils.http import fail

uploads_bp = Blueprint("uploads", __name__)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
URL_ID_RE = re.compile(r"/api/uploads/([A-Za-z0-9_-]{16,40})\.jpg(?:[?#].*)?$")
WIDTHS = {"cover": 900, "banner": 1600, "page": 1600}


def _public_url(blob_id):
    base = Config.PUBLIC_BACKEND_URL.rstrip("/") if Config.PUBLIC_BACKEND_URL.startswith("http") else request.url_root.rstrip("/")
    return f"{base}/api/uploads/{blob_id}.jpg"


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
    """Many files at once -> ordered page URLs. Archives/PDF are opened, loose images are sorted by file name."""
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return fail("Choisis au moins un fichier.")
    if all(kind_of(f) == "image" for f in files):
        files.sort(key=lambda f: natural_key(f.filename))
    created, pages, skipped = [], [], []
    try:
        for f in files:
            for name, raw in iter_pages(f):
                if len(pages) >= MAX_PAGES:
                    raise ImportFailure(f"Trop de pages ({MAX_PAGES} maximum par envoi). Envoie le chapitre en plusieurs fois.")
                try:
                    blob = _save(raw, WIDTHS["page"])
                except ImportFailure:
                    skipped.append(name)
                    continue
                created.append(blob.id)
                pages.append(_public_url(blob.id))
                if len(created) % 10 == 0:
                    db.session.commit()
        if not pages:
            raise ImportFailure("Images illisibles : " + ", ".join(skipped[:3]) if skipped
                                else "Aucune image trouvée dans les fichiers envoyés.")
        db.session.commit()
    except ImportFailure as exc:
        db.session.rollback()
        if created:
            MediaBlob.query.filter(MediaBlob.id.in_(created)).delete(synchronize_session=False)
            db.session.commit()
        return fail(str(exc))
    except Exception:
        db.session.rollback()
        if created:
            MediaBlob.query.filter(MediaBlob.id.in_(created)).delete(synchronize_session=False)
            db.session.commit()
        raise
    return jsonify(success=True, pages=pages, count=len(pages), skipped=skipped)


@uploads_bp.post("/discard")
@require_admin
def discard():
    """Forget images that were uploaded but never saved (modal closed, page removed before saving)."""
    urls = (request.get_json(silent=True) or {}).get("urls")
    if isinstance(urls, list):
        release_urls(urls[:600])
        db.session.commit()
    return jsonify(success=True)
