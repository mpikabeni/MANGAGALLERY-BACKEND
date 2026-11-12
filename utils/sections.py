"""Helpers shared by the routes that expose mangas / chapters: which section is requested, and is it allowed."""
from flask import request

from models.manga import ALL_TYPES, SECTION_ADULT, SECTION_NORMAL, SECTIONS
from utils.authz import viewer_adult_ok, viewer_is_admin
from utils.http import fail

ADULT_MESSAGE = "Espace réservé aux adultes (18+). Confirme ton âge pour continuer."


def adult_denied():
    """403 payload understood by the mini app (it then shows the age confirmation screen)."""
    return fail(ADULT_MESSAGE, 403, code="ADULT_REQUIRED")


def requested_section():
    """Section asked through ?section=. Returns "normal", "sainte_culture" or None (= every section).

    - the mini app always passes the section explicitly;
    - without the parameter, the administrator sees everything and everybody else only the normal gallery.
    """
    value = (request.args.get("section") or "").strip().lower()
    if value in SECTIONS:
        return value
    if value == "all" and viewer_is_admin():
        return None
    return None if (viewer_is_admin() and not value) else SECTION_NORMAL


def requested_type():
    value = (request.args.get("type") or "").strip().lower()
    return value if value in ALL_TYPES else None


def can_view_manga(manga):
    """Visibility + age rule for a single manga."""
    if not manga:
        return False
    if manga.visibility != "public" and not viewer_is_admin():
        return False
    return manga.section != SECTION_ADULT or viewer_adult_ok()
