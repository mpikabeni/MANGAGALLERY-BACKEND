"""
==================================
MANGA GALLERY
SETTINGS MODEL
==================================
"""

from datetime import datetime

from database import db


class Settings(db.Model):

    __tablename__ = "settings"


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    app_name = db.Column(

        db.String(150),

        nullable=False,

        default="Manga Gallery"

    )


    telegram_bot = db.Column(

        db.String(150)

    )


    mini_app_url = db.Column(

        db.String(255)

    )


    backend_url = db.Column(

        db.String(255)

    )


    logo = db.Column(

        db.String(255)

    )


    favicon = db.Column(

        db.String(255)

    )


    default_language = db.Column(

        db.String(20),

        default="fr"

    )


    maintenance_mode = db.Column(

        db.Boolean,

        default=False

    )


    registration_enabled = db.Column(

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
    # SERIALIZATION
    # ==================================

    def to_dict(self):

        return {

            "id": self.id,

            "app_name": self.app_name,

            "telegram_bot": self.telegram_bot,

            "mini_app_url": self.mini_app_url,

            "backend_url": self.backend_url,

            "logo": self.logo,

            "favicon": self.favicon,

            "default_language": self.default_language,

            "maintenance_mode": self.maintenance_mode,

            "registration_enabled": self.registration_enabled,

            "created_at": self.created_at.isoformat()

            if self.created_at else None,

            "updated_at": self.updated_at.isoformat()

            if self.updated_at else None

        }


    # ==================================
    # REPRESENTATION
    # ==================================

    def __repr__(self):

        return (

            f"<Settings {self.app_name}>"

        )