from datetime import datetime

from database import db


class Comment(db.Model):

    __tablename__ = "comments"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    manga_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "mangas.id",
            ondelete="CASCADE"
        ),
        nullable=True,
        index=True
    )

    chapter_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "chapters.id",
            ondelete="CASCADE"
        ),
        nullable=True,
        index=True
    )

    content = db.Column(
        db.Text,
        nullable=False
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="visible"
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

    user = db.relationship(
        "User",
        back_populates="comments"
    )

    def to_dict(self):

        return {

            "id": self.id,

            "user_id": self.user_id,

            "manga_id": self.manga_id,

            "chapter_id": self.chapter_id,

            "content": self.content,

            "status": self.status,

            "created_at":
                self.created_at.isoformat()
                if self.created_at
                else None,

            "updated_at":
                self.updated_at.isoformat()
                if self.updated_at
                else None

        }