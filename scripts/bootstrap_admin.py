"""Create / repair the single administrator account.

Usage (ADMIN_TELEGRAM_ID is required, ADMIN_PASSWORD is optional):
    ADMIN_TELEGRAM_ID=123456789 python scripts/bootstrap_admin.py

Normally you do not even need this: the account is created automatically the first time you open the
mini app from the Telegram account whose id is ADMIN_TELEGRAM_ID. This script also demotes every
other account that carries the admin role, so exactly one administrator remains.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from config import Config  # noqa: E402
from database import db  # noqa: E402
from main import app  # noqa: E402
from models.role import Role  # noqa: E402
from models.user import User  # noqa: E402

PERMS = {"manage_mangas": True, "manage_users": True, "manage_settings": True, "manage_roles": True,
         "manage_reports": True, "manage_notifications": True}

if not Config.ADMIN_TELEGRAM_ID:
    sys.exit("ADMIN_TELEGRAM_ID est obligatoire (votre identifiant Telegram numérique).")

with app.app_context():
    role = Role.query.filter_by(name="admin").first()
    if not role:
        role = Role(name="admin", description="Administrateur unique de Manga Gallery FR", permissions=PERMS,
                    is_system=True, is_active=True)
        db.session.add(role)
        db.session.flush()
    else:
        role.permissions, role.is_system, role.is_active = PERMS, True, True

    user = User.query.filter_by(telegram_id=Config.ADMIN_TELEGRAM_ID).first()
    if not user:
        username = Config.ADMIN_USERNAME or f"tg_{Config.ADMIN_TELEGRAM_ID}"
        user = User(telegram_id=Config.ADMIN_TELEGRAM_ID, username=username, first_name=username)
        db.session.add(user)
    user.role, user.role_id, user.status, user.is_verified = "admin", role.id, "active", True

    password = os.getenv("ADMIN_PASSWORD", "")
    if password:
        if len(password) < 12:
            sys.exit("ADMIN_PASSWORD : 12 caractères minimum.")
        user.password_hash = generate_password_hash(password)

    for other in User.query.filter(User.id != user.id, User.role.in_(["admin", "super_admin"])).all():
        other.role, other.role_id = "user", None
    db.session.commit()
    print(f"ADMIN PRÊT : id={user.id} telegram_id={user.telegram_id}")
