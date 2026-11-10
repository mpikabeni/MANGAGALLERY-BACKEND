from flask import Blueprint, jsonify, request

from database import db
from models.role import Role
from models.user import User
from utils.authz import current_user, is_admin, require_admin
from utils.http import fail, like_pattern, paginate, search_term
from utils.security import clean_text, is_safe_url

users_bp = Blueprint("users", __name__)
STATUSES = {"active", "inactive", "suspended", "banned"}


def _protected(user):
    """The administrator account cannot be edited, disabled, demoted or deleted through the API."""
    return is_admin(user)


@users_bp.get("/")
@require_admin
def list_users():
    q = User.query
    term = search_term()
    if term:
        p = like_pattern(term)
        q = q.filter(db.or_(User.username.ilike(p, escape="\\"), User.first_name.ilike(p, escape="\\"),
                            User.last_name.ilike(p, escape="\\"), User.email.ilike(p, escape="\\")))
    if request.args.get("role"):
        q = q.filter(User.role == request.args["role"])
    if request.args.get("status") in STATUSES:
        q = q.filter(User.status == request.args["status"])
    return paginate(q.order_by(User.id), lambda u: u.to_dict(), key="users")


@users_bp.get("/search")
@require_admin
def search_users():
    return list_users()


@users_bp.get("/<int:user_id>")
@require_admin
def get_user(user_id):
    u = User.query.get(user_id)
    return jsonify(u.to_dict()) if u else fail("Utilisateur introuvable", 404)


@users_bp.post("/")
@require_admin
def create_user():
    data = request.get_json(silent=True) or {}
    username = clean_text(data.get("username"), 100)
    email = clean_text(data.get("email"), 255)
    if not username:
        return fail("Nom d'utilisateur obligatoire")
    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        return fail("Nom d'utilisateur déjà utilisé", 409)
    if email and User.query.filter_by(email=email).first():
        return fail("Email déjà utilisé", 409)
    status = data.get("status", "active")
    if status not in STATUSES:
        return fail("Statut invalide")
    u = User(username=username, email=email, first_name=clean_text(data.get("first_name")),
             last_name=clean_text(data.get("last_name")), role="user", status=status,
             is_verified=bool(data.get("is_verified", False)))
    db.session.add(u)
    db.session.commit()
    return jsonify(success=True, message="Utilisateur créé", user=u.to_dict()), 201


@users_bp.put("/<int:user_id>")
@require_admin
def update_user(user_id):
    u = User.query.get(user_id)
    if not u:
        return fail("Utilisateur introuvable", 404)
    if _protected(u) and u.id != current_user().id:
        return fail("Le compte administrateur est protégé", 403)
    data = request.get_json(silent=True) or {}
    if _protected(u) and ("status" in data or "role" in data):
        return fail("Le statut et le rôle de l'administrateur ne peuvent pas être modifiés", 403)
    for f in ("first_name", "last_name"):
        if f in data:
            setattr(u, f, clean_text(data[f]))
    if "username" in data:
        name = clean_text(data["username"], 100)
        if not name:
            return fail("Nom d'utilisateur invalide")
        if User.query.filter(db.func.lower(User.username) == name.lower(), User.id != u.id).first():
            return fail("Nom d'utilisateur déjà utilisé", 409)
        u.username = name
    if "email" in data:
        email = clean_text(data["email"], 255)
        if email and User.query.filter(User.email == email, User.id != u.id).first():
            return fail("Email déjà utilisé", 409)
        u.email = email
    if "photo_url" in data:
        if data["photo_url"] and not is_safe_url(data["photo_url"], allow_relative=False):
            return fail("photo_url invalide")
        u.photo_url = data["photo_url"] or None
    if "status" in data:
        if data["status"] not in STATUSES:
            return fail("Statut invalide")
        u.status = data["status"]
    if "is_verified" in data:
        u.is_verified = bool(data["is_verified"])
    db.session.commit()
    return jsonify(success=True, message="Utilisateur mis à jour", user=u.to_dict())


@users_bp.delete("/<int:user_id>")
@require_admin
def delete_user(user_id):
    u = User.query.get(user_id)
    if not u:
        return fail("Utilisateur introuvable", 404)
    if _protected(u):
        return fail("Le compte administrateur ne peut pas être supprimé", 403)
    db.session.delete(u)
    db.session.commit()
    return jsonify(success=True, message="Utilisateur supprimé")


@users_bp.patch("/<int:user_id>/status")
@require_admin
def set_status(user_id):
    u = User.query.get(user_id)
    if not u:
        return fail("Utilisateur introuvable", 404)
    if _protected(u):
        return fail("Le compte administrateur ne peut pas être désactivé", 403)
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in STATUSES:
        return fail("Statut invalide")
    u.status = status
    db.session.commit()
    return jsonify(success=True, user=u.to_dict())


@users_bp.patch("/<int:user_id>/role")
@require_admin
def set_role(user_id):
    u = User.query.get(user_id)
    if not u:
        return fail("Utilisateur introuvable", 404)
    if _protected(u):
        return fail("Le rôle de l'administrateur ne peut pas être modifié", 403)
    name = str((request.get_json(silent=True) or {}).get("role", "user")).strip()
    if name in ("admin", "super_admin"):
        return fail("Aucun autre administrateur ne peut être créé", 403)
    role = Role.query.filter_by(name=name).first()
    if name != "user" and not role:
        return fail("Rôle introuvable", 404)
    u.role, u.role_id = name, (role.id if role else None)
    db.session.commit()
    return jsonify(success=True, message="Rôle mis à jour", user=u.to_dict())


@users_bp.get("/status")
def status():
    return jsonify(service="Users", status="online")
