"""
==================================
MANGA GALLERY
REPORT MODEL
==================================
"""

from datetime import datetime

from database import db


class Report(db.Model):

    __tablename__ = "reports"


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    user_id = db.Column(

        db.Integer,

        db.ForeignKey("users.id"),

        nullable=False,

        index=True

    )


    manga_id = db.Column(

        db.Integer,

        db.ForeignKey("mangas.id"),

        nullable=True,

        index=True

    )


    comment_id = db.Column(

        db.Integer,

        db.ForeignKey("comments.id"),

        nullable=True,

        index=True

    )


    reason = db.Column(

        db.Text,

        nullable=False

    )


    status = db.Column(

        db.String(20),

        default="pending"

    )


    moderator_id = db.Column(

        db.Integer,

        db.ForeignKey("users.id"),

        nullable=True

    )


    moderator_note = db.Column(

        db.Text

    )


    resolved_at = db.Column(

        db.DateTime

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

    user = db.relationship(

        "User",

        foreign_keys=[user_id],

        back_populates="reports"

    )

    moderator = db.relationship(

        "User",

        foreign_keys=[moderator_id]

    )

    manga = db.relationship(

        "Manga",

        backref="reports"

    )

    comment = db.relationship(

        "Comment",

        backref="reports"

    )


    # ==================================
    # SERIALIZATION
    # ==================================

    def to_dict(self):

        return {

            "id": self.id,

            "user_id": self.user_id,

            "manga_id": self.manga_id,

            "comment_id": self.comment_id,

            "reason": self.reason,

            "status": self.status,

            "moderator_id": self.moderator_id,

            "moderator_note": self.moderator_note,

            "resolved_at": self.resolved_at.isoformat()

            if self.resolved_at else None,

            "created_at": self.created_at.isoformat()

            if self.created_at else None,

            "updated_at": self.updated_at.isoformat()

            if self.updated_at else None

        }


    # ==================================
    # REPRESENTATION
    # ==================================

    def __repr__(self):

        return f"<Report {self.id}>"