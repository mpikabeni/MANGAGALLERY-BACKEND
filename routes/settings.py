from flask import Blueprint, jsonify, request

from config import Config
from database import db
from models.settings import Settings
from utils.authz import require_admin
from utils.http import fail
from utils.security import clean_text, is_safe_url

settings_bp = Blueprint("settings", __name__)
LANGS = {"fr", "en"}


def get_or_create():
    s = Settings.query.first()
    if not s:
        s = Settings(app_name=Config.APP_NAME, default_language="fr", registration_enabled=True,
                     maintenance_mode=False)
        db.session.add(s)
        db.session.commit()
    return s


def _apply(s, data):
    if "app_name" in data:
        name = clean_text(data["app_name"], 100)
        if not name:
            return "Nom invalide"
        s.app_name = name
    for key in ("mini_app_url", "backend_url", "logo", "favicon"):
        if key in data:
            v = data[key]
            if v and not is_safe_url(v):
                return f"{key} invalide (http/https uniquement)"
            setattr(s, key, v or None)
    if "default_language" in data:
        if data["default_language"] not in LANGS:
            return "Langue invalide (fr ou en)"
        s.default_language = data["default_language"]
    for key in ("maintenance_mode", "registration_enabled"):
        if key in data:
            setattr(s, key, bool(data[key]))
    return None


def _update():
    s = get_or_create()
    err = _apply(s, request.get_json(silent=True) or {})
    if err:
        db.session.rollback()
        return fail(err)
    db.session.commit()
    return jsonify(success=True, message="Paramètres mis à jour", settings=s.to_dict(), **s.to_dict())


@settings_bp.get("/")
@require_admin
def get_settings():
    s = get_or_create()
    return jsonify(success=True, settings=s.to_dict(), **s.to_dict())


@settings_bp.put("/")
@require_admin
def put_settings():
    return _update()


@settings_bp.patch("/")
@require_admin
def patch_settings():
    return _update()


@settings_bp.patch("/urls")
@require_admin
def update_urls():
    return _update()


@settings_bp.patch("/maintenance")
@require_admin
def maintenance():
    return _update()


@settings_bp.patch("/language")
@require_admin
def language():
    data = request.get_json(silent=True) or {}
    if "language" in data:
        data = {"default_language": data["language"]}
    s = get_or_create()
    err = _apply(s, data)
    if err:
        return fail(err)
    db.session.commit()
    return jsonify(success=True, language=s.default_language)


@settings_bp.get("/application")
def application():
    return jsonify(success=True, application={"name": Config.APP_NAME, "version": Config.APP_VERSION})


@settings_bp.get("/telegram")
@require_admin
def telegram():
    return jsonify(success=True, telegram={"bot_username": Config.TELEGRAM_BOT_USERNAME,
                                           "configured": bool(Config.TELEGRAM_BOT_TOKEN),
                                           "channel": Config.REQUIRED_CHANNEL})


@settings_bp.patch("/telegram")
@require_admin
def update_telegram():
    return fail("Le token Telegram se gère uniquement par la variable d'environnement TELEGRAM_BOT_TOKEN", 400)


@settings_bp.get("/status")
def status():
    return jsonify(service="Settings", status="online")
