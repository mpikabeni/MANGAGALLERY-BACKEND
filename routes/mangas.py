from flask import Blueprint, jsonify, request

from database import db
from models.category import Category
from models.chapter import Chapter
from models.manga import ALL_TYPES, SECTION_ADULT, SECTION_NORMAL, SECTIONS, TYPES_BY_SECTION, Manga
from utils.authz import current_user, require_admin, require_user, viewer_adult_ok, viewer_is_admin
from utils.http import fail, like_pattern, paginate, pick, search_term
from utils.security import clean_multiline, clean_text, is_safe_url
from routes.uploads import release_urls
from utils.sections import adult_denied, requested_section, requested_type
from utils.slug import slugify, unique_slug

mangas_bp = Blueprint("mangas", __name__)

STATUSES = {"ongoing", "completed", "paused", "hiatus", "cancelled"}
VISIBILITIES = {"public", "private", "hidden"}


def _public_chapters(query):
    return query.filter(Chapter.visibility == "public", Chapter.status == "published")


def _serialize_batch(rows):
    ids = [m.id for m in rows]
    stats = {}
    if ids:
        q = db.session.query(Chapter.manga_id, db.func.count(Chapter.id), db.func.max(Chapter.number)) \
            .filter(Chapter.manga_id.in_(ids))
        if not viewer_is_admin():
            q = _public_chapters(q)
        stats = {mid: (n, last) for mid, n, last in q.group_by(Chapter.manga_id)}
    cats = {c.id: c for c in Category.query.filter(Category.id.in_({m.category_id for m in rows if m.category_id})).all()} if rows else {}
    out = []
    for m in rows:
        d = m.to_dict()
        n, last = stats.get(m.id, (0, None))
        d["chapters_count"] = n
        d["last_chapter"] = last
        c = cats.get(m.category_id)
        d["category"] = {"id": c.id, "name": c.name, "slug": c.slug, "color": c.color} if c else None
        out.append(d)
    return out


def _query(section=None):
    q = Manga.query
    if not viewer_is_admin():
        q = q.filter(Manga.visibility == "public")
    if section:
        q = q.filter(Manga.section == section)
    ctype = requested_type()
    if ctype:
        q = q.filter(Manga.content_type == ctype)
    term = search_term()
    if term:
        q = q.filter(Manga.title.ilike(like_pattern(term), escape="\\"))
    if request.args.get("category_id", type=int):
        q = q.filter(Manga.category_id == request.args.get("category_id", type=int))
    status = request.args.get("status")
    if status in STATUSES:
        q = q.filter(Manga.status == status)
    sort = request.args.get("sort", "latest")
    order = {"title": Manga.title.asc(), "updated": Manga.updated_at.desc(), "oldest": Manga.created_at.asc()}
    return q.order_by(order.get(sort, Manga.created_at.desc()), Manga.id.desc())


@mangas_bp.get("/")
@require_user
def list_mangas():
    section = requested_section()
    if section == SECTION_ADULT and not viewer_adult_ok():
        return adult_denied()
    return paginate(_query(section), batch=_serialize_batch, key="mangas")


@mangas_bp.get("/search")
@require_user
def search_mangas():
    return list_mangas()


@mangas_bp.get("/<int:manga_id>")
@require_user
def get_manga(manga_id):
    manga = Manga.query.get(manga_id)
    if not manga or (manga.visibility != "public" and not viewer_is_admin()):
        return fail("Manga introuvable", 404)
    if manga.section == SECTION_ADULT and not viewer_adult_ok():
        return adult_denied()
    data = _serialize_batch([manga])[0]
    cq = Chapter.query.filter_by(manga_id=manga.id)
    if not viewer_is_admin():
        cq = _public_chapters(cq)
    data["chapters"] = [{"id": c.id, "number": c.number, "title": c.title,
                         "published_at": c.published_at.isoformat() if c.published_at else None,
                         "pages_count": len(c.pages or [])}
                        for c in cq.order_by(Chapter.number.asc()).all()]
    return jsonify(success=True, manga=data, **data)


def _validated(data, partial=False):
    """Return (clean_fields, error_message)."""
    out = {}
    if "title" in data or not partial:
        title = clean_text(data.get("title"), 255)
        if not title:
            return None, "Le titre est obligatoire"
        out["title"] = title
    if "description" in data:
        out["description"] = clean_multiline(data.get("description"), 5000) or None
    for key in ("cover_url", "banner_url"):
        if key in data:
            v = data.get(key)
            if v and not is_safe_url(v):
                return None, f"{key} invalide (http/https uniquement)"
            out[key] = v or None
    if "status" in data:
        if data["status"] not in STATUSES:
            return None, "Statut invalide"
        out["status"] = data["status"]
    if "visibility" in data:
        if data["visibility"] not in VISIBILITIES:
            return None, "Visibilité invalide"
        out["visibility"] = data["visibility"]
    if "section" in data:
        if data["section"] not in SECTIONS:
            return None, "Section invalide (normal ou sainte_culture)"
        out["section"] = data["section"]
    if "content_type" in data:
        if data["content_type"] not in ALL_TYPES:
            return None, "Type invalide (manga, webtoon ou comic)"
        out["content_type"] = data["content_type"]
    if "category_id" in data:
        cid = data.get("category_id")
        if cid in (None, ""):
            out["category_id"] = None
        else:
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                return None, "Catégorie invalide"
            if not Category.query.get(cid):
                return None, "Catégorie introuvable"
            out["category_id"] = cid
    return out, None


def _check_combo(section, ctype):
    """La Sainte Culture only accepts webtoons and bandes dessinées."""
    if ctype not in TYPES_BY_SECTION.get(section, ()):
        if section == SECTION_ADULT:
            return "La Sainte Culture accepte uniquement les webtoons et les bandes dessinées."
        return "Type invalide pour cette section."
    return None


@mangas_bp.post("/")
@require_admin
def create_manga():
    data = request.get_json(silent=True) or {}
    fields, err = _validated(pick(data, ("title", "slug", "description", "cover_url", "banner_url", "status",
                                         "visibility", "category_id", "section", "content_type")))
    if err:
        return fail(err)
    fields.setdefault("status", "ongoing")
    fields.setdefault("visibility", "public")
    fields.setdefault("section", SECTION_NORMAL)
    fields.setdefault("content_type", "manga")
    err = _check_combo(fields["section"], fields["content_type"])
    if err:
        return fail(err)
    fields.pop("slug", None)
    fields["slug"] = unique_slug(Manga, slugify(data.get("slug") or fields["title"], "manga"))
    user = current_user()
    manga = Manga(author_id=user.id if user else None, **fields)
    db.session.add(manga)
    db.session.commit()
    return jsonify(success=True, message="Manga créé", manga=manga.to_dict()), 201


@mangas_bp.put("/<int:manga_id>")
@require_admin
def update_manga(manga_id):
    manga = Manga.query.get(manga_id)
    if not manga:
        return fail("Manga introuvable", 404)
    data = request.get_json(silent=True) or {}
    fields, err = _validated(pick(data, ("title", "description", "cover_url", "banner_url", "status",
                                         "visibility", "category_id", "section", "content_type")), partial=True)
    if err:
        return fail(err)
    err = _check_combo(fields.get("section", manga.section), fields.get("content_type", manga.content_type))
    if err:
        return fail(err)
    release_urls([old for k, old in (("cover_url", manga.cover_url), ("banner_url", manga.banner_url))
                  if k in fields and fields[k] != old])
    for k, v in fields.items():
        setattr(manga, k, v)
    if data.get("slug"):
        manga.slug = unique_slug(Manga, slugify(data["slug"], "manga"), exclude_id=manga.id)
    db.session.commit()
    return jsonify(success=True, message="Manga mis à jour", manga=manga.to_dict())


@mangas_bp.delete("/<int:manga_id>")
@require_admin
def delete_manga(manga_id):
    manga = Manga.query.get(manga_id)
    if not manga:
        return fail("Manga introuvable", 404)
    release_urls([manga.cover_url, manga.banner_url])
    for chapter in manga.chapters:
        release_urls(chapter.pages)
    db.session.delete(manga)
    db.session.commit()
    return jsonify(success=True, message="Manga supprimé")


def _set_image(manga_id, field):
    manga = Manga.query.get(manga_id)
    if not manga:
        return fail("Manga introuvable", 404)
    url = request.form.get(field) or (request.get_json(silent=True) or {}).get(field)
    if not is_safe_url(url):
        return fail(f"{field} invalide (http/https uniquement)")
    setattr(manga, field, url)
    db.session.commit()
    return jsonify(success=True, manga=manga.to_dict())


@mangas_bp.post("/<int:manga_id>/cover")
@require_admin
def upload_cover(manga_id):
    return _set_image(manga_id, "cover_url")


@mangas_bp.post("/<int:manga_id>/banner")
@require_admin
def upload_banner(manga_id):
    return _set_image(manga_id, "banner_url")


@mangas_bp.get("/status")
def status():
    return jsonify(service="Mangas", status="online")
