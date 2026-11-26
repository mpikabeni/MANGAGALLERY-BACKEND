"""Admin import from the catalogue sites that serve METADATA only: AniList, MyAnimeList (Jikan), Kitsu, MangaUpdates.

(MangaDex, the 5th source, keeps its own routes in routes/mangadex.py because it also serves the chapters.)
An import creates the fiche - cover stored in our database, synopsis in French, genres, credit link - and NO chapters:
the admin then adds the chapters (PDF / CBZ upload), or leaves the title in "Bientôt" / as a hidden draft.
The browser only sends the id: title, cover and rating are read again from the site, and an adult title can only go to
La Sainte Culture.
"""
import threading

from flask import Blueprint, jsonify, request

from database import db
from models.manga import SECTION_ADULT, SECTION_NORMAL, Manga
from routes.mangas import _check_combo
from routes.uploads import _public_url, _save
from services import catalog
from services import mangadex as md
from services.chapter_import import ImportFailure
from services.translate import translate
from utils.authz import require_admin
from utils.http import fail
from utils.security import clean_multiline, clean_text
from utils.slug import slugify, unique_slug

catalog_bp = Blueprint("catalog", __name__)
_lock = threading.Lock()          # one import at a time: the free APIs have strict rate limits


@catalog_bp.get("/sources")
@require_admin
def sources():
    """The 5 sources shown as tabs in the admin."""
    return jsonify(success=True, sources=[{"key": k, **v} for k, v in catalog.SOURCES.items()])


@catalog_bp.get("/search")
@require_admin
def search():
    """?source=anilist|jikan|kitsu|mangaupdates &q= &section=normal|sainte_culture &format=''|manhwa|manhua|manga &offset=0"""
    source = request.args.get("source", "")
    section = request.args.get("section", SECTION_NORMAL)
    try:
        result = catalog.search(source, (request.args.get("q") or "").strip()[:100], section == SECTION_ADULT,
                                request.args.get("format", ""), max(0, request.args.get("offset", 0, type=int)))
    except catalog.CatalogError as exc:
        return fail(str(exc), 502)
    items = result["items"]
    ids = [i["id"] for i in items]
    known = {m.external_id: m.id for m in Manga.query.filter(Manga.source == source, Manga.external_id.in_(ids)).all()} if ids else {}
    titles = {t.lower() for (t,) in db.session.query(Manga.title).filter(db.func.lower(Manga.title).in_([i["title"].lower() for i in items])).all()} if items else set()
    for i in items:
        i["imported_id"] = known.get(i["id"])
        i["same_title"] = i["title"].lower() in titles and not i["imported_id"]      # same name already added from another source
    return jsonify(success=True, items=items, next=result["next"], has_more=result["has_more"])


def _synopsis(text, lang):
    """-> (text, kind): 'auto' (machine-translated from English), 'en' or 'none'. These sites write their synopsis in English."""
    if not text:
        return "", "none"
    if lang == "fr":
        french = translate(text)
        if french:
            return french + "\n\n(Synopsis traduit automatiquement de l'anglais.)", "auto"
    return text, "en"


@catalog_bp.post("/import")
@require_admin
def import_title():
    """{source, id, section, content_type, lang, visibility: 'public' (shown in Bientôt) | 'hidden' (draft)}"""
    data = request.get_json(silent=True) or {}
    source, ident = data.get("source"), str(data.get("id") or "")
    section, ctype = data.get("section", SECTION_NORMAL), data.get("content_type", "manga")
    lang = "fr" if data.get("lang", "fr") == "fr" else "en"
    visibility = "hidden" if data.get("visibility") == "hidden" else "public"
    err = _check_combo(section, ctype)
    if err:
        return fail(err)
    if source not in catalog.CLIENTS:
        return fail("Source inconnue.")
    if not _lock.acquire(blocking=False):
        return fail("Un import est déjà en cours, patiente quelques secondes.", 429)
    try:
        if Manga.query.filter_by(source=source, external_id=ident).first():
            return fail("Ce titre est déjà dans ton catalogue.")
        item = catalog.get_one(source, ident)
        if item["rating"] == "adult" and section != SECTION_ADULT:
            return fail("Ce titre est classé adulte : importe-le dans La Sainte Culture.")
        text, kind = _synopsis(item["description"], lang)
        cover = None
        if catalog.cover_allowed(item["cover_url"]):
            try:
                raw, _ = md.fetch_bytes(item["cover_url"])
                blob = _save(raw, 900)
                db.session.flush()
                cover = _public_url(blob.id)
            except (md.MangaDexError, ImportFailure):
                cover = None                                  # the title is still imported, without cover
        description = clean_multiline(text, 4800) or ""
        if item["genres"]:
            description = (description + "\n\nGenres : " + ", ".join(item["genres"]) + ".").strip()
        manga = Manga(title=clean_text(item["title"], 255) or "Sans titre", slug=unique_slug(Manga, slugify(item["title"], "manga")),
                      description=description or None, cover_url=cover, status=item["status"], visibility=visibility,
                      section=section, content_type=ctype, source=source, external_id=ident, source_lang=None,
                      coming_soon=(visibility == "public"), announced_at=None)
        db.session.add(manga)
        db.session.commit()
        return jsonify(success=True, manga=manga.to_dict(), synopsis=kind, cover=bool(cover), visibility=visibility), 201
    except catalog.CatalogError as exc:
        db.session.rollback()
        return fail(str(exc), 502)
    finally:
        _lock.release()
