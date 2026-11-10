from datetime import datetime

from flask import Blueprint, jsonify, request

from database import db
from models.comment import Comment
from models.manga import Manga
from models.report import Report
from utils.authz import current_user, require_admin, require_user
from utils.http import fail, paginate
from utils.security import clean_multiline, limiter

reports_bp = Blueprint("reports", __name__)
STATUSES = {"pending", "reviewing", "resolved", "approved", "rejected"}


@reports_bp.get("/")
@require_admin
def list_reports():
    q = Report.query
    if request.args.get("status") in STATUSES:
        q = q.filter(Report.status == request.args["status"])
    return paginate(q.order_by(Report.created_at.desc()), lambda r: r.to_dict(), key="reports")


@reports_bp.get("/search")
@require_admin
def search_reports():
    return list_reports()


@reports_bp.get("/<int:report_id>")
@require_admin
def get_report(report_id):
    r = Report.query.get(report_id)
    return jsonify(r.to_dict()) if r else fail("Signalement introuvable", 404)


@reports_bp.post("/")
@require_user
def create_report():
    user = current_user()
    if not limiter.allow(f"report:{user.id}", 10, 3600):
        return fail("Trop de signalements.", 429)
    data = request.get_json(silent=True) or {}
    reason = clean_multiline(data.get("reason"), 500)
    if not reason:
        return fail("reason obligatoire")
    if data.get("manga_id") and not Manga.query.get(data["manga_id"]):
        return fail("Manga introuvable", 404)
    if data.get("comment_id") and not Comment.query.get(data["comment_id"]):
        return fail("Commentaire introuvable", 404)
    r = Report(user_id=user.id, manga_id=data.get("manga_id"), comment_id=data.get("comment_id"),
               reason=reason, status="pending")
    db.session.add(r)
    db.session.commit()
    return jsonify(success=True, message="Signalement créé", report=r.to_dict()), 201


def _resolve(report_id, status=None):
    r = Report.query.get(report_id)
    if not r:
        return fail("Signalement introuvable", 404)
    data = request.get_json(silent=True) or {}
    status = status or data.get("status")
    if status not in STATUSES:
        return fail("Statut invalide")
    r.status = status
    r.moderator_id = current_user().id
    if "note" in data or "moderator_note" in data:
        r.moderator_note = clean_multiline(data.get("note") or data.get("moderator_note"), 1000) or None
    r.resolved_at = datetime.utcnow() if status in {"resolved", "approved", "rejected"} else None
    db.session.commit()
    return jsonify(success=True, report=r.to_dict())


@reports_bp.patch("/<int:report_id>")
@require_admin
def patch_report(report_id):
    return _resolve(report_id)


@reports_bp.put("/<int:report_id>")
@require_admin
def put_report(report_id):
    return _resolve(report_id)


@reports_bp.patch("/<int:report_id>/approve")
@require_admin
def approve(report_id):
    return _resolve(report_id, "approved")


@reports_bp.patch("/<int:report_id>/reject")
@require_admin
def reject(report_id):
    return _resolve(report_id, "rejected")


@reports_bp.delete("/<int:report_id>")
@require_admin
def delete_report(report_id):
    r = Report.query.get(report_id)
    if not r:
        return fail("Signalement introuvable", 404)
    db.session.delete(r)
    db.session.commit()
    return jsonify(success=True, message="Signalement supprimé")


@reports_bp.get("/statistics")
@require_admin
def statistics():
    c = lambda s: Report.query.filter_by(status=s).count()
    return jsonify(success=True, statistics={"total": Report.query.count(), "pending": c("pending"),
                                             "reviewing": c("reviewing"), "resolved": c("resolved"),
                                             "approved": c("approved"), "rejected": c("rejected")})


@reports_bp.get("/count")
@require_admin
def count():
    return jsonify(success=True, total_reports=Report.query.count())


@reports_bp.get("/status")
def status():
    return jsonify(service="Reports", status="online")
