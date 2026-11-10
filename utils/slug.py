import re
import unicodedata


def slugify(text, fallback="item"):
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:120] or fallback


def unique_slug(model, base, exclude_id=None):
    slug, n = base, 2
    while True:
        q = model.query.filter_by(slug=slug)
        if exclude_id:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{n}"
        n += 1
