"""One rating (1-5 stars) per reader and per title. Created automatically at startup (see main.py)."""
from datetime import datetime

from database import db


class Rating(db.Model):
    __tablename__ = "ratings"
    __table_args__ = (
        db.UniqueConstraint("user_id", "manga_id", name="uq_rating_user_manga"),
        db.Index("ix_ratings_manga_updated", "manga_id", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    manga_id = db.Column(db.Integer, db.ForeignKey("mangas.id", ondelete="CASCADE"), nullable=False, index=True)
    score = db.Column(db.SmallInteger, nullable=False)                       # 1..5
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Moment of the LAST vote: the ranking of "the last 7 days / 1 month / 3 months" counts the votes cast in that window.
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class ChapterRating(db.Model):
    """One rating (1-5 stars) per reader and per CHAPTER, given at the end of the chapter. The rating of a title is the average of
    the votes of its chapters. Created automatically at startup (see main.py). The old `ratings` table (one vote per title) is
    kept untouched but is no longer read."""
    __tablename__ = "chapter_ratings"
    __table_args__ = (
        db.UniqueConstraint("user_id", "chapter_id", name="uq_chapter_rating_user_chapter"),
        db.Index("ix_chapter_ratings_manga_updated", "manga_id", "updated_at"),
        db.Index("ix_chapter_ratings_chapter_updated", "chapter_id", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    manga_id = db.Column(db.Integer, db.ForeignKey("mangas.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    score = db.Column(db.SmallInteger, nullable=False)                       # 1..5
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Moment of the LAST vote: the rankings of "7 days / 1 month / 3 months" count the votes cast in that window.
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
