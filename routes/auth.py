"""Authentication.

Mini app users sign in with Telegram initData (validated server-side with the bot token).
The administrator is the account whose Telegram id equals ADMIN_TELEGRAM_ID.
Password login exists only for that account and only if ADMIN_PASSWORD_LOGIN=true.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (create_access_token, create_refresh_token, get_jwt_identity,
                                jwt_required)
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import db
from models.settings import Settings
from models.user import User
from services.telegram_service import TelegramError, channel_url, is_channel_member, is_owner
from services.user_service import upsert_telegram_user
from utils.authz import current_user, is_admin
from utils.http import fail
from utils.security import InitDataError, limiter, verify_init_data

auth_bp = Blueprint("auth", __name__)

_DUMMY_HASH = None


def _client_ip():
    return request.remote_addr or "?"  # real client IP thanks to ProxyFix in main.py


def _public_user(user):
    data = user.to_dict()
    data["is_admin"] = is_admin(user)
    return data


def _tokens(user):
    ident = str(user.id)
    return {"access_token": create_access_token(identity=ident),
            "refresh_token": create_refresh_token(identity=ident)}


def _gate(telegram_id):
    """Return an error response if this Telegram user may not enter, else None."""
    if is_owner(telegram_id) or not Config.CHANNEL_GATE:
        return None
    try:
        if not is_channel_member(telegram_id):
            return fail("Rejoins le canal Nexa pour continuer.", 403, code="NOT_MEMBER",
                        channel=Config.REQUIRED_CHANNEL, channel_url=channel_url())
    except TelegramError:
        return fail("Vérification du canal impossible pour le moment.", 503, code="CHANNEL_CHECK_FAILED")
    return None


@auth_bp.post("/telegram")
def telegram_login():
    if not limiter.allow(f"tg:{_client_ip()}", 40, 60):
        return fail("Trop de tentatives, réessayez dans une minute.", 429, code="RATE_LIMITED")
    data = request.get_json(silent=True) or {}
    try:
        tg_user = verify_init_data(str(data.get("init_data") or ""), Config.TELEGRAM_BOT_TOKEN,
                                   Config.TELEGRAM_INITDATA_MAX_AGE)
    except InitDataError:
        return fail("Session Telegram invalide. Rouvre l'application depuis le bot.", 401, code="INVALID_INIT_DATA")

    denied = _gate(tg_user["id"])
    if denied:
        return denied

    settings = Settings.query.first()
    owner = is_owner(tg_user["id"])
    if settings and settings.maintenance_mode and not owner:
        return fail("Maintenance en cours.", 503, code="MAINTENANCE")

    user = upsert_telegram_user(tg_user, allow_create=bool(owner or not settings or settings.registration_enabled))
    if not user:
        return fail("Les inscriptions sont fermées.", 403, code="REGISTRATION_CLOSED")
    if user.status != "active":
        return fail("Compte désactivé.", 403, code="ACCOUNT_DISABLED")

    return jsonify(success=True, user=_public_user(user), **_tokens(user)), 200


@auth_bp.post("/login")
def password_login():
    if not Config.ADMIN_PASSWORD_LOGIN:
        return fail("Connexion par mot de passe désactivée. Ouvre l'administration depuis Telegram.", 403,
                    code="PASSWORD_LOGIN_DISABLED")
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()[:100]
    password = str(data.get("password", ""))[:256]
    if not (limiter.allow(f"pw-ip:{_client_ip()}", 10, 600) and limiter.allow(f"pw-user:{username.lower()}", 5, 900)):
        return fail("Trop de tentatives. Réessaie plus tard.", 429, code="RATE_LIMITED")

    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = generate_password_hash("nexa-dummy")
    user = User.query.filter(db.func.lower(User.username) == username.lower(), User.role == "admin").first()
    valid = check_password_hash((user.password_hash if user and user.password_hash else _DUMMY_HASH), password)
    if not (user and user.password_hash and valid and is_admin(user)):
        return fail("Identifiants incorrects", 401)
    from datetime import datetime
    user.last_login = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True, user=_public_user(user), **_tokens(user)), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    user = current_user()
    if not user or user.status != "active":
        return fail("Utilisateur introuvable", 401)
    return jsonify(success=True, user=_public_user(user), version=Config.APP_VERSION)


@auth_bp.post("/adult-confirm")
@jwt_required()
def adult_confirm():
    """The user declares being 18 or older: unlocks La Sainte Culture (stored server-side, on every device)."""
    user = current_user()
    if not user or user.status != "active":
        return fail("Utilisateur introuvable", 401)
    if (request.get_json(silent=True) or {}).get("confirm") is not True:
        return fail("Confirmation requise", 400)
    from datetime import datetime
    user.adult_confirmed_at = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True, user=_public_user(user))


@auth_bp.delete("/adult-confirm")
@jwt_required()
def adult_revoke():
    """Lock La Sainte Culture again for this account."""
    user = current_user()
    if not user or user.status != "active":
        return fail("Utilisateur introuvable", 401)
    user.adult_confirmed_at = None
    db.session.commit()
    return jsonify(success=True, user=_public_user(user))


@auth_bp.get("/verify")
@jwt_required()
def verify():
    return me()


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    user = User.query.get(int(get_jwt_identity()))
    if not user or user.status != "active":
        return fail("Compte indisponible", 401)
    if user.telegram_id:
        denied = _gate(user.telegram_id)
        if denied:
            return denied
    return jsonify(success=True, access_token=create_access_token(identity=str(user.id)))


@auth_bp.post("/logout")
@jwt_required(optional=True)
def logout():
    return jsonify(success=True, message="Déconnexion réussie")


@auth_bp.get("/status")
def status():
    return jsonify(service="Authentication", status="online")
