from flask import Blueprint, jsonify, request

from database import db
from models.notification import Notification
from models.user import User
from utils.authz import current_user, is_admin, require_admin, require_user
from utils.http import fail, paginate
from utils.security import clean_multiline, clean_text

notifications_bp = Blueprint("notifications", __name__)
TYPES = {"system", "announcement", "promotion", "manga", "category", "user", "important", "urgent", "normal"}


def _ntype(v):
    return v if v in TYPES else "system"


# ---------------------------------------------------------------- mini app (own notifications)
@notifications_bp.get("/me")
@require_user
def my_notifications():
    q = Notification.query.filter_by(user_id=current_user().id).order_by(Notification.created_at.desc())
    resp = paginate(q, lambda n: n.to_dict(), key="notifications")
    return resp


@notifications_bp.get("/me/unread-count")
@require_user
def my_unread():
    n = Notification.query.filter_by(user_id=current_user().id, is_read=False).count()
    return jsonify(success=True, unread=n)


@notifications_bp.patch("/me/read-all")
@require_user
def read_all():
    for n in Notification.query.filter_by(user_id=current_user().id, is_read=False).all():
        n.mark_as_read()
    db.session.commit()
    return jsonify(success=True)


@notifications_bp.patch("/<int:notification_id>/read")
@require_user
def mark_read(notification_id):
    n, user = Notification.query.get(notification_id), current_user()
    if not n or (n.user_id != user.id and not is_admin(user)):
        return fail("Notification introuvable", 404)
    n.mark_as_read()
    db.session.commit()
    return jsonify(success=True, notification=n.to_dict())


# ---------------------------------------------------------------- administration
@notifications_bp.get("/")
@require_admin
def list_notifications():
    q = Notification.query
    if request.args.get("type") in TYPES:
        q = q.filter(Notification.type == request.args["type"])
    return paginate(q.order_by(Notification.created_at.desc()), lambda n: n.to_dict(), key="notifications")


@notifications_bp.get("/user/<int:user_id>")
@require_admin
def user_notifications(user_id):
    if not User.query.get(user_id):
        return fail("Utilisateur introuvable", 404)
    q = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc())
    return paginate(q, lambda n: n.to_dict(), key="notifications")


@notifications_bp.get("/<int:notification_id>")
@require_admin
def get_notification(notification_id):
    n = Notification.query.get(notification_id)
    return jsonify(n.to_dict()) if n else fail("Notification introuvable", 404)


def _content(data):
    title = clean_text(data.get("title"), 200)
    message = clean_multiline(data.get("message"), 2000)
    return title, message


@notifications_bp.post("/")
@require_admin
def send_notification():
    data = request.get_json(silent=True) or {}
    title, message = _content(data)
    if not title or not message:
        return fail("title et message sont obligatoires")
    uid = data.get("user_id")
    if uid is not None and not User.query.get(uid):
        return fail("Utilisateur introuvable", 404)
    n = Notification(user_id=uid, title=title, message=message, type=_ntype(data.get("type")),
                     data=data.get("data") if isinstance(data.get("data"), dict) else {})
    db.session.add(n)
    db.session.commit()
    return jsonify(success=True, message="Notification créée", notification=n.to_dict()), 201


@notifications_bp.post("/broadcast")
@require_admin
def broadcast():
    data = request.get_json(silent=True) or {}
    title, message = _content(data)
    if not title or not message:
        return fail("title et message sont obligatoires")
    ids = [u.id for u in User.query.filter_by(status="active").with_entities(User.id).all()]
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    db.session.bulk_save_objects([Notification(user_id=i, title=title, message=message,
                                               type=_ntype(data.get("type")), data=payload) for i in ids])
    db.session.commit()
    return jsonify(success=True, message="Notification diffusée", recipients=len(ids)), 201


@notifications_bp.put("/<int:notification_id>")
@require_admin
def update_notification(notification_id):
    n = Notification.query.get(notification_id)
    if not n:
        return fail("Notification introuvable", 404)
    data = request.get_json(silent=True) or {}
    title, message = _content(data)
    if title:
        n.title = title
    if message:
        n.message = message
    if "type" in data:
        n.type = _ntype(data["type"])
    db.session.commit()
    return jsonify(success=True, notification=n.to_dict())


@notifications_bp.post("/<int:notification_id>/resend")
@require_admin
def resend(notification_id):
    n = Notification.query.get(notification_id)
    if not n:
        return fail("Notification introuvable", 404)
    copy = Notification(user_id=n.user_id, title=n.title, message=n.message, type=n.type, data=n.data or {})
    db.session.add(copy)
    db.session.commit()
    return jsonify(success=True, message="Notification renvoyée", notification=copy.to_dict()), 201


@notifications_bp.delete("/<int:notification_id>")
@require_admin
def delete_notification(notification_id):
    n = Notification.query.get(notification_id)
    if not n:
        return fail("Notification introuvable", 404)
    db.session.delete(n)
    db.session.commit()
    return jsonify(success=True, message="Notification supprimée")


@notifications_bp.get("/statistics")
@require_admin
def statistics():
    total = Notification.query.count()
    unread = Notification.query.filter_by(is_read=False).count()
    return jsonify(success=True, statistics={"total": total, "unread": unread, "read": total - unread})


@notifications_bp.get("/status")
def status():
    return jsonify(service="Notifications", status="online")
