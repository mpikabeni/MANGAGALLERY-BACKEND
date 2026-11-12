from flask import Blueprint, jsonify, request

from database import db
from models.chapter import Chapter
from models.comment import Comment
from models.manga import SECTION_ADULT, Manga
from models.report import Report
from models.user import User
from utils.authz import current_user, is_admin, require_admin, require_user, viewer_adult_ok, viewer_is_admin
from utils.http import fail, like_pattern, paginate, search_term
from utils.security import clean_multiline, limiter

comments_bp = Blueprint("comments", __name__)

PUBLIC = ("published", "visible")          # "visible" = legacy value
ADMIN_STATUSES = {"published", "hidden", "reported", "deleted"}


def _batch(rows):
    users = {u.id: u for u in User.query.filter(User.id.in_({c.user_id for c in rows})).all()} if rows else {}
    admin = viewer_is_admin()
    out = []
    for c in rows:
        d = c.to_dict()
        u = users.get(c.user_id)
        d["author"] = u.to_public() if u else {"id": None, "name": "—", "photo_url": None}
        if not admin:
            d.pop("user_id", None)
        else:
            d["user"] = u.to_dict() if u else None
        out.append(d)
    return out


@comments_bp.get("/")
@require_user
def list_comments():
    q = Comment.query
    if not viewer_is_admin():
        q = q.filter(Comment.status.in_(PUBLIC))
    elif request.args.get("status"):
        q = q.filter(Comment.status == request.args["status"])
    if not viewer_adult_ok():   # comments of La Sainte Culture stay behind the 18+ confirmation
        adult_ids = db.select(Manga.id).where(Manga.section == SECTION_ADULT)
        adult_chapters = db.select(Chapter.id).where(Chapter.manga_id.in_(adult_ids))
        q = q.filter(db.or_(Comment.manga_id.is_(None), ~Comment.manga_id.in_(adult_ids)))
        q = q.filter(db.or_(Comment.chapter_id.is_(None), ~Comment.chapter_id.in_(adult_chapters)))
    if request.args.get("manga_id", type=int):
        q = q.filter(Comment.manga_id == request.args.get("manga_id", type=int))
    if request.args.get("chapter_id", type=int):
        q = q.filter(Comment.chapter_id == request.args.get("chapter_id", type=int))
    term = search_term()
    if term:
        q = q.filter(Comment.content.ilike(like_pattern(term), escape="\\"))
    return paginate(q.order_by(Comment.created_at.desc()), batch=_batch, key="comments")


@comments_bp.get("/search")
@require_user
def search_comments():
    return list_comments()


@comments_bp.get("/<int:comment_id>")
@require_user
def get_comment(comment_id):
    c = Comment.query.get(comment_id)
    if not c or (c.status not in PUBLIC and not viewer_is_admin()):
        return fail("Commentaire introuvable", 404)
    return jsonify(_batch([c])[0])


@comments_bp.post("/")
@require_user
def create_comment():
    user = current_user()
    if not limiter.allow(f"comment:{user.id}", 6, 60):
        return fail("Doucement ! Réessaie dans une minute.", 429)
    data = request.get_json(silent=True) or {}
    content = clean_multiline(data.get("content"), 1000)
    if not content:
        return fail("Le contenu est obligatoire")
    manga_id, chapter_id = data.get("manga_id"), data.get("chapter_id")
    if not manga_id and not chapter_id:
        return fail("manga_id ou chapter_id requis")
    if manga_id and not Manga.query.filter_by(id=manga_id, visibility="public").first() and not is_admin(user):
        return fail("Manga introuvable", 404)
    chapter = Chapter.query.get(chapter_id) if chapter_id else None
    if chapter_id and not chapter:
        return fail("Chapitre introuvable", 404)
    adult_ids = [m for m in (manga_id, chapter.manga_id if chapter else None) if m]
    if adult_ids and not viewer_adult_ok() and \
            Manga.query.filter(Manga.id.in_(adult_ids), Manga.section == SECTION_ADULT).first():
        return fail("Espace réservé aux adultes (18+).", 403, code="ADULT_REQUIRED")
    c = Comment(user_id=user.id, manga_id=manga_id, chapter_id=chapter_id, content=content, status="published")
    db.session.add(c)
    db.session.commit()
    return jsonify(success=True, message="Commentaire ajouté", comment=_batch([c])[0]), 201


@comments_bp.put("/<int:comment_id>")
@require_user
def update_comment(comment_id):
    c, user = Comment.query.get(comment_id), current_user()
    if not c:
        return fail("Commentaire introuvable", 404)
    if c.user_id != user.id and not is_admin(user):
        return fail("Accès refusé", 403)
    content = clean_multiline((request.get_json(silent=True) or {}).get("content"), 1000)
    if not content:
        return fail("Le contenu est obligatoire")
    c.content = content
    db.session.commit()
    return jsonify(success=True, comment=_batch([c])[0])


@comments_bp.delete("/<int:comment_id>")
@require_user
def delete_comment(comment_id):
    c, user = Comment.query.get(comment_id), current_user()
    if not c:
        return fail("Commentaire introuvable", 404)
    if c.user_id != user.id and not is_admin(user):
        return fail("Accès refusé", 403)
    db.session.delete(c)
    db.session.commit()
    return jsonify(success=True, message="Commentaire supprimé")


@comments_bp.post("/<int:comment_id>/report")
@require_user
def report_comment(comment_id):
    user = current_user()
    c = Comment.query.get(comment_id)
    if not c or c.status not in PUBLIC:
        return fail("Commentaire introuvable", 404)
    if not limiter.allow(f"report:{user.id}", 10, 3600):
        return fail("Trop de signalements.", 429)
    exists = Report.query.filter_by(user_id=user.id, comment_id=c.id, status="pending").first()
    if not exists:
        reason = clean_multiline((request.get_json(silent=True) or {}).get("reason"), 500) or "comment"
        db.session.add(Report(user_id=user.id, comment_id=c.id, reason=reason, status="pending"))
        db.session.commit()
    return jsonify(success=True, message="Signalement enregistré"), 201


def _set_status(comment_id, status):
    c = Comment.query.get(comment_id)
    if not c:
        return fail("Commentaire introuvable", 404)
    c.status = status
    db.session.commit()
    return jsonify(success=True, comment=_batch([c])[0])


@comments_bp.patch("/<int:comment_id>/status")
@require_admin
def set_status(comment_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status == "visible":
        status = "published"
    if status not in ADMIN_STATUSES:
        return fail("Statut invalide")
    return _set_status(comment_id, status)


@comments_bp.patch("/<int:comment_id>/hide")
@require_admin
def hide(comment_id):
    return _set_status(comment_id, "hidden")


@comments_bp.patch("/<int:comment_id>/restore")
@require_admin
def restore(comment_id):
    return _set_status(comment_id, "published")


@comments_bp.get("/status")
def status():
    return jsonify(service="Comments", status="online")
