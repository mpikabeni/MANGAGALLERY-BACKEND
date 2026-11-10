from datetime import datetime

from database import db


class Chapter(db.Model):

    __tablename__ = "chapters"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    manga_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "mangas.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    number = db.Column(
        db.Float,
        nullable=False
    )

    title = db.Column(
        db.String(255),
        nullable=True
    )

    slug = db.Column(
        db.String(255),
        nullable=False,
        index=True
    )

    pages = db.Column(
        db.JSON,
        nullable=False,
        default=list
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="published"
    )

    visibility = db.Column(
        db.String(30),
        nullable=False,
        default="public"
    )

    published_at = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    manga = db.relationship(
        "Manga",
        back_populates="chapters"
    )

    # ==================================
    # RELATION AVEC MEDIA
    # ==================================

    media = db.relationship(
        "Media",
        back_populates="chapter",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def to_dict(self):

        return {

            "id": self.id,

            "manga_id": self.manga_id,

            "number": self.number,

            "title": self.title,

            "slug": self.slug,

            "pages": self.pages or [],

            "status": self.status,

            "visibility": self.visibility,

            "published_at":
                self.published_at.isoformat()
                if self.published_at
                else None,

            "created_at":
                self.created_at.isoformat()
                if self.created_at
                else None,

            "updated_at":
                self.updated_at.isoformat()
                if self.updated_at
                else None

        }