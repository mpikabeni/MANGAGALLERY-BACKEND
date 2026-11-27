"""Routes called by the "Maintenance" buttons of Admin -> Paramètres (they used to answer 404 because only /api/system existed).

There is no application cache in this backend, so "clear the cache" and "refresh" only confirm that the database session is healthy.
"""
from flask import Blueprint, jsonify

from database import db
from utils.authz import require_admin

maintenance_bp = Blueprint("maintenance", __name__)


def _check_database():
    db.session.rollback()
    db.session.execute(db.text("SELECT 1"))


@maintenance_bp.post("/cache/clear")
@require_admin
def clear_cache():
    _check_database()
    return jsonify(success=True, message="Aucun cache applicatif à vider : rien n'était conservé.")


@maintenance_bp.post("/refresh")
@require_admin
def refresh():
    _check_database()
    return jsonify(success=True, message="Données actualisées.")
