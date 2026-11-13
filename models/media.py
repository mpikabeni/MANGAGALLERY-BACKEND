"""
==================================
MANGA GALLERY
MEDIA MODEL
==================================
"""

from datetime import datetime

from database import db


class Media(db.Model):

    __tablename__ = "media"


    id = db.Column(

        db.Integer,

        primary_key=True

    )


    manga_id = db.Column(

        db.Integer,

        db.ForeignKey("mangas.id"),

        nullable=True,

        index=True

    )


    chapter_id = db.Column(

        db.Integer,

        db.ForeignKey("chapters.id"),

        nullable=True,

        index=True

    )


    filename = db.Column(

        db.String(255),

        nullable=False

    )


    original_name = db.Column(

        db.String(255),

        nullable=False

    )


    file_type = db.Column(

        db.String(50),

        nullable=False

    )


    mime_type = db.Column(

        db.String(100)

    )


    file_size = db.Column(

        db.BigInteger,

        default=0

    )


    file_path = db.Column(

        db.String(500),

        nullable=False

    )


    width = db.Column(

        db.Integer,

        default=0

    )


    height = db.Column(

        db.Integer,

        default=0

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

    manga = db.relationship(

        "Manga",

        back_populates="media"

    )

    chapter = db.relationship(

        "Chapter",

        back_populates="media"

    )


    # ==================================
    # SERIALIZATION
    # ==================================

    def to_dict(self):

        return {

            "id": self.id,

            "manga_id": self.manga_id,

            "chapter_id": self.chapter_id,

            "filename": self.filename,

            "original_name": self.original_name,

            "file_type": self.file_type,

            "mime_type": self.mime_type,

            "file_size": self.file_size,

            "url": f"/api/media/file/{self.filename}",

            "width": self.width,

            "height": self.height,

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

            f"<Media {self.filename}>"

        )

class MediaBlob(db.Model):
    """An image uploaded by the administrator, stored IN the database.

    Render's disk is wiped at every deploy, PostgreSQL is not: covers and chapter pages therefore live here and are
    served by /api/uploads/<id>.jpg. The id is a random 128-bit token (the URL is only ever shown by endpoints that
    already applied the visibility / 18+ rules)."""

    __tablename__ = "media_blobs"

    id = db.Column(db.String(40), primary_key=True)
    mime = db.Column(db.String(60), nullable=False, default="image/jpeg")
    size = db.Column(db.Integer, nullable=False, default=0)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    data = db.deferred(db.Column(db.LargeBinary, nullable=False))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ImportJob(db.Model):
    """Background import of a chapter (PDF / CBZ / images). The upload request answers immediately with the job id and
    the page conversion runs in a thread: a long PDF can no longer hit the hosting platform's request timeout."""

    __tablename__ = "import_jobs"

    id = db.Column(db.String(40), primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="processing")   # processing | done | error
    done = db.Column(db.Integer, nullable=False, default=0)
    pages = db.Column(db.JSON, nullable=True)
    skipped = db.Column(db.JSON, nullable=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
