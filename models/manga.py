from datetime import datetime

from database import db


# ==================================
# SECTIONS / TYPES
# ==================================
SECTION_NORMAL = "normal"             # la galerie classique
SECTION_ADULT = "sainte_culture"      # La Sainte Culture (18+)
SECTIONS = {SECTION_NORMAL, SECTION_ADULT}
TYPE_MANGA, TYPE_WEBTOON, TYPE_COMIC = "manga", "webtoon", "comic"     # comic = bande dessinée
TYPES_BY_SECTION = {
    SECTION_NORMAL: {TYPE_MANGA, TYPE_WEBTOON, TYPE_COMIC},
    SECTION_ADULT: {TYPE_WEBTOON, TYPE_COMIC},                          # La Sainte Culture : webtoon + BD uniquement
}
ALL_TYPES = {TYPE_MANGA, TYPE_WEBTOON, TYPE_COMIC}


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

    section = db.Column(
        db.String(30),
        nullable=False,
        default=SECTION_NORMAL,
        server_default=SECTION_NORMAL,
        index=True
    )

    content_type = db.Column(
        db.String(30),
        nullable=False,
        default=TYPE_MANGA,
        server_default=TYPE_MANGA,
        index=True
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

            "section": self.section or SECTION_NORMAL,

            "content_type": self.content_type or TYPE_MANGA,

            "is_adult": (self.section == SECTION_ADULT),

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