"""Manga Gallery FR - Flask application (canonical entry point, WSGI object: `app`)."""
import logging
import threading
import time

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config, validate_config
from database import db, init_database
from utils.schema import ensure_schema

# Import every model before create_all / mapper configuration.
from models import (Admin, Category, Chapter, Comment, Favorite, Manga, Media, Notification, ReadingProgress,  # noqa: F401
                    Report, Role, Settings, User, UserPref)

validate_config()

app = Flask(__name__)
app.config.from_object(Config)
app.url_map.strict_slashes = False          # /api/settings and /api/settings/ both work (no redirect on preflight)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # Render sits behind one proxy
logging.basicConfig(level=logging.INFO)

if "*" in Config.CORS_ORIGINS:
    app.logger.warning("CORS_ORIGINS=* : restreins-le au domaine du mini app (ex. https://mangagalleryzone.netlify.app)")
CORS(app, resources={r"/api/*": {"origins": Config.CORS_ORIGINS}, r"/health": {"origins": "*"}},
     supports_credentials=False, allow_headers=["Authorization", "Content-Type"], max_age=600)

jwt = JWTManager(app)
init_database(app)


# ------------------------------------------------------------------ JWT errors -> consistent JSON
@jwt.unauthorized_loader
def _missing(reason):
    return jsonify(success=False, message="Authentification requise", code="UNAUTHORIZED"), 401


@jwt.invalid_token_loader
def _invalid(reason):
    return jsonify(success=False, message="Session invalide", code="INVALID_TOKEN"), 401


@jwt.expired_token_loader
def _expired(header, payload):
    return jsonify(success=False, message="Session expirée", code="TOKEN_EXPIRED"), 401


# ------------------------------------------------------------------ blueprints
from routes.auth import auth_bp  # noqa: E402
from routes.categories import categories_bp  # noqa: E402
from routes.chapters import chapters_bp  # noqa: E402
from routes.comments import comments_bp  # noqa: E402
from routes.library import library_bp  # noqa: E402
from routes.mangas import mangas_bp  # noqa: E402
from routes.media import media_bp  # noqa: E402
from routes.notifications import notifications_bp  # noqa: E402
from routes.reports import reports_bp  # noqa: E402
from routes.roles import roles_bp  # noqa: E402
from routes.settings import settings_bp  # noqa: E402
from routes.statistics import statistics_bp  # noqa: E402
from routes.system import system_bp  # noqa: E402
from routes.telegram import telegram_bp  # noqa: E402
from routes.users import users_bp  # noqa: E402

for blueprint, prefix in [
    (auth_bp, "auth"), (mangas_bp, "mangas"), (chapters_bp, "chapters"), (categories_bp, "categories"),
    (users_bp, "users"), (comments_bp, "comments"), (notifications_bp, "notifications"),
    (statistics_bp, "statistics"), (reports_bp, "reports"), (media_bp, "media"), (roles_bp, "roles"),
    (settings_bp, "settings"), (system_bp, "system"), (telegram_bp, "telegram"), (library_bp, "library"),
]:
    app.register_blueprint(blueprint, url_prefix=f"/api/{prefix}")


# ------------------------------------------------------------------ public endpoints
@app.get("/api/config")
def public_config():
    """Everything the mini app needs before the user is authenticated (nothing sensitive)."""
    language, maintenance = "fr", False
    try:
        s = Settings.query.first()
        if s:
            language, maintenance = s.default_language or "fr", bool(s.maintenance_mode)
    except Exception:
        db.session.rollback()
    return jsonify(success=True, app_name=Config.APP_NAME, version=Config.APP_VERSION,
                   channel=Config.REQUIRED_CHANNEL if Config.CHANNEL_GATE else None,
                   channel_url=("https://t.me/" + Config.REQUIRED_CHANNEL.lstrip("@")) if Config.CHANNEL_GATE else None,
                   adult_space="La Sainte Culture",
                   default_language=language if language in ("fr", "en") else "fr", languages=["fr", "en"],
                   maintenance=maintenance, password_login=Config.ADMIN_PASSWORD_LOGIN,
                   bot_username=Config.TELEGRAM_BOT_USERNAME or None, mini_app_url=Config.TELEGRAM_MINI_APP_URL or None)


@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        ok = True
    except Exception:
        db.session.rollback()
        ok = False
    return jsonify(status="online" if ok else "degraded", application=Config.APP_NAME,
                   version=Config.APP_VERSION, database="online" if ok else "offline"), 200 if ok else 503


# ------------------------------------------------------------------ errors
@app.errorhandler(HTTPException)
def http_error(err):
    return jsonify(success=False, message=err.description or err.name), err.code


@app.errorhandler(Exception)
def unhandled(err):
    db.session.rollback()
    app.logger.exception("Unhandled application error")
    return jsonify(success=False, message="Internal server error"), 500


@app.after_request
def secure_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if Config.APP_ENV == "production":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not resp.headers.get("Cache-Control"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ------------------------------------------------------------------ tables / schema / bot
# Everything below is idempotent: it creates what is missing and never touches existing data, so there is no
# manual "init-db" step any more (a fresh database used to answer 500 on every request until someone ran it).
def _prepare_database():
    with app.app_context():
        try:
            db.create_all()
        except Exception:  # another gunicorn worker may be creating them at the same time
            db.session.rollback()
            app.logger.warning("create_all skipped (concurrent start?)")
        try:
            ensure_schema(db)  # adds the "La Sainte Culture" columns to databases created by an older version
        except Exception:
            db.session.rollback()
            app.logger.exception("Schema upgrade failed")


def _bot_boot():
    """Register the Telegram webhook + commands + menu button, with retries (Render may still be starting)."""
    from services.telegram_service import ensure_webhook, setup_bot
    for attempt in range(1, 5):
        try:
            url = ensure_webhook()
            setup_bot()
            app.logger.info("Telegram bot ready - webhook: %s", url)
            return
        except Exception as exc:
            app.logger.warning("Telegram setup attempt %s/4 failed: %s", attempt, exc)
            time.sleep(4 * attempt)
    app.logger.error("Telegram setup failed. Open /api/telegram/health to see what is wrong.")


_prepare_database()
if Config.BOT_AUTO_SETUP and Config.TELEGRAM_BOT_TOKEN:
    threading.Thread(target=_bot_boot, name="telegram-boot", daemon=True).start()


@app.cli.command("init-db")
def init_db_command():
    db.create_all()
    print("Tables créées.")


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
