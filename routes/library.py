"""Favorites, reading history/progress and preferences, synced through the backend."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from database import db
from models.chapter import Chapter
from models.library import Favorite, ReadingProgress, UserPref
from models.manga import Manga
from routes.mangas import _serialize_batch
from utils.authz import current_user, viewer_is_admin
from utils.authz import require_user
from utils.http import fail
from utils.security import limiter

library_bp = Blueprint("library", __name__)

THEMES = {"auto", "nexa", "light", "amoled", "sakura", "ocean", "sunset"}
LANGS = {"auto", "fr", "en"}
READER_MODES = {"vertical", "paged"}
MAX_FAVORITES = 500
MAX_HISTORY = 60


def _uid():
    return current_user().id


def _visible_manga(manga_id):
    m = Manga.query.get(manga_id)
    if not m or (m.visibility != "public" and not viewer_is_admin()):
        return None
    return m


def _int(value, default=None, lo=None, hi=None):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None and v < lo:
        return default
    if hi is not None and v > hi:
        return default
    return v


# ------------------------------------------------------------------ favorites
@library_bp.get("/favorites")
@require_user
def list_favorites():
    favs = Favorite.query.filter_by(user_id=_uid()).order_by(Favorite.created_at.desc()).limit(MAX_FAVORITES).all()
    ids = [f.manga_id for f in favs]
    by_id = {}
    if ids:
        q = Manga.query.filter(Manga.id.in_(ids))
        if not viewer_is_admin():
            q = q.filter(Manga.visibility == "public")
        by_id = {m.id: m for m in q.all()}
    rows = [by_id[i] for i in ids if i in by_id]
    items = _serialize_batch(rows) if rows else []
    return jsonify(success=True, items=items, ids=[m["id"] for m in items], total=len(items))


@library_bp.get("/favorites/ids")
@require_user
def favorite_ids():
    ids = [f.manga_id for f in Favorite.query.filter_by(user_id=_uid()).all()]
    return jsonify(success=True, ids=ids)


@library_bp.put("/favorites/<int:manga_id>")
@require_user
def add_favorite(manga_id):
    uid = _uid()
    if not limiter.allow(f"fav:{uid}", 60, 60):
        return fail("Trop d'actions, réessaie dans un instant.", 429)
    if not _visible_manga(manga_id):
        return fail("Manga introuvable", 404)
    if not Favorite.query.filter_by(user_id=uid, manga_id=manga_id).first():
        if Favorite.query.filter_by(user_id=uid).count() >= MAX_FAVORITES:
            return fail("Limite de favoris atteinte", 409)
        db.session.add(Favorite(user_id=uid, manga_id=manga_id))
        try:
            db.session.commit()
        except Exception:  # double tap = unique violation: the favorite exists, that's fine
            db.session.rollback()
    return jsonify(success=True, favorite=True, manga_id=manga_id)


@library_bp.delete("/favorites/<int:manga_id>")
@require_user
def remove_favorite(manga_id):
    Favorite.query.filter_by(user_id=_uid(), manga_id=manga_id).delete()
    db.session.commit()
    return jsonify(success=True, favorite=False, manga_id=manga_id)


@library_bp.delete("/favorites")
@require_user
def clear_favorites():
    Favorite.query.filter_by(user_id=_uid()).delete()
    db.session.commit()
    return jsonify(success=True)


# ------------------------------------------------------------------ reading history
def _entry(p, manga):
    return {"manga": {"id": manga.id, "title": manga.title, "cover_url": manga.cover_url},
            "chapter_id": p.chapter_id, "number": p.chapter_number, "page": p.page, "total": p.total,
            "read": p.read_chapters or [], "updated_at": p.updated_at.isoformat() if p.updated_at else None}


@library_bp.get("/history")
@require_user
def history():
    rows = (ReadingProgress.query.filter_by(user_id=_uid()).order_by(ReadingProgress.updated_at.desc())
            .limit(MAX_HISTORY).all())
    mangas = {m.id: m for m in Manga.query.filter(Manga.id.in_({p.manga_id for p in rows})).all()} if rows else {}
    items = [_entry(p, mangas[p.manga_id]) for p in rows
             if p.manga_id in mangas and p.chapter_id and (mangas[p.manga_id].visibility == "public" or viewer_is_admin())]
    return jsonify(success=True, items=items, total=len(items))


@library_bp.get("/progress/<int:manga_id>")
@require_user
def get_progress(manga_id):
    p = ReadingProgress.query.filter_by(user_id=_uid(), manga_id=manga_id).first()
    manga = _visible_manga(manga_id)
    if not p or not manga:
        return jsonify(success=True, progress=None)
    return jsonify(success=True, progress=_entry(p, manga))


@library_bp.put("/progress")
@require_user
def save_progress():
    uid = _uid()
    if not limiter.allow(f"progress:{uid}", 120, 60):
        return fail("Trop de requêtes", 429)
    data = request.get_json(silent=True) or {}
    manga_id, chapter_id = _int(data.get("manga_id"), lo=1), _int(data.get("chapter_id"), lo=1)
    page, total = _int(data.get("page"), 1, 1, 5000), _int(data.get("total"), 0, 0, 5000)
    if not manga_id or not chapter_id:
        return fail("manga_id et chapter_id sont obligatoires")
    chapter = Chapter.query.get(chapter_id)
    if not chapter or chapter.manga_id != manga_id or not _visible_manga(manga_id):
        return fail("Chapitre introuvable", 404)
    if not viewer_is_admin() and (chapter.visibility != "public" or chapter.status != "published"):
        return fail("Chapitre introuvable", 404)

    p = ReadingProgress.query.filter_by(user_id=uid, manga_id=manga_id).first()
    if not p:
        p = ReadingProgress(user_id=uid, manga_id=manga_id, read_chapters=[])
        db.session.add(p)
    read = list(p.read_chapters or [])
    if total and page >= total and chapter_id not in read:
        read.append(chapter_id)
    p.read_chapters = read[-1000:]
    p.chapter_id, p.chapter_number, p.page, p.total = chapter_id, chapter.number, page, total
    p.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception:  # two requests created the row at the same time: retry once as an update
        db.session.rollback()
        p = ReadingProgress.query.filter_by(user_id=uid, manga_id=manga_id).first()
        if not p:
            return fail("Erreur d'enregistrement", 500)
        p.chapter_id, p.chapter_number, p.page, p.total, p.updated_at = chapter_id, chapter.number, page, total, datetime.utcnow()
        db.session.commit()
    return jsonify(success=True)


@library_bp.delete("/history")
@require_user
def clear_history():
    ReadingProgress.query.filter_by(user_id=_uid()).delete()
    db.session.commit()
    return jsonify(success=True)


@library_bp.delete("/history/<int:manga_id>")
@require_user
def remove_history(manga_id):
    ReadingProgress.query.filter_by(user_id=_uid(), manga_id=manga_id).delete()
    db.session.commit()
    return jsonify(success=True)


@library_bp.get("/summary")
@require_user
def summary():
    uid = _uid()
    rows = ReadingProgress.query.filter_by(user_id=uid).all()
    return jsonify(success=True, favorites=Favorite.query.filter_by(user_id=uid).count(),
                   mangas_started=len(rows), chapters_read=sum(len(r.read_chapters or []) for r in rows))


# ------------------------------------------------------------------ preferences (language, theme, reader mode)
@library_bp.get("/prefs")
@require_user
def get_prefs():
    p = UserPref.query.get(_uid())
    return jsonify(success=True, prefs=(p.data if p else {}) or {})


@library_bp.put("/prefs")
@require_user
def put_prefs():
    uid = _uid()
    data = request.get_json(silent=True) or {}
    p = UserPref.query.get(uid)
    prefs = dict((p.data if p else {}) or {})
    if data.get("language") in LANGS:
        prefs["language"] = data["language"]
    if data.get("theme") in THEMES:
        prefs["theme"] = data["theme"]
    if data.get("reader_mode") in READER_MODES:
        prefs["reader_mode"] = data["reader_mode"]
    if not p:
        p = UserPref(user_id=uid, data=prefs)
        db.session.add(p)
    else:
        p.data = prefs
    p.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True, prefs=prefs)
