"""
==================================
MANGA GALLERY
ROLE MODEL
==================================
"""

from datetime import datetime

from database import db


class Role(db.Model):

    __tablename__ = "roles"


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    name = db.Column(

        db.String(100),

        unique=True,

        nullable=False,

        index=True

    )


    description = db.Column(

        db.Text

    )


    permissions = db.Column(

        db.JSON,

        nullable=False,

        default=dict

    )


    is_system = db.Column(

        db.Boolean,

        default=False

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


    users = db.relationship(
        "User",
        back_populates="role_object",
        foreign_keys="User.role_id",
        lazy=True
    )

    # ==================================
    # SERIALIZATION
    # ==================================


    def to_dict(self):

        return {

            "id": self.id,

            "name": self.name,

            "description": self.description,

            "permissions": self.permissions,

            "is_system": self.is_system,

            "is_active": self.is_active,

            "total_users": len(self.users),

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

            f"<Role {self.name}>"

        )