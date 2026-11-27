"""Ratings (1-5 stars) given by readers at the END OF EACH CHAPTER, and the two rankings built from them: titles and chapters."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from database import db
from models.chapter import Chapter
from models.manga import SECTION_ADULT, SECTION_NORMAL, Manga
from models.rating import ChapterRating
from routes.mangas import _serialize_batch
from services.ratings import MAX_SCORE, MIN_SCORE, chapter_summary, ensure_table, has_read_chapter, summary
from utils.authz import current_user, require_user, viewer_adult_ok, viewer_is_admin
from utils.http import fail
from utils.sections import adult_denied, can_view_manga, requested_section, requested_type
from utils.security import limiter

ratings_bp = Blueprint("ratings", __name__)
ratings_bp.before_request(ensure_table)

# period -> number of days (None = all time)
PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
ALIASES = {"week": "7d", "month": "30d", "1m": "30d", "3m": "90d", "3months": "90d", "alltime": "all", "all-time": "all"}
PRIOR_VOTES = 3          # a title / chapter needs a few votes before its average can outrank the others (see _bayes)
MAX_LIMIT = 50


def _bayes(count, total, prior_mean):
    """Weighted rating: (v / (v + m)) * R + (m / (v + m)) * C. One single 5-star vote therefore cannot beat an item with 200 votes at 4.7."""
    return (count / (count + PRIOR_VOTES)) * (total / count) + (PRIOR_VOTES / (count + PRIOR_VOTES)) * prior_mean


def _chapter_for_vote(chapter_id):
    """The chapter, if the caller may see it (published + public chapter of a visible title; admins see everything), else None."""
    c = Chapter.query.get(chapter_id)
    if not c or not can_view_manga(Manga.query.get(c.manga_id)):
        return None
    if not viewer_is_admin() and (c.status != "published" or c.visibility != "public"):
        return None
    return c


# ------------------------------------------------------------------ one chapter: vote at the end of the chapter
@ratings_bp.get("/chapter/<int:chapter_id>")
@require_user
def get_chapter_rating(chapter_id):
    c = _chapter_for_vote(chapter_id)
    if not c:
        return fail("Chapitre introuvable", 404)
    return jsonify(success=True, **chapter_summary(c.manga_id, c.id, current_user().id))


@ratings_bp.put("/chapter/<int:chapter_id>")
@require_user
def rate_chapter(chapter_id):
    uid = current_user().id
    if not limiter.allow(f"rate:{uid}", 30, 60):
        return fail("Trop d'actions, réessaie dans un instant.", 429)
    c = _chapter_for_vote(chapter_id)
    if not c:
        return fail("Chapitre introuvable", 404)
    try:
        score = int((request.get_json(silent=True) or {}).get("score"))
    except (TypeError, ValueError):
        score = 0
    if not MIN_SCORE <= score <= MAX_SCORE:
        return fail(f"La note doit être comprise entre {MIN_SCORE} et {MAX_SCORE}.")
    if not has_read_chapter(uid, c.manga_id, c.id):
        return fail("Termine ce chapitre pour le noter.", 403, code="NOT_READ")

    now = datetime.utcnow()
    r = ChapterRating.query.filter_by(user_id=uid, chapter_id=c.id).first()
    if r:
        r.score, r.updated_at = score, now
    else:
        db.session.add(ChapterRating(user_id=uid, manga_id=c.manga_id, chapter_id=c.id, score=score, created_at=now, updated_at=now))
    try:
        db.session.commit()
    except Exception:                       # double tap: two inserts at once -> the row exists now, update it
        db.session.rollback()
        r = ChapterRating.query.filter_by(user_id=uid, chapter_id=c.id).first()
        if not r:
            return fail("Erreur d'enregistrement", 500)
        r.score, r.updated_at = score, now
        db.session.commit()
    return jsonify(success=True, **chapter_summary(c.manga_id, c.id, uid))


@ratings_bp.delete("/chapter/<int:chapter_id>")
@require_user
def remove_chapter_rating(chapter_id):
    uid = current_user().id
    c = Chapter.query.get(chapter_id)
    if not c:
        return fail("Chapitre introuvable", 404)
    ChapterRating.query.filter_by(user_id=uid, chapter_id=chapter_id).delete()
    db.session.commit()
    return jsonify(success=True, **chapter_summary(c.manga_id, c.id, uid))


# ------------------------------------------------------------------ one title: the sum of its chapters' votes
@ratings_bp.get("/manga/<int:manga_id>")
@require_user
def get_manga_rating(manga_id):
    if not can_view_manga(Manga.query.get(manga_id)):
        return fail("Manga introuvable", 404)
    return jsonify(success=True, **summary(manga_id, current_user().id))


# ------------------------------------------------------------------ rankings
def _ranking_args():
    """(period, section, ctype, limit) from the query string, or (error_response, None, None, None)."""
    period = (request.args.get("period") or "7d").strip().lower()
    period = ALIASES.get(period, period)
    if period not in PERIODS:
        return fail("Période invalide (7d, 30d, 90d ou all)"), None, None, None
    section = requested_section() or SECTION_NORMAL
    if section == SECTION_ADULT and not viewer_adult_ok():
        return adult_denied(), None, None, None
    limit = max(1, min(request.args.get("limit", 10, type=int) or 10, MAX_LIMIT))
    return period, section, requested_type(), limit


def _eligible(q, period, section, ctype):
    """Only public, published, readable content counts, and only the votes cast during the period."""
    q = (q.join(Manga, Manga.id == ChapterRating.manga_id).join(Chapter, Chapter.id == ChapterRating.chapter_id)
         .filter(Manga.section == section, Manga.visibility == "public", Manga.coming_soon.is_(False),
                 Chapter.status == "published", Chapter.visibility == "public"))
    if ctype:
        q = q.filter(Manga.content_type == ctype)
    days = PERIODS[period]
    if days:
        q = q.filter(ChapterRating.updated_at >= datetime.utcnow() - timedelta(days=days))
    return q


def _sorted_rows(rows):
    """rows = [(id, count, total)] -> (sorted by weighted rating, number of votes)."""
    rows = [(i, int(n), int(t)) for i, n, t in rows]
    votes = sum(n for _, n, _ in rows)
    prior_mean = (sum(t for _, _, t in rows) / votes) if votes else 0
    rows.sort(key=lambda r: (-_bayes(r[1], r[2], prior_mean), -r[1], r[0]))
    return rows, votes


@ratings_bp.get("/ranking")
@require_user
def ranking():
    """Best rated TITLES. ?period=7d|30d|90d|all  &section=normal|sainte_culture  &type=manga|webtoon|comic  &limit=1..50

    A title is rated through the votes given at the end of its chapters. Only the votes cast during the period count,
    so the list moves with what readers like right now."""
    period, section, ctype, limit = _ranking_args()
    if period not in PERIODS:
        return period                                    # error response
    q = _eligible(db.session.query(ChapterRating.manga_id, db.func.count(ChapterRating.id), db.func.sum(ChapterRating.score)),
                  period, section, ctype)
    rows, votes = _sorted_rows(q.group_by(ChapterRating.manga_id).all())
    top = rows[:limit]

    by_id = {m.id: m for m in Manga.query.filter(Manga.id.in_([r[0] for r in top])).all()} if top else {}
    top = [r for r in top if r[0] in by_id]
    batch = _serialize_batch([by_id[r[0]] for r in top])
    items = []
    for rank, (d, (_, n, total)) in enumerate(zip(batch, top), start=1):
        d["rank"] = rank
        d["rating"] = {"average": round(total / n, 1), "count": n}       # votes of the period (rating_avg / rating_count = all time)
        items.append(d)
    return jsonify(success=True, period=period, items=items, total=len(rows), votes=votes)


@ratings_bp.get("/ranking/chapters")
@require_user
def chapters_ranking():
    """Best rated CHAPTERS (same filters as /ranking). Each item: the chapter, its title (`manga`), `rank` and `rating`."""
    period, section, ctype, limit = _ranking_args()
    if period not in PERIODS:
        return period
    q = _eligible(db.session.query(ChapterRating.chapter_id, db.func.count(ChapterRating.id), db.func.sum(ChapterRating.score)),
                  period, section, ctype)
    rows, votes = _sorted_rows(q.group_by(ChapterRating.chapter_id).all())
    top = rows[:limit]

    chapters = {c.id: c for c in Chapter.query.filter(Chapter.id.in_([r[0] for r in top])).all()} if top else {}
    mangas = {m.id: m for m in Manga.query.filter(Manga.id.in_({c.manga_id for c in chapters.values()})).all()} if chapters else {}
    items = []
    for cid, n, total in top:
        c = chapters.get(cid)
        m = mangas.get(c.manga_id) if c else None
        if not c or not m:
            continue
        items.append({"rank": len(items) + 1, "id": c.id, "number": c.number, "title": c.title, "manga_id": m.id,
                      "manga": {"id": m.id, "title": m.title, "cover_url": m.cover_url, "content_type": m.content_type},
                      "rating": {"average": round(total / n, 1), "count": n}})
    return jsonify(success=True, period=period, items=items, total=len(rows), votes=votes)
