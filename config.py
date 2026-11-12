"""Manga Gallery FR - configuration (everything comes from environment variables)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = "Manga Gallery FR"
APP_VERSION = "Finale"         # single source of truth for the displayed version
REQUIRED_CHANNEL = "@Nexa_CG"  # users must join this channel before using the mini app (set REQUIRED_CHANNEL=off to disable)
FRONTEND_URL = "https://mangagalleryzone.netlify.app"             # the mini app (Netlify)
BACKEND_URL = "https://mangagallery-backend-8d98.onrender.com"     # this API (Render)


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default=None):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} doit être un nombre entier")


def _database_url():
    url = os.getenv("DATABASE_URL", "").strip()
    # Render/Heroku give postgres:// or postgresql:// ; SQLAlchemy + psycopg3 needs the driver name.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    # ---- application
    APP_NAME = APP_NAME
    APP_VERSION = APP_VERSION
    APP_ENV = os.getenv("APP_ENV", "development")
    DEBUG = APP_ENV == "development"
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = _int("PORT", 5000)
    AUTO_CREATE_TABLES = True   # tables are created / completed automatically at startup (never touches existing data)
    API_PREFIX = "/api"

    # ---- secrets
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
    JWT_ACCESS_TOKEN_EXPIRES = _int("JWT_ACCESS_MINUTES", 60) * 60
    JWT_REFRESH_TOKEN_EXPIRES = _int("JWT_REFRESH_DAYS", 14) * 86400

    # ---- database
    DATABASE_URL = _database_url()
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}

    # ---- uploads / pagination
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
    MEDIA_UPLOAD_DIR = os.getenv("MEDIA_UPLOAD_DIR", str(BASE_DIR / "uploads"))
    DEFAULT_PAGE_SIZE = _int("DEFAULT_PAGE_SIZE", 20)
    MAX_PAGE_SIZE = _int("MAX_PAGE_SIZE", 100)

    # ---- CORS (comma separated list of origins)
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", FRONTEND_URL).split(",") if o.strip()]

    # ---- Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    TELEGRAM_MINI_APP_URL = os.getenv("TELEGRAM_MINI_APP_URL", FRONTEND_URL).strip()
    TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    PUBLIC_BACKEND_URL = os.getenv("PUBLIC_BACKEND_URL", BACKEND_URL).strip()
    REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip() or REQUIRED_CHANNEL
    # REQUIRED_CHANNEL=off|none|false|0 switches the channel gate off (useful while the bot is not yet admin of the channel)
    CHANNEL_GATE = REQUIRED_CHANNEL.lower() not in {"off", "none", "false", "0", "no"}
    # Register the webhook + bot commands by itself when the server starts (production by default).
    BOT_AUTO_SETUP = _bool("BOT_AUTO_SETUP", "true" if os.getenv("APP_ENV", "development") == "production" else "false")
    TELEGRAM_INITDATA_MAX_AGE = _int("TELEGRAM_INITDATA_MAX_AGE", 86400)

    # ---- administrator (the owner). Identified by Telegram id, never by "id == 1".
    ADMIN_TELEGRAM_ID = _int("ADMIN_TELEGRAM_ID")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
    # Password login is OFF by default: the admin signs in through Telegram only.
    ADMIN_PASSWORD_LOGIN = _bool("ADMIN_PASSWORD_LOGIN")


_PLACEHOLDERS = ("change", "your-", "generate", "example", "secret-key")


def _weak(value):
    v = (value or "").strip().lower()
    return len(v) < 32 or any(v.startswith(p) for p in _PLACEHOLDERS)


def validate_config():
    missing = [k for k in ("SECRET_KEY", "JWT_SECRET_KEY", "DATABASE_URL") if not getattr(Config, k)]
    if missing:
        raise RuntimeError("Configuration manquante : " + ", ".join(missing))

    if Config.APP_ENV == "production":
        weak = [k for k in ("SECRET_KEY", "JWT_SECRET_KEY") if _weak(getattr(Config, k))]
        if weak:
            raise RuntimeError(
                "Secrets trop faibles ou encore à leur valeur d'exemple : " + ", ".join(weak)
                + ". Générez-les avec : python -c \"import secrets;print(secrets.token_urlsafe(48))\""
            )
        if not Config.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN est obligatoire en production")
        if not Config.TELEGRAM_WEBHOOK_SECRET:
            raise RuntimeError("TELEGRAM_WEBHOOK_SECRET est obligatoire en production")
        if not Config.ADMIN_TELEGRAM_ID:
            raise RuntimeError("ADMIN_TELEGRAM_ID est obligatoire en production (votre identifiant Telegram numérique)")
    return True
