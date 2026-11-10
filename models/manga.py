from datetime import datetime

from database import db


class Manga(db.Model):
    __tablename__ = "mangas"

    # ==================================
    # IDENTIFIANT
    # ==================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ==================================
    # INFORMATIONS DU MANGA
    # ==================================

    title = db.Column(
        db.String(255),
        nullable=False,
        index=True
    )

    slug = db.Column(
        db.String(255),
        unique=True,
        nullable=False,
        index=True
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    cover_url = db.Column(
        db.Text,
        nullable=True
    )

    banner_url = db.Column(
        db.Text,
        nullable=True
    )

    # ==================================
    # STATUT
    # ==================================

    status = db.Column(
        db.String(30),
        nullable=False,
        default="ongoing"
    )

    visibility = db.Column(
        db.String(30),
        nullable=False,
        default="public"
    )

    # ==================================
    # AUTEUR
    # ==================================

    author_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id",
            ondelete="SET NULL"
        ),
        nullable=True,
        index=True
    )

    # ==================================
    # CATÉGORIE
    # ==================================

    category_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "categories.id",
            ondelete="SET NULL"
        ),
        nullable=True,
        index=True
    )

    # ==================================
    # DATES
    # ==================================

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

    # ==================================
    # RELATION AVEC USER
    # ==================================

    author = db.relationship(
        "User",
        back_populates="mangas"
    )

    # ==================================
    # RELATION AVEC CATEGORY
    # ==================================

    category = db.relationship(
        "Category",
        back_populates="mangas"
    )

    # ==================================
    # RELATION AVEC MEDIA
    # ==================================

    media = db.relationship(
        "Media",
        back_populates="manga",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ==================================
    # RELATION AVEC CHAPTER
    # ==================================

    chapters = db.relationship(
        "Chapter",
        back_populates="manga",
        lazy=True,
        cascade="all, delete-orphan"
    )
    # ==================================
    # SERIALIZATION
    # ==================================

    def to_dict(self):

        return {
            "id": self.id,

            "title": self.title,

            "slug": self.slug,

            "description": self.description,

            "cover_url": self.cover_url,

            "banner_url": self.banner_url,

            "status": self.status,

            "visibility": self.visibility,

            "author_id": self.author_id,

            "category_id": self.category_id,

            "created_at":
                self.created_at.isoformat()
                if self.created_at
                else None,

            "updated_at":
                self.updated_at.isoformat()
                if self.updated_at
                else None
        }

    # ==================================
    # REPRESENTATION
    # ==================================

    def __repr__(self):

        return (
            f"<Manga "
            f"{self.title}>"
        )