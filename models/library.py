"""Per-user library stored on the server: favorites, reading progress, preferences.

These tables are created automatically at startup (see main.py), no manual migration needed.
"""
from datetime import datetime

from database import db


class Favorite(db.Model):
    __tablename__ = "favorites"
    __table_args__ = (db.UniqueConstraint("user_id", "manga_id", name="uq_favorite_user_manga"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    manga_id = db.Column(db.Integer, db.ForeignKey("mangas.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ReadingProgress(db.Model):
    __tablename__ = "reading_progress"
    __table_args__ = (db.UniqueConstraint("user_id", "manga_id", name="uq_progress_user_manga"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    manga_id = db.Column(db.Integer, db.ForeignKey("mangas.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    chapter_number = db.Column(db.Float, nullable=True)
    page = db.Column(db.Integer, nullable=False, default=1)
    total = db.Column(db.Integer, nullable=False, default=0)
    read_chapters = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class UserPref(db.Model):
    __tablename__ = "user_prefs"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
