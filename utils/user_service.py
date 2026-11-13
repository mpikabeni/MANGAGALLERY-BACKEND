from datetime import datetime

from sqlalchemy.exc import IntegrityError

from config import Config
from database import db
from models.user import User
from utils.security import clean_text, is_safe_url

RESERVED_USERNAMES = {"admin", "administrator", "root", "support", "moderator", "system", "nexa", "nexa_cg", "exauce"}


def is_owner_id(telegram_id):
    return bool(Config.ADMIN_TELEGRAM_ID) and telegram_id == Config.ADMIN_TELEGRAM_ID


def _free_username(candidate, telegram_id):
    fallback = f"tg_{telegram_id}"
    if not candidate or len(candidate) < 3:
        return fallback
    low = candidate.lower()
    reserved = RESERVED_USERNAMES | ({Config.ADMIN_USERNAME.lower()} if Config.ADMIN_USERNAME else set())
    if low in reserved and not is_owner_id(telegram_id):
        return fallback
    if User.query.filter(db.func.lower(User.username) == low, User.telegram_id != telegram_id).first():
        return fallback
    return candidate


def sync_role(user):
    """Single administrator rule, decided by the configured Telegram id only."""
    if not Config.ADMIN_TELEGRAM_ID:
        return
    if is_owner_id(user.telegram_id):
        user.role = "admin"
        user.status = "active"
        user.is_verified = True
    elif user.role == "admin":
        user.role = "user"
        user.role_id = None


def upsert_telegram_user(tg_user, allow_create=True):
    """Create/update the account from *verified* Telegram data. Returns None if registration is closed."""
    telegram_id = int(tg_user["id"])
    first = clean_text(tg_user.get("first_name"))
    last = clean_text(tg_user.get("last_name"))
    uname = clean_text(tg_user.get("username"))
    photo = tg_user.get("photo_url") if is_safe_url(tg_user.get("photo_url"), allow_relative=False) else None

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        if not allow_create and not is_owner_id(telegram_id):
            return None
        user = User(telegram_id=telegram_id, username=_free_username(uname, telegram_id), first_name=first,
                    last_name=last, photo_url=photo, role="user", status="active", is_verified=True)
        db.session.add(user)
    else:
        user.first_name, user.last_name = first, last
        if photo:
            user.photo_url = photo
        if uname and uname != user.username:
            user.username = _free_username(uname, telegram_id)

    sync_role(user)
    user.last_login = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:  # two first requests at the same time
        db.session.rollback()
        user = User.query.filter_by(telegram_id=telegram_id).first()
        if not user:
            raise
    return user
