"""Rating helpers shared by routes/ratings.py (vote, rankings) and routes/mangas.py (average shown on every card).

A reader votes (1-5 stars) at the END OF EACH CHAPTER. The rating of a title is computed from the votes of its chapters."""
from database import db
from models.library import ReadEvent, ReadingProgress
from models.rating import ChapterRating

MIN_SCORE, MAX_SCORE = 1, 5


def batch_stats(manga_ids):
    """{manga_id: (count, average)} for the given titles (all the votes of all their chapters), in one query.
    Never raises: a rating problem must not break the catalogue."""
    ids = list(manga_ids)
    if not ids:
        return {}
    try:
        rows = (db.session.query(ChapterRating.manga_id, db.func.count(ChapterRating.id), db.func.avg(ChapterRating.score))
                .filter(ChapterRating.manga_id.in_(ids)).group_by(ChapterRating.manga_id).all())
        return {mid: (int(n), float(avg)) for mid, n, avg in rows}
    except Exception:
        db.session.rollback()
        return {}


def chapter_stats(chapter_ids):
    """{chapter_id: (count, average)} for the given chapters, in one query (shown in the chapter list). Never raises."""
    ids = list(chapter_ids)
    if not ids:
        return {}
    try:
        rows = (db.session.query(ChapterRating.chapter_id, db.func.count(ChapterRating.id), db.func.avg(ChapterRating.score))
                .filter(ChapterRating.chapter_id.in_(ids)).group_by(ChapterRating.chapter_id).all())
        return {cid: (int(n), float(avg)) for cid, n, avg in rows}
    except Exception:
        db.session.rollback()
        return {}


_table_ready = False


def ensure_table():
    """The `chapter_ratings` table is created at startup; this is a safety net (checkfirst) in case that start-up step was skipped or lost a race."""
    global _table_ready
    if _table_ready:
        return
    try:
        ChapterRating.__table__.create(db.engine, checkfirst=True)
        _table_ready = True
    except Exception:
        db.session.rollback()


def has_read_chapter(user_id, manga_id, chapter_id):
    """A reader may vote on a chapter only once he has FINISHED it: the chapter is in his reading history (last page reached)
    or a "complete" event was recorded for it by the statistics."""
    p = ReadingProgress.query.filter_by(user_id=user_id, manga_id=manga_id).first()
    if p and chapter_id in (p.read_chapters or []):
        return True
    if p and p.chapter_id == chapter_id and p.total and p.page >= p.total:
        return True
    return db.session.query(ReadEvent.id).filter_by(user_id=user_id, chapter_id=chapter_id, kind="complete").first() is not None


def _distribution(query):
    rows = query.with_entities(ChapterRating.score, db.func.count(ChapterRating.id)).group_by(ChapterRating.score).all()
    dist = {s: 0 for s in range(MIN_SCORE, MAX_SCORE + 1)}
    for score, n in rows:
        dist[int(score)] = int(n)
    count = sum(dist.values())
    average = round(sum(s * n for s, n in dist.items()) / count, 1) if count else None
    return dist, count, average


def chapter_summary(manga_id, chapter_id, user_id=None):
    """Average, number of votes and distribution (1..5) of ONE chapter, the caller's own vote and whether the caller may vote."""
    dist, count, average = _distribution(ChapterRating.query.filter(ChapterRating.chapter_id == chapter_id))
    mine, can_rate = None, False
    if user_id:
        r = ChapterRating.query.filter_by(user_id=user_id, chapter_id=chapter_id).first()
        mine = r.score if r else None
        can_rate = mine is not None or has_read_chapter(user_id, manga_id, chapter_id)
    return {"chapter_id": chapter_id, "average": average, "count": count, "distribution": dist, "mine": mine, "can_rate": can_rate}


def summary(manga_id, user_id=None):
    """Rating of a TITLE = all the votes given to its chapters: average, number of votes, distribution (1..5).
    With `user_id`, also how many chapters of the title the caller has rated."""
    dist, count, average = _distribution(ChapterRating.query.filter(ChapterRating.manga_id == manga_id))
    out = {"average": average, "count": count, "distribution": dist}
    if user_id:
        out["my_votes"] = ChapterRating.query.filter_by(user_id=user_id, manga_id=manga_id).count()
    return out
