from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from config import Config
from models.user import User


def current_user():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return User.query.get(user_id)


def is_admin(user):
    """The one and only administrator.

    Requires the admin role AND, when ADMIN_TELEGRAM_ID is configured, that exact Telegram id.
    A role string in the database alone is never enough.
    """
    if not user or user.status != "active" or user.role != "admin":
        return False
    if Config.ADMIN_TELEGRAM_ID:
        return user.telegram_id == Config.ADMIN_TELEGRAM_ID
    return True


def _deny(message, status):
    return jsonify(success=False, message=message), status


def require_user(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user.status != "active":
            return _deny("Authentification requise", 401)
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user.status != "active":
            return _deny("Authentification requise", 401)
        if not is_admin(user):
            return _deny("Accès réservé à l'administrateur", 403)
        return fn(*args, **kwargs)
    return wrapper


def viewer_is_admin():
    """Cached per request: is the caller the administrator? (used to widen visibility filters)"""
    if not hasattr(g, "_viewer_is_admin"):
        g._viewer_is_admin = is_admin(current_user())
    return g._viewer_is_admin
