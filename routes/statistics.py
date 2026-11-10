from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from database import db
from models.category import Category
from models.chapter import Chapter
from models.comment import Comment
from models.manga import Manga
from models.report import Report
from models.user import User
from utils.authz import require_admin

statistics_bp = Blueprint("statistics", __name__)


def _group(model, column):
    return {k or "unknown": n for k, n in db.session.query(column, db.func.count(model.id)).group_by(column)}


def _payload():
    week = datetime.utcnow() - timedelta(days=7)
    return {
        "users": User.query.count(),
        "mangas": Manga.query.count(),
        "chapters": Chapter.query.count(),
        "categories": Category.query.count(),
        "comments": Comment.query.count(),
        "reports_pending": Report.query.filter_by(status="pending").count(),
        "new_users_7d": User.query.filter(User.created_at >= week).count(),
        "users_by_status": _group(User, User.status),
        "mangas_by_status": _group(Manga, Manga.status),
        "chapters_by_status": _group(Chapter, Chapter.status),
    }


@statistics_bp.get("/")
@require_admin
def statistics():
    stats = _payload()
    return jsonify(success=True, statistics=stats, **stats)


@statistics_bp.get("/summary")
@require_admin
def summary():
    return statistics()
