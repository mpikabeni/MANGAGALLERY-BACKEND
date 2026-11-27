"""Rating helpers shared by routes/ratings.py (vote, ranking) and routes/mangas.py (average shown on every card)."""
from database import db
from models.library import ReadEvent, ReadingProgress
from models.rating import Rating

MIN_SCORE, MAX_SCORE = 1, 5


def batch_stats(manga_ids):
    """{manga_id: (count, average)} for the given titles, in one query. Never raises: a rating problem must not break the catalogue."""
    ids = list(manga_ids)
    if not ids:
        return {}
    try:
        rows = (db.session.query(Rating.manga_id, db.func.count(Rating.id), db.func.avg(Rating.score))
                .filter(Rating.manga_id.in_(ids)).group_by(Rating.manga_id).all())
        return {mid: (int(n), float(avg)) for mid, n, avg in rows}
    except Exception:
        db.session.rollback()
        return {}


_table_ready = False


def ensure_table():
    """The `ratings` table is created at startup; this is a safety net (checkfirst) in case that start-up step was skipped or lost a race."""
    global _table_ready
    if _table_ready:
        return
    try:
        Rating.__table__.create(db.engine, checkfirst=True)
        _table_ready = True
    except Exception:
        db.session.rollback()


def has_read(user_id, manga_id):
    """A reader may vote only after finishing at least one chapter of the title: a chapter in the reading history, the last page of the
    chapter being read, or a "complete" event recorded by the statistics."""
    p = ReadingProgress.query.filter_by(user_id=user_id, manga_id=manga_id).first()
    if p and (p.read_chapters or (p.total and p.page >= p.total)):
        return True
    return db.session.query(ReadEvent.id).filter_by(user_id=user_id, manga_id=manga_id, kind="complete").first() is not None


def summary(manga_id, user_id=None):
    """Average, number of votes, distribution (1..5), the caller's own vote and whether the caller may vote."""
    rows = db.session.query(Rating.score, db.func.count(Rating.id)).filter(Rating.manga_id == manga_id).group_by(Rating.score).all()
    dist = {s: 0 for s in range(MIN_SCORE, MAX_SCORE + 1)}
    for score, n in rows:
        dist[int(score)] = int(n)
    count = sum(dist.values())
    average = round(sum(s * n for s, n in dist.items()) / count, 1) if count else None
    mine, can_rate = None, False
    if user_id:
        r = Rating.query.filter_by(user_id=user_id, manga_id=manga_id).first()
        mine = r.score if r else None
        can_rate = has_read(user_id, manga_id)
    return {"average": average, "count": count, "distribution": dist, "mine": mine, "can_rate": can_rate}
