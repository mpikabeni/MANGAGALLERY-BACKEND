from flask import jsonify, request

from config import Config


def fail(message, status=400, **extra):
    return jsonify(success=False, message=message, **extra), status


def page_args():
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    raw = request.args.get("per_page", type=int) or request.args.get("limit", type=int) or Config.DEFAULT_PAGE_SIZE
    return page, max(1, min(raw, Config.MAX_PAGE_SIZE))


def search_term():
    return (request.args.get("q") or request.args.get("search") or "").strip()[:100]


def like_pattern(term):
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def paginate(query, serialize=None, key="items", batch=None):
    """Paginated payload understood by both the mini app and the admin panel."""
    page, per_page = page_args()
    total = query.count()
    rows = query.limit(per_page).offset((page - 1) * per_page).all()
    items = batch(rows) if batch else [serialize(r) for r in rows]
    pages = max((total + per_page - 1) // per_page, 1)
    payload = {"success": True, "items": items, "data": items, "total": total,
               "page": page, "per_page": per_page, "total_pages": pages, "pages": pages}
    if key != "items":
        payload[key] = items
    return jsonify(payload)


def pick(data, allowed):
    """Whitelist fields (prevents mass assignment)."""
    return {k: data[k] for k in allowed if k in data}
