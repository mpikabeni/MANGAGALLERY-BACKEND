"""Image uploads. Files get random names, are verified with Pillow and stored outside any route a user can influence.

NOTE: on hosts with an ephemeral disk (Render free) uploaded files disappear on redeploy.
Prefer external image URLs for chapter pages, or mount a persistent disk on MEDIA_UPLOAD_DIR.
"""
import os
import re
import secrets

from flask import Blueprint, jsonify, request, send_file, send_from_directory
from PIL import Image, UnidentifiedImageError

from config import Config
from database import db
from models.media import Media
from utils.authz import require_admin
from utils.http import fail, like_pattern, paginate, search_term
from utils.security import clean_text

media_bp = Blueprint("media", __name__)
SAFE_NAME = re.compile(r"^[a-f0-9]{32}\.(jpg|png|webp)$")
FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}


def _dir():
    os.makedirs(Config.MEDIA_UPLOAD_DIR, exist_ok=True)
    return os.path.abspath(Config.MEDIA_UPLOAD_DIR)


@media_bp.get("/file/<name>")
def serve(name):
    """Public on purpose (used by <img>): names are 128-bit random and only images are stored."""
    if not SAFE_NAME.match(name):
        return fail("Fichier introuvable", 404)
    resp = send_from_directory(_dir(), name, conditional=True, max_age=86400)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
    return resp


@media_bp.get("/")
@require_admin
def list_media():
    q = Media.query
    term = search_term()
    if term:
        p = like_pattern(term)
        q = q.filter(db.or_(Media.filename.ilike(p, escape="\\"), Media.original_name.ilike(p, escape="\\")))
    return paginate(q.order_by(Media.created_at.desc()), lambda m: m.to_dict(), key="media")


@media_bp.get("/search")
@require_admin
def search_media():
    return list_media()


@media_bp.get("/<int:media_id>")
@require_admin
def get_media(media_id):
    m = Media.query.get(media_id)
    return jsonify(m.to_dict()) if m else fail("Média introuvable", 404)


@media_bp.post("/upload")
@require_admin
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("Fichier obligatoire")
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in Config.ALLOWED_IMAGE_EXTENSIONS:
        return fail("Type de fichier non autorisé (jpg, png, webp)")
    try:
        img = Image.open(f.stream)
        img.verify()
        f.stream.seek(0)
        img = Image.open(f.stream)
        fmt, (width, height) = img.format, img.size
    except (UnidentifiedImageError, OSError, ValueError):
        return fail("Image invalide")
    if fmt not in FORMATS or width * height > 60_000_000:
        return fail("Format ou dimensions non autorisés")
    real_ext, mime = FORMATS[fmt]
    name = f"{secrets.token_hex(16)}.{real_ext}"
    path = os.path.join(_dir(), name)
    f.stream.seek(0)
    f.save(path)
    m = Media(manga_id=request.form.get("manga_id", type=int), chapter_id=request.form.get("chapter_id", type=int),
              filename=name, original_name=clean_text(f.filename, 255) or name, file_type=real_ext,
              mime_type=mime, file_size=os.path.getsize(path), file_path=name, width=width, height=height)
    db.session.add(m)
    db.session.commit()
    return jsonify(success=True, message="Fichier envoyé", media=m.to_dict()), 201


@media_bp.patch("/<int:media_id>/rename")
@require_admin
def rename(media_id):
    m = Media.query.get(media_id)
    if not m:
        return fail("Média introuvable", 404)
    name = clean_text((request.get_json(silent=True) or {}).get("original_name"), 255)
    if not name:
        return fail("original_name obligatoire")
    m.original_name = name
    db.session.commit()
    return jsonify(success=True, media=m.to_dict())


@media_bp.get("/<int:media_id>/download")
@require_admin
def download(media_id):
    m = Media.query.get(media_id)
    if not m or not SAFE_NAME.match(m.filename or ""):
        return fail("Fichier introuvable", 404)
    path = os.path.join(_dir(), m.filename)
    if not os.path.isfile(path):
        return fail("Fichier introuvable", 404)
    return send_file(path, as_attachment=True, download_name=m.original_name or m.filename)


@media_bp.delete("/<int:media_id>")
@require_admin
def delete(media_id):
    m = Media.query.get(media_id)
    if not m:
        return fail("Média introuvable", 404)
    if SAFE_NAME.match(m.filename or ""):
        try:
            os.remove(os.path.join(_dir(), m.filename))
        except OSError:
            pass
    db.session.delete(m)
    db.session.commit()
    return jsonify(success=True, message="Fichier supprimé")


@media_bp.get("/statistics")
@require_admin
def statistics():
    items = Media.query.all()
    return jsonify(success=True, statistics={"total": len(items), "size_bytes": sum(int(m.file_size or 0) for m in items)})


@media_bp.get("/status")
def status():
    return jsonify(service="Media", status="online")
