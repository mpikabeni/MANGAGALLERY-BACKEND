from datetime import datetime

from database import db


class Notification(db.Model):

    __tablename__ = "notifications"

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
        nullable=True,
        index=True
    )

    title = db.Column(
        db.String(255),
        nullable=False
    )

    message = db.Column(
        db.Text,
        nullable=False
    )

    type = db.Column(
        db.String(50),
        nullable=False,
        default="system"
    )

    is_read = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    data = db.Column(
        db.JSON,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    read_at = db.Column(
        db.DateTime,
        nullable=True
    )

    user = db.relationship(
        "User",
        back_populates="notifications"
    )

    def mark_as_read(self):

        if not self.is_read:

            self.is_read = True

            self.read_at = datetime.utcnow()


    def to_dict(self):

        return {

            "id": self.id,

            "user_id": self.user_id,

            "title": self.title,

            "message": self.message,

            "type": self.type,

            "is_read": self.is_read,

            "data": self.data or {},

            "created_at":
                self.created_at.isoformat()
                if self.created_at
                else None,

            "read_at":
                self.read_at.isoformat()
                if self.read_at
                else None

        }