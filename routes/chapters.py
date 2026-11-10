from datetime import datetime

from flask import Blueprint, jsonify, request

from database import db
from models.chapter import Chapter
from models.manga import Manga
from utils.authz import require_admin, require_user, viewer_is_admin
from utils.http import fail, like_pattern, paginate, search_term
from utils.security import clean_text, is_safe_url
from utils.slug import slugify

chapters_bp = Blueprint("chapters", __name__)

STATUSES = {"draft", "published"}
VISIBILITIES = {"public", "private", "hidden"}


def _visible(q):
    if viewer_is_admin():
        return q
    return q.filter(Chapter.visibility == "public", Chapter.status == "published")


def _light(c):
    d = c.to_dict()
    d["pages_count"] = len(d.pop("pages", []) or [])
    return d


def _clean_pages(pages):
    if not isinstance(pages, list) or len(pages) > 500:
        return None
    out = []
    for p in pages:
        url = p.get("url") if isinstance(p, dict) else p
        if not is_safe_url(url):
            return None
        out.append(url.strip())
    return out


@chapters_bp.get("/")
@require_user
def list_chapters():
    q = _visible(Chapter.query)
    manga_id = request.args.get("manga_id", type=int)
    if manga_id:
        q = q.filter(Chapter.manga_id == manga_id)
    status = request.args.get("status")
    if status in STATUSES and viewer_is_admin():
        q = q.filter(Chapter.status == status)
    term = search_term()
    if term:
        q = q.filter(Chapter.title.ilike(like_pattern(term), escape="\\"))
    sort = Chapter.number.desc() if request.args.get("order") == "desc" else Chapter.number.asc()
    return paginate(q.order_by(Chapter.manga_id, sort), _light, key="chapters")


@chapters_bp.get("/search")
@require_user
def search_chapters():
    return list_chapters()


@chapters_bp.get("/latest")
@require_user
def latest_chapters():
    """Latest published chapters with their manga (home page 'updates')."""
    q = _visible(Chapter.query).join(Manga, Manga.id == Chapter.manga_id)
    if not viewer_is_admin():
        q = q.filter(Manga.visibility == "public")
    q = q.order_by(Chapter.published_at.desc().nullslast(), Chapter.id.desc())

    def batch(rows):
        mangas = {m.id: m for m in Manga.query.filter(Manga.id.in_({c.manga_id for c in rows})).all()} if rows else {}
        out = []
        for c in rows:
            d = _light(c)
            m = mangas.get(c.manga_id)
            d["manga"] = {"id": m.id, "title": m.title, "cover_url": m.cover_url} if m else None
            out.append(d)
        return out
    return paginate(q, batch=batch, key="chapters")


@chapters_bp.get("/<int:chapter_id>")
@require_user
def get_chapter(chapter_id):
    c = _visible(Chapter.query).filter(Chapter.id == chapter_id).first()
    if not c:
        return fail("Chapitre introuvable", 404)
    return jsonify(c.to_dict())


@chapters_bp.get("/<int:chapter_id>/read")
@require_user
def read_chapter(chapter_id):
    c = _visible(Chapter.query).filter(Chapter.id == chapter_id).first()
    if not c:
        return fail("Chapitre introuvable", 404)
    siblings = _visible(Chapter.query).filter(Chapter.manga_id == c.manga_id)
    prev_c = siblings.filter(Chapter.number < c.number).order_by(Chapter.number.desc()).first()
    next_c = siblings.filter(Chapter.number > c.number).order_by(Chapter.number.asc()).first()
    manga = Manga.query.get(c.manga_id)
    return jsonify(success=True, chapter=c.to_dict(),
                   manga={"id": manga.id, "title": manga.title} if manga else None,
                   prev_id=prev_c.id if prev_c else None, next_id=next_c.id if next_c else None)


@chapters_bp.post("/")
@require_admin
def create_chapter():
    data = request.get_json(silent=True) or {}
    try:
        manga_id, number = int(data.get("manga_id")), float(data.get("number"))
    except (TypeError, ValueError):
        return fail("manga_id et number sont obligatoires")
    if number < 0:
        return fail("Numéro de chapitre invalide")
    if not Manga.query.get(manga_id):
        return fail("Manga introuvable", 404)
    if Chapter.query.filter_by(manga_id=manga_id, number=number).first():
        return fail("Ce chapitre existe déjà", 409)
    status = data.get("status", "published")
    visibility = data.get("visibility", "public")
    if status not in STATUSES or visibility not in VISIBILITIES:
        return fail("Statut ou visibilité invalide")
    pages = _clean_pages(data.get("pages") or [])
    if pages is None:
        return fail("pages : liste d'URLs http/https (500 max)")
    num_txt = str(int(number)) if number == int(number) else str(number).replace(".", "-")
    c = Chapter(manga_id=manga_id, number=number, title=clean_text(data.get("title"), 255),
                slug=slugify(data.get("slug") or f"chapter-{num_txt}"), pages=pages, status=status,
                visibility=visibility, published_at=datetime.utcnow() if status == "published" else None)
    db.session.add(c)
    db.session.commit()
    return jsonify(success=True, message="Chapitre créé", chapter=c.to_dict()), 201


@chapters_bp.put("/<int:chapter_id>")
@require_admin
def update_chapter(chapter_id):
    c = Chapter.query.get(chapter_id)
    if not c:
        return fail("Chapitre introuvable", 404)
    data = request.get_json(silent=True) or {}
    if "number" in data:
        try:
            number = float(data["number"])
        except (TypeError, ValueError):
            return fail("Numéro invalide")
        if number < 0:
            return fail("Numéro invalide")
        dup = Chapter.query.filter(Chapter.manga_id == c.manga_id, Chapter.number == number, Chapter.id != c.id).first()
        if dup:
            return fail("Ce chapitre existe déjà", 409)
        c.number = number
    if "title" in data:
        c.title = clean_text(data["title"], 255)
    if "slug" in data and data["slug"]:
        c.slug = slugify(data["slug"])
    if "status" in data:
        if data["status"] not in STATUSES:
            return fail("Statut invalide")
        c.status = data["status"]
        if c.status == "published" and not c.published_at:
            c.published_at = datetime.utcnow()
    if "visibility" in data:
        if data["visibility"] not in VISIBILITIES:
            return fail("Visibilité invalide")
        c.visibility = data["visibility"]
    if "pages" in data:
        pages = _clean_pages(data["pages"])
        if pages is None:
            return fail("pages : liste d'URLs http/https (500 max)")
        c.pages = pages
    db.session.commit()
    return jsonify(success=True, message="Chapitre mis à jour", chapter=c.to_dict())


@chapters_bp.delete("/<int:chapter_id>")
@require_admin
def delete_chapter(chapter_id):
    c = Chapter.query.get(chapter_id)
    if not c:
        return fail("Chapitre introuvable", 404)
    db.session.delete(c)
    db.session.commit()
    return jsonify(success=True, message="Chapitre supprimé")


@chapters_bp.post("/<int:chapter_id>/pages")
@require_admin
def set_pages(chapter_id):
    c = Chapter.query.get(chapter_id)
    if not c:
        return fail("Chapitre introuvable", 404)
    pages = _clean_pages((request.get_json(silent=True) or {}).get("pages"))
    if pages is None:
        return fail("pages : liste d'URLs http/https (500 max)")
    c.pages = pages
    db.session.commit()
    return jsonify(success=True, message="Pages mises à jour", chapter=c.to_dict())


@chapters_bp.get("/status")
def status():
    return jsonify(service="Chapters", status="online")
