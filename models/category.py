"""
==================================
MANGA GALLERY
CATEGORY MODEL
==================================
"""

from datetime import datetime

from database import db


class Category(db.Model):

    __tablename__ = "categories"


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    name = db.Column(

        db.String(120),

        unique=True,

        nullable=False,

        index=True

    )


    slug = db.Column(

        db.String(120),

        unique=True,

        nullable=False,

        index=True

    )


    description = db.Column(

        db.Text

    )


    icon = db.Column(

        db.String(255)

    )


    color = db.Column(

        db.String(20),

        default="#E11D2E"

    )


    is_active = db.Column(

        db.Boolean,

        default=True

    )


    created_at = db.Column(

        db.DateTime,

        default=datetime.utcnow

    )


    updated_at = db.Column(

        db.DateTime,

        default=datetime.utcnow,

        onupdate=datetime.utcnow

    )
    
    # ==================================
    # RELATIONSHIPS
    # ==================================

    mangas = db.relationship(

        "Manga",

        back_populates="category",

        cascade="save-update",

        passive_deletes=True,

        lazy=True

    )


    # ==================================
    # SERIALIZATION
    # ==================================

    def to_dict(self):

        return {

            "id": self.id,

            "name": self.name,

            "slug": self.slug,

            "description": self.description,

            "icon": self.icon,

            "color": self.color,

            "is_active": self.is_active,

            "mangas_count": len(self.mangas)

        }


    # ==================================
    # REPRESENTATION
    # ==================================

    def __repr__(self):

        return f"<Category {self.name}>"