import time

from flask import Blueprint, jsonify

from config import Config
from database import db
from utils.authz import require_admin

system_bp = Blueprint("system", __name__)
START = time.time()


@system_bp.get("/info")
@require_admin
def info():
    return jsonify(success=True, system={"application": Config.APP_NAME, "version": Config.APP_VERSION,
                                         "environment": Config.APP_ENV,
                                         "uptime_seconds": int(time.time() - START)})


@system_bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        ok = True
    except Exception:
        ok = False
    return jsonify(success=ok, database="online" if ok else "offline"), 200 if ok else 503


@system_bp.get("/cache")
@require_admin
def cache():
    return jsonify(success=True, cache={"enabled": False, "status": "not_configured"})


@system_bp.post("/cache/clear")
@require_admin
def clear_cache():
    return jsonify(success=True, message="Aucun cache applicatif configuré")


@system_bp.post("/database/optimize")
@require_admin
def optimize():
    return jsonify(success=True, message="Optimisation PostgreSQL à effectuer chez l'hébergeur")


@system_bp.post("/backup")
@require_admin
def backup():
    return jsonify(success=False, message="Utilise les sauvegardes PostgreSQL de l'hébergeur"), 501


@system_bp.post("/backup/restore")
@require_admin
def restore():
    return jsonify(success=False, message="Restauration via l'hébergeur PostgreSQL"), 501


@system_bp.post("/restart")
@require_admin
def restart():
    return jsonify(success=False, message="Le redémarrage est géré par l'hébergeur"), 501


@system_bp.get("/status")
def status():
    return jsonify(service="System", status="online")
