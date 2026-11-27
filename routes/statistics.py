"""Admin statistics.

The page (admin/statistics.html) asks GET /api/statistics?range=7|30|90|365 and expects: overview, activity (chart), content (doughnut),
reading, engagement, top_mangas, top_users, categories, recent_activity and performance. The old flat totals (users, mangas, ...)
are still returned at the top level because the dashboard uses them.

Where the numbers come from:
  - users / mangas / chapters / comments / favorites : their own tables (created_at)
  - views   = chapters OPENED   (read_events, kind "open")      } recorded by PUT /library/progress since this version
  - reading = chapters FINISHED (read_events, kind "complete")  }
  - reading time, bookmarks and shares are not tracked anywhere in the app: they are returned as 0.
Every "change" value compares the selected period with the previous one of the same length (in %).
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from database import db
from models.category import Category
from models.chapter import Chapter
from models.comment import Comment
from models.library import Favorite, ReadEvent, ReadingProgress
from models.manga import TYPE_COMIC, TYPE_MANGA, TYPE_WEBTOON, Manga
from models.report import Report
from models.user import User
from utils.authz import require_admin

statistics_bp = Blueprint("statistics", __name__)

RANGES = (7, 30, 90, 365)
TYPE_LABELS = {TYPE_MANGA: "Mangas", TYPE_WEBTOON: "Webtoons", TYPE_COMIC: "BD / Comics"}


def _group(model, column):
    return {k or "unknown": n for k, n in db.session.query(column, db.func.count(model.id)).group_by(column)}


def _pct(current, previous):
    """Change in % between two periods (+100 when something appears from nothing)."""
    if not previous:
        return 100.0 if current else 0.0
    return round((current - previous) / previous * 100, 1)


def _soft(fn, default):
    """Runs a query that may fail (for example the `read_events` table does not exist yet): returns `default` instead of breaking the page."""
    try:
        return fn()
    except Exception:
        db.session.rollback()
        current_app.logger.warning("statistics: query skipped", exc_info=True)
        return default


def _count(model, column, start, end, *extra):
    return _soft(lambda: model.query.filter(column >= start, column < end, *extra).count(), 0)


def _daily(column, since, *extra):
    """{'YYYY-MM-DD': n} for the rows created since `since` (grouped by day in SQL: works on PostgreSQL and SQLite)."""
    day = db.func.date(column)
    rows = _soft(lambda: db.session.query(day, db.func.count()).filter(column >= since, *extra).group_by(day).all(), [])
    return {str(d)[:10]: n for d, n in rows}


def _buckets(days):
    """Chart columns: one per day up to 30 days, one per week for 90 days, one per ~month for a year."""
    step, n = (1, days) if days <= 30 else (7, math.ceil(days / 7)) if days <= 90 else (30, 12)
    today = datetime.utcnow().date()
    out = []
    for i in range(n):
        end = today - timedelta(days=(n - 1 - i) * step)
        start = end - timedelta(days=step - 1)
        out.append((start, end, end.strftime("%d/%m")))
    return out


def _series(daily, buckets):
    result = []
    for start, end, _ in buckets:
        total, d = 0, start
        while d <= end:
            total += daily.get(d.isoformat(), 0)
            d += timedelta(days=1)
        result.append(total)
    return result


def _name(user):
    return (user.first_name or user.username or "Utilisateur") if user else "Utilisateur"


def _merge(primary, fallback):
    """Ranking values: the recorded openings, or - while nothing has been recorded yet - the readers found in the reading history."""
    return {k: (primary.get(k) or fallback.get(k, 0)) for k in set(primary) | set(fallback)}


def _ctx(days):
    now = datetime.utcnow()
    return {"days": days, "now": now, "start": now - timedelta(days=days), "prev": now - timedelta(days=days * 2)}


def _period(c, model, col, *extra):
    """(count in the selected period, count in the previous one of the same length)."""
    return _count(model, col, c["start"], c["now"], *extra), _count(model, col, c["prev"], c["start"], *extra)


def _s_overview(c):
    opens = ReadEvent.kind == "open"
    users, o_users = _period(c, User, User.created_at)
    mangas, o_mangas = _period(c, Manga, Manga.created_at)
    chapters, o_chapters = _period(c, Chapter, Chapter.created_at)
    views, o_views = _period(c, ReadEvent, ReadEvent.created_at, opens)
    total_mangas = Manga.query.count()
    return {"overview": {"users": User.query.count(), "users_change": _pct(users, o_users),
                         "mangas": total_mangas, "mangas_change": _pct(mangas, o_mangas),
                         "chapters": Chapter.query.count(), "chapters_change": _pct(chapters, o_chapters),
                         "views": _soft(lambda: ReadEvent.query.filter(opens).count(), 0), "views_change": _pct(views, o_views)},
            "performance": {"new_users": users, "new_users_change": _pct(users, o_users),
                            "new_mangas": mangas, "new_mangas_change": _pct(mangas, o_mangas),
                            "average_views": round(views / total_mangas, 1) if total_mangas else 0, "average_reading_time": 0}}


def _s_activity(c):
    buckets = _buckets(c["days"])
    first = buckets[0][0]
    since = datetime(first.year, first.month, first.day)
    return {"activity": {"labels": [b[2] for b in buckets],
                         "users": _series(_daily(User.created_at, since), buckets),
                         "views": _series(_daily(ReadEvent.created_at, since, ReadEvent.kind == "open"), buckets),
                         "reading": _series(_daily(ReadEvent.created_at, since, ReadEvent.kind == "complete"), buckets)}}


def _s_content(c):
    by_type = _group(Manga, Manga.content_type)
    return {"content": {"labels": [TYPE_LABELS.get(k, k.capitalize()) for k in by_type], "values": list(by_type.values())}}


def _s_reading(c):
    views, _ = _period(c, ReadEvent, ReadEvent.created_at, ReadEvent.kind == "open")
    finished, _ = _period(c, ReadEvent, ReadEvent.created_at, ReadEvent.kind == "complete")
    comments, _ = _period(c, Comment, Comment.created_at)
    favorites, _ = _period(c, Favorite, Favorite.created_at)
    return {"reading": {"started": views, "completed": finished, "time": 0,
                        "completion_rate": round(min(100, finished / views * 100), 1) if views else 0},
            "engagement": {"comments": comments, "favorites": favorites, "bookmarks": 0, "shares": 0}}


def _s_top_mangas(c):
    start = c["start"]
    opened = dict(_soft(lambda: db.session.query(ReadEvent.manga_id, db.func.count())
                        .filter(ReadEvent.created_at >= start, ReadEvent.kind == "open").group_by(ReadEvent.manga_id).all(), []))
    readers = dict(db.session.query(ReadingProgress.manga_id, db.func.count()).filter(ReadingProgress.updated_at >= start)
                   .group_by(ReadingProgress.manga_id).all())
    ranking = sorted(_merge(opened, readers).items(), key=lambda kv: kv[1], reverse=True)[:10]
    mangas = {m.id: m for m in Manga.query.filter(Manga.id.in_([k for k, _ in ranking])).all()} if ranking else {}
    return {"top_mangas": [{"id": k, "title": mangas[k].title, "cover": mangas[k].cover_url, "views": v} for k, v in ranking if k in mangas]}


def _s_top_users(c):
    start = c["start"]
    u_open = dict(_soft(lambda: db.session.query(ReadEvent.user_id, db.func.count())
                        .filter(ReadEvent.created_at >= start, ReadEvent.kind == "open").group_by(ReadEvent.user_id).all(), []))
    u_hist = dict(db.session.query(ReadingProgress.user_id, db.func.count()).filter(ReadingProgress.updated_at >= start)
                  .group_by(ReadingProgress.user_id).all())
    ranking = sorted(_merge(u_open, u_hist).items(), key=lambda kv: kv[1], reverse=True)[:10]
    users = {u.id: u for u in User.query.filter(User.id.in_([k for k, _ in ranking])).all()} if ranking else {}
    return {"top_users": [{"id": k, "name": _name(users[k]), "avatar": users[k].photo_url, "activity": v} for k, v in ranking if k in users]}


def _s_categories(c):
    rows = (db.session.query(Category.name, db.func.count(Manga.id)).join(Manga, Manga.category_id == Category.id)
            .group_by(Category.id, Category.name).order_by(db.func.count(Manga.id).desc()).limit(10).all())
    # `top_categories`, not `categories`: the dashboard reads `categories` as a NUMBER (how many categories exist)
    return {"top_categories": [{"name": n, "count": n_} for n, n_ in rows]}


SECTIONS = (_s_overview, _s_activity, _s_content, _s_reading, _s_top_mangas, _s_top_users, _s_categories, lambda c: {"recent_activity": _recent()})


def _payload(days):
    """Each block is computed on its own: if one query fails the others are still returned (and the failure is logged)."""
    c, out = _ctx(days), {"range": days}
    for section in SECTIONS:
        try:
            out.update(section(c))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("statistics block failed")
    return out


def _recent(limit=20):
    """The latest things done in the app, all kinds mixed: [{user_name, user_avatar, action, content, created_at}]."""
    items = []

    def events():
        rows = (db.session.query(ReadEvent, User, Manga, Chapter).join(User, User.id == ReadEvent.user_id)
                .join(Manga, Manga.id == ReadEvent.manga_id).outerjoin(Chapter, Chapter.id == ReadEvent.chapter_id)
                .order_by(ReadEvent.created_at.desc()).limit(limit).all())
        for e, u, m, c in rows:
            label = m.title + (f" · ch. {c.number:g}" if c is not None and c.number is not None else "")
            items.append((e.created_at, u, "A terminé un chapitre" if e.kind == "complete" else "A ouvert un chapitre", label))

    def comments():
        for cm, u, m in (db.session.query(Comment, User, Manga).join(User, User.id == Comment.user_id)
                         .outerjoin(Manga, Manga.id == Comment.manga_id).order_by(Comment.created_at.desc()).limit(limit).all()):
            items.append((cm.created_at, u, "A commenté", m.title if m else "-"))

    def favorites():
        for f, u, m in (db.session.query(Favorite, User, Manga).join(User, User.id == Favorite.user_id)
                        .join(Manga, Manga.id == Favorite.manga_id).order_by(Favorite.created_at.desc()).limit(limit).all()):
            items.append((f.created_at, u, "A ajouté aux favoris", m.title))

    def signups():
        for u in User.query.order_by(User.created_at.desc()).limit(limit).all():
            items.append((u.created_at, u, "Nouvelle inscription", "-"))

    for source in (events, comments, favorites, signups):
        _soft(source, None)
    items.sort(key=lambda t: t[0] or datetime.min, reverse=True)
    return [{"user_name": _name(u), "user_avatar": u.photo_url, "action": action, "content": content,
             "created_at": (when.isoformat() + "Z") if when else None} for when, u, action, content in items[:limit]]


def _flat():
    """The totals of the first version of this route (used by the dashboard)."""
    week = datetime.utcnow() - timedelta(days=7)
    return {
        "users": User.query.count(), "mangas": Manga.query.count(), "chapters": Chapter.query.count(),
        "categories": Category.query.count(), "comments": Comment.query.count(),
        "reports_pending": Report.query.filter_by(status="pending").count(),
        "new_users_7d": User.query.filter(User.created_at >= week).count(),
        "users_by_status": _group(User, User.status), "mangas_by_status": _group(Manga, Manga.status),
        "chapters_by_status": _group(Chapter, Chapter.status),
    }


@statistics_bp.get("/")
@require_admin
def statistics():
    days = request.args.get("range", 7, type=int)
    days = days if days in RANGES else 7
    payload = {**_flat(), **_payload(days)}       # ONE dict: passing both to jsonify(**a, **b) fails when a key is in both
    return jsonify(success=True, statistics=payload, **payload)


@statistics_bp.get("/summary")
@require_admin
def summary():
    return statistics()
