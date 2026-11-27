"""Ratings (1-5 stars) given by readers once they have read a title, and the rankings built from them."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from database import db
from models.chapter import Chapter
from models.manga import SECTION_ADULT, SECTION_NORMAL, Manga
from models.rating import Rating
from routes.mangas import _serialize_batch
from services.ratings import MAX_SCORE, MIN_SCORE, ensure_table, has_read, summary
from utils.authz import current_user, require_user, viewer_adult_ok
from utils.http import fail
from utils.sections import adult_denied, can_view_manga, requested_section, requested_type
from utils.security import limiter

ratings_bp = Blueprint("ratings", __name__)
ratings_bp.before_request(ensure_table)

# period -> number of days (None = all time)
PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
ALIASES = {"week": "7d", "month": "30d", "1m": "30d", "3m": "90d", "3months": "90d", "alltime": "all", "all-time": "all"}
PRIOR_VOTES = 3          # a title needs a few votes before its average can outrank the others (see _bayes)
MAX_LIMIT = 50


def _bayes(count, total, prior_mean):
    """Weighted rating: (v / (v + m)) * R + (m / (v + m)) * C. One single 5-star vote therefore cannot beat a title with 200 votes at 4.7."""
    return (count / (count + PRIOR_VOTES)) * (total / count) + (PRIOR_VOTES / (count + PRIOR_VOTES)) * prior_mean


@ratings_bp.get("/manga/<int:manga_id>")
@require_user
def get_rating(manga_id):
    if not can_view_manga(Manga.query.get(manga_id)):
        return fail("Manga introuvable", 404)
    return jsonify(success=True, **summary(manga_id, current_user().id))


@ratings_bp.put("/manga/<int:manga_id>")
@require_user
def rate(manga_id):
    uid = current_user().id
    if not limiter.allow(f"rate:{uid}", 30, 60):
        return fail("Trop d'actions, réessaie dans un instant.", 429)
    if not can_view_manga(Manga.query.get(manga_id)):
        return fail("Manga introuvable", 404)
    try:
        score = int((request.get_json(silent=True) or {}).get("score"))
    except (TypeError, ValueError):
        score = 0
    if not MIN_SCORE <= score <= MAX_SCORE:
        return fail(f"La note doit être comprise entre {MIN_SCORE} et {MAX_SCORE}.")
    if not has_read(uid, manga_id):
        return fail("Termine au moins un chapitre pour noter ce titre.", 403, code="NOT_READ")

    now = datetime.utcnow()
    r = Rating.query.filter_by(user_id=uid, manga_id=manga_id).first()
    if r:
        r.score, r.updated_at = score, now
    else:
        db.session.add(Rating(user_id=uid, manga_id=manga_id, score=score, created_at=now, updated_at=now))
    try:
        db.session.commit()
    except Exception:                       # double tap: two inserts at once -> the row exists now, update it
        db.session.rollback()
        r = Rating.query.filter_by(user_id=uid, manga_id=manga_id).first()
        if not r:
            return fail("Erreur d'enregistrement", 500)
        r.score, r.updated_at = score, now
        db.session.commit()
    return jsonify(success=True, **summary(manga_id, uid))


@ratings_bp.delete("/manga/<int:manga_id>")
@require_user
def remove_rating(manga_id):
    uid = current_user().id
    Rating.query.filter_by(user_id=uid, manga_id=manga_id).delete()
    db.session.commit()
    return jsonify(success=True, **summary(manga_id, uid))


@ratings_bp.get("/ranking")
@require_user
def ranking():
    """Best rated titles. ?period=7d|30d|90d|all  &section=normal|sainte_culture  &type=manga|webtoon|comic  &limit=1..50

    Only the votes cast during the period count, so the list moves with what readers like right now."""
    period = (request.args.get("period") or "7d").strip().lower()
    period = ALIASES.get(period, period)
    if period not in PERIODS:
        return fail("Période invalide (7d, 30d, 90d ou all)")
    section = requested_section() or SECTION_NORMAL
    if section == SECTION_ADULT and not viewer_adult_ok():
        return adult_denied()
    limit = max(1, min(request.args.get("limit", 10, type=int) or 10, MAX_LIMIT))

    q = (db.session.query(Rating.manga_id, db.func.count(Rating.id), db.func.sum(Rating.score))
         .join(Manga, Manga.id == Rating.manga_id)
         .filter(Manga.section == section, Manga.visibility == "public", Manga.coming_soon.is_(False),
                 db.exists().where(db.and_(Chapter.manga_id == Manga.id, Chapter.status == "published", Chapter.visibility == "public"))))
    ctype = requested_type()
    if ctype:
        q = q.filter(Manga.content_type == ctype)
    days = PERIODS[period]
    if days:
        q = q.filter(Rating.updated_at >= datetime.utcnow() - timedelta(days=days))
    rows = [(mid, int(n), int(total)) for mid, n, total in q.group_by(Rating.manga_id).all()]

    votes = sum(n for _, n, _ in rows)
    prior_mean = (sum(t for _, _, t in rows) / votes) if votes else 0
    rows.sort(key=lambda r: (-_bayes(r[1], r[2], prior_mean), -r[1], r[0]))
    top = rows[:limit]

    by_id = {m.id: m for m in Manga.query.filter(Manga.id.in_([r[0] for r in top])).all()} if top else {}
    batch = _serialize_batch([by_id[r[0]] for r in top if r[0] in by_id])
    items = []
    for rank, (d, (_, n, total)) in enumerate(zip(batch, [r for r in top if r[0] in by_id]), start=1):
        d["rank"] = rank
        d["rating"] = {"average": round(total / n, 1), "count": n}       # votes of the period (rating_avg / rating_count = all time)
        items.append(d)
    return jsonify(success=True, period=period, items=items, total=len(rows), votes=votes)
