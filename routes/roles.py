from flask import Blueprint, jsonify, request

from database import db
from models.role import Role
from models.user import User
from utils.authz import is_admin, require_admin
from utils.http import fail
from utils.security import clean_multiline, clean_text

roles_bp = Blueprint("roles", __name__)
RESERVED = {"admin", "super_admin"}


@roles_bp.get("/")
@require_admin
def list_roles():
    return jsonify([r.to_dict() for r in Role.query.order_by(Role.id).all()])


@roles_bp.get("/search")
@require_admin
def search_roles():
    return list_roles()


@roles_bp.get("/<int:role_id>")
@require_admin
def get_role(role_id):
    r = Role.query.get(role_id)
    return jsonify(r.to_dict()) if r else fail("Rôle introuvable", 404)


@roles_bp.post("/")
@require_admin
def create_role():
    data = request.get_json(silent=True) or {}
    name = clean_text(data.get("name"), 30)
    if not name:
        return fail("name obligatoire")
    if name.lower() in RESERVED or Role.query.filter(db.func.lower(Role.name) == name.lower()).first():
        return fail("Ce nom de rôle n'est pas disponible", 409)
    perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    r = Role(name=name, description=clean_multiline(data.get("description"), 255) or None,
             permissions=perms, is_system=False, is_active=True)
    db.session.add(r)
    db.session.commit()
    return jsonify(success=True, role=r.to_dict()), 201


@roles_bp.put("/<int:role_id>")
@require_admin
def update_role(role_id):
    r = Role.query.get(role_id)
    if not r:
        return fail("Rôle introuvable", 404)
    data = request.get_json(silent=True) or {}
    if r.is_system or r.name in RESERVED:
        return fail("Les rôles système ne sont pas modifiables", 403)
    if "name" in data:
        name = clean_text(data["name"], 30)
        if not name or name.lower() in RESERVED:
            return fail("Nom de rôle invalide")
        r.name = name
    if "description" in data:
        r.description = clean_multiline(data["description"], 255) or None
    if isinstance(data.get("permissions"), dict):
        r.permissions = data["permissions"]
    if "is_active" in data:
        r.is_active = bool(data["is_active"])
    db.session.commit()
    return jsonify(success=True, role=r.to_dict())


@roles_bp.patch("/<int:role_id>/permissions")
@require_admin
def update_permissions(role_id):
    r = Role.query.get(role_id)
    if not r:
        return fail("Rôle introuvable", 404)
    if r.is_system or r.name in RESERVED:
        return fail("Les rôles système ne sont pas modifiables", 403)
    perms = (request.get_json(silent=True) or {}).get("permissions")
    if not isinstance(perms, dict):
        return fail("permissions doit être un objet")
    r.permissions = perms
    db.session.commit()
    return jsonify(success=True, role=r.to_dict())


@roles_bp.delete("/<int:role_id>")
@require_admin
def delete_role(role_id):
    r = Role.query.get(role_id)
    if not r:
        return fail("Rôle introuvable", 404)
    if r.is_system or r.name in RESERVED:
        return fail("Les rôles système ne peuvent pas être supprimés", 403)
    db.session.delete(r)
    db.session.commit()
    return jsonify(success=True, message="Rôle supprimé")


@roles_bp.patch("/<int:user_id>/assign")
@require_admin
def assign_role(user_id):
    u = User.query.get(user_id)
    if not u:
        return fail("Utilisateur introuvable", 404)
    if is_admin(u):
        return fail("Le rôle de l'administrateur ne peut pas être modifié", 403)
    name = str((request.get_json(silent=True) or {}).get("role", "user")).strip()
    if name in RESERVED:
        return fail("Aucun autre administrateur ne peut être créé", 403)
    role = Role.query.filter_by(name=name).first()
    if name != "user" and not role:
        return fail("Rôle introuvable", 404)
    u.role, u.role_id = name, (role.id if role else None)
    db.session.commit()
    return jsonify(success=True, user=u.to_dict())


@roles_bp.get("/status")
def status():
    return jsonify(service="Roles", status="online")
