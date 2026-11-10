from flask import Blueprint, jsonify, request

from database import db
from models.category import Category
from utils.authz import require_admin, require_user, viewer_is_admin
from utils.http import fail, like_pattern, paginate, search_term
from utils.security import clean_multiline, clean_text
from utils.slug import slugify, unique_slug

categories_bp = Blueprint("categories", __name__)


def _query():
    q = Category.query
    if not viewer_is_admin():
        q = q.filter(Category.is_active.is_(True))
    term = search_term()
    if term:
        q = q.filter(Category.name.ilike(like_pattern(term), escape="\\"))
    st = request.args.get("status")
    if st in ("active", "disabled") and viewer_is_admin():
        q = q.filter(Category.is_active.is_(st == "active"))
    return q.order_by(Category.name.asc())


@categories_bp.get("/")
@require_user
def list_categories():
    if request.args.get("page") is None and request.args.get("limit") is None:
        return jsonify([c.to_dict() for c in _query().all()])  # small list, used by filters
    return paginate(_query(), lambda c: c.to_dict(), key="categories")


@categories_bp.get("/search")
@require_user
def search_categories():
    return list_categories()


@categories_bp.get("/<int:category_id>")
@require_user
def get_category(category_id):
    c = Category.query.get(category_id)
    if not c or (not c.is_active and not viewer_is_admin()):
        return fail("Catégorie introuvable", 404)
    return jsonify(c.to_dict())


def _color(v):
    import re
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else "#7C5CFF"


@categories_bp.post("/")
@require_admin
def create_category():
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get("name"), 100)
    if not name:
        return fail("Le nom est obligatoire")
    if Category.query.filter(db.func.lower(Category.name) == name.lower()).first():
        return fail("Cette catégorie existe déjà", 409)
    c = Category(name=name, slug=unique_slug(Category, slugify(data.get("slug") or name, "category")),
                 description=clean_multiline(data.get("description"), 500) or None,
                 icon=clean_text(data.get("icon"), 50), color=_color(data.get("color")),
                 is_active=bool(data.get("is_active", True)))
    db.session.add(c)
    db.session.commit()
    return jsonify(success=True, message="Catégorie créée", category=c.to_dict()), 201


@categories_bp.put("/<int:category_id>")
@require_admin
def update_category(category_id):
    c = Category.query.get(category_id)
    if not c:
        return fail("Catégorie introuvable", 404)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = clean_text(data["name"], 100)
        if not name:
            return fail("Le nom est obligatoire")
        c.name = name
    if data.get("slug"):
        c.slug = unique_slug(Category, slugify(data["slug"], "category"), exclude_id=c.id)
    if "description" in data:
        c.description = clean_multiline(data["description"], 500) or None
    if "icon" in data:
        c.icon = clean_text(data["icon"], 50)
    if "color" in data:
        c.color = _color(data["color"])
    if "is_active" in data:
        c.is_active = bool(data["is_active"])
    db.session.commit()
    return jsonify(success=True, message="Catégorie mise à jour", category=c.to_dict())


@categories_bp.delete("/<int:category_id>")
@require_admin
def delete_category(category_id):
    c = Category.query.get(category_id)
    if not c:
        return fail("Catégorie introuvable", 404)
    db.session.delete(c)
    db.session.commit()
    return jsonify(success=True, message="Catégorie supprimée")


@categories_bp.get("/statistics")
@require_admin
def statistics():
    cats = Category.query.all()
    return jsonify(success=True, statistics={"total": len(cats), "active": sum(bool(c.is_active) for c in cats),
                                             "items": [{"id": c.id, "name": c.name, "mangas": len(c.mangas)} for c in cats]})


@categories_bp.get("/count")
@require_admin
def count():
    return jsonify(success=True, total_categories=Category.query.count())


@categories_bp.get("/status")
def status():
    return jsonify(service="Categories", status="online")
