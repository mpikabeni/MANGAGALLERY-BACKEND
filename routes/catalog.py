"""Admin import from the catalogue sites that serve METADATA only: AniList, MyAnimeList (Jikan), Kitsu, MangaUpdates.

(MangaDex, the 5th source, keeps its own routes in routes/mangadex.py because it also serves the chapters.)
An import creates the fiche - cover stored in our database, synopsis in French, genres, credit link - and NO chapters:
the admin then adds the chapters (PDF / CBZ upload), or leaves the title in "Bientôt" / as a hidden draft.
The browser only sends the id: title, cover and rating are read again from the site, and an adult title can only go to
La Sainte Culture.
"""
import re
import threading

from flask import Blueprint, jsonify, request

from database import db
from models.manga import SECTION_ADULT, SECTION_NORMAL, Manga
from routes.mangas import _check_combo
from routes.uploads import _public_url, _save
from services import catalog
from services import mangadex as md
from services.chapter_import import ImportFailure
from services.translate import NOTE, looks_french, to_french
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
                                request.args.get("format", ""), max(0, request.args.get("offset", 0, type=int)), request.args.get("lang", "fr"))
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


def _synopsis(item):
    """-> (text, kind). The synopsis is ALWAYS French: 'vf' (already French), 'auto' (machine-translated),
    'en' (no translation provider answered: original kept, see translate-synopses below) or 'none'."""
    text = item["description"]
    if not text:
        return "", "none"
    result = to_french(text, item.get("language"))      # None = unknown language: detected
    if result and result[1] == "already":
        return result[0], "vf"
    if result:
        return result[0] + "\n\n" + NOTE, "auto"
    return text, "en"


@catalog_bp.post("/import")
@require_admin
def import_title():
    """{source, id, section, content_type, visibility: 'public' (shown in Bientôt) | 'hidden' (draft)}"""
    data = request.get_json(silent=True) or {}
    source, ident = data.get("source"), str(data.get("id") or "")
    section, ctype = data.get("section", SECTION_NORMAL), data.get("content_type", "manga")
    visibility = "hidden" if data.get("visibility") == "hidden" else "public"
    if source in ("googlebooks", "internetarchive"):
        ctype = "comic"                                       # these sources only serve bandes dessinées
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
        text, kind = _synopsis(item)
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
        if item.get("extra"):
            description = (description + "\n\n" + item["extra"]).strip()       # BD: authors and publisher
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


# ------------------------------------------------------------------ translate the synopses already in the catalogue
_TAIL_RE = re.compile(r"\n\n(?:\(Synopsis traduit|Genres :|Auteur\(s\) :|Éditeur :)")


@catalog_bp.post("/translate-synopses")
@require_admin
def translate_synopses():
    """Translates, a few titles per call, the synopses that are not French yet. {after_id: 0} -> {translated, skipped, failed, next_after, done}.
    The admin page calls it again with `next_after` until `done`. It stops at the first failure (quota reached, provider down)."""
    after = max(0, int((request.get_json(silent=True) or {}).get("after_id") or 0))
    translated = skipped = failed = 0
    last, done = after, True
    rows = Manga.query.filter(Manga.id > after, Manga.description.isnot(None)).order_by(Manga.id).limit(120).all()
    for m in rows:
        last = m.id
        parts = _TAIL_RE.split(m.description, maxsplit=1)
        main, tail = parts[0].strip(), m.description[len(parts[0]):]
        if not main or looks_french(main):
            skipped += 1
            continue
        result = to_french(main, None)
        if not result:
            failed += 1
            done = False
            break
        if result[1] != "already":
            m.description = (result[0] + "\n\n" + NOTE + tail)[:5000]
            translated += 1
        else:
            skipped += 1
        if translated >= 3:
            done = False
            break
    else:
        done = len(rows) < 120
    db.session.commit()
    return jsonify(success=True, translated=translated, skipped=skipped, failed=failed, next_after=last, done=done and not failed)
