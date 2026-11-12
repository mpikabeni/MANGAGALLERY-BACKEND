from datetime import datetime

from database import db


class User(db.Model):
    __tablename__ = "users"

    # ==================================
    # IDENTIFIANT
    # ==================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # ==================================
    # TELEGRAM
    # ==================================

    telegram_id = db.Column(
        db.BigInteger,
        unique=True,
        nullable=True,
        index=True
    )

    username = db.Column(
        db.String(100),
        nullable=True
    )

    first_name = db.Column(
        db.String(100),
        nullable=True
    )

    last_name = db.Column(
        db.String(100),
        nullable=True
    )

    photo_url = db.Column(
        db.Text,
        nullable=True
    )

    # ==================================
    # COMPTE
    # ==================================

    email = db.Column(
        db.String(255),
        unique=True,
        nullable=True,
        index=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=True
    )

    role = db.Column(
        db.String(30),
        nullable=False,
        default="user"
    )

    # ==================================
    # ROLE RELATION
    # ==================================

    role_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "roles.id",
            ondelete="SET NULL"
        ),
        nullable=True,
        index=True
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="active"
    )

    is_verified = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    last_login = db.Column(
        db.DateTime,
        nullable=True
    )

    # La Sainte Culture (18+) : date à laquelle la personne a déclaré avoir 18 ans ou plus
    adult_confirmed_at = db.Column(
        db.DateTime,
        nullable=True
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
    # RELATION AVEC ROLE
    # ==================================

    role_object = db.relationship(
        "Role",
        back_populates="users",
        foreign_keys=[role_id]
    )

    # ==================================
    # RELATION AVEC MANGA
    # ==================================

    mangas = db.relationship(
        "Manga",
        back_populates="author",
        lazy=True
    )

    # ==================================
    # RELATION AVEC COMMENTAIRES
    # ==================================

    comments = db.relationship(
        "Comment",
        back_populates="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ==================================
    # RELATION AVEC NOTIFICATIONS
    # ==================================

    notifications = db.relationship(
        "Notification",
        back_populates="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ==================================
    # RELATION AVEC REPORTS
    # ==================================

    reports = db.relationship(
        "Report",
        foreign_keys="Report.user_id",
        back_populates="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # ==================================
    # SERIALIZATION
    # ==================================

    def to_dict(self):

        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "username": self.username,
            "name": self.display_name(),
            "first_name": self.first_name,
            "last_name": self.last_name,
            "photo_url": self.photo_url,
            "email": self.email,
            "role": self.role,
            "role_id": self.role_id,
            "status": self.status,
            "is_verified": self.is_verified,
            "adult_confirmed": bool(self.adult_confirmed_at),
            "last_login":
                self.last_login.isoformat()
                if self.last_login
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

    def display_name(self):
        full = " ".join(x for x in (self.first_name, self.last_name) if x)
        return full or self.username or f"User {self.id}"

    def to_public(self):
        """Safe subset shown to other users (no Telegram id / email)."""
        return {"id": self.id, "name": self.display_name(), "photo_url": self.photo_url}

    # ==================================
    # REPRESENTATION
    # ==================================

    def __repr__(self):

        return (
            f"<User "
            f"{self.id} "
            f"{self.username}>"
        )
