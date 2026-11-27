"""Import titles (fiches) and chapters from MangaDex, and relay their page images.

Admin only: search / import / sync.   Public (signed URL): the page image relay used by the reader.
Credits to MangaDex and to the scanlation group are shown in the app; delete a title to honour a removal request."""
import threading
import time
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, request

from config import Config
from database import db
from models.chapter import Chapter
from models.manga import SECTION_ADULT, SECTION_NORMAL, Manga
from routes.mangas import _check_combo
from routes.uploads import _public_url, _save
from services import mangadex as md
from services.announcements import chapter_stats, maybe_announce
from services.translate import NOTE, to_french
from services.chapter_import import ImportFailure
from utils.authz import require_admin
from utils.http import fail
from utils.security import clean_multiline, clean_text
from utils.slug import slugify, unique_slug

mangadex_bp = Blueprint("mangadex", __name__)
_import_lock = threading.Lock()      # one import at a time keeps us far below MangaDex's rate limits


def _lang():
    lang = (request.values.get("lang") or (request.get_json(silent=True) or {}).get("lang") or "fr").lower()
    return lang if lang in ("fr", "en", "es", "pt-br", "de", "it", "ar", "id") else "fr"


@mangadex_bp.get("/search")
@require_admin
def search():
    """?q=&section=normal|sainte_culture&lang=fr&offset=0  -> titles, with the ones already imported flagged."""
    section = request.args.get("section", SECTION_NORMAL)
    try:
        items, total = md.search((request.args.get("q") or "").strip()[:100], _lang(), section == SECTION_ADULT,
                                 max(0, request.args.get("offset", 0, type=int)), completed_only=request.args.get("completed") == "1",
                                 any_lang=request.args.get("coming") == "1", origin=request.args.get("format", ""))
    except md.MangaDexError as exc:
        return fail(str(exc), 502)
    ids = [i["id"] for i in items]
    known = {m.external_id: m.id for m in Manga.query.filter(Manga.source == "mangadex", Manga.external_id.in_(ids)).all()} if ids else {}
    for i in items:
        i["imported_id"] = known.get(i["id"])
    return jsonify(success=True, items=items, total=total)


@mangadex_bp.get("/info")
@require_admin
def info():
    """?id=&lang=&status=&declared=  ->  how many chapters exist in that language, from which to which, any gap, complete or not.
    Shown BEFORE publishing; one light MangaDex request per title (cached 10 min)."""
    try:
        summary = md.chapter_summary(request.args.get("id", ""), _lang(), request.args.get("declared") or None, request.args.get("status"))
    except md.MangaDexError as exc:
        return fail(str(exc), 502)
    return jsonify(success=True, **summary)


def usable_chapters(feed):
    """Chapters we keep: numbered above 0 (no chapter 0, no unnumbered), one per number, oldest first."""
    seen, out = set(), []
    for ch in feed:
        try:
            number = float(ch["chapter"])
        except (TypeError, ValueError):
            continue
        if number <= 0 or number in seen:
            continue
        seen.add(number)
        out.append((number, ch))
    out.sort(key=lambda t: t[0])
    return out


def _insert_chapters(manga, chapters):
    have = {c.number for c in Chapter.query.filter_by(manga_id=manga.id).all()}
    added = 0
    for number, ch in chapters:
        if number in have:
            continue
        label = str(int(number)) if number == int(number) else str(number).replace(".", "-")
        try:
            published = datetime.fromisoformat(ch["publish_at"].replace("Z", "+00:00")).replace(tzinfo=None) if ch["publish_at"] else datetime.utcnow()
        except ValueError:
            published = datetime.utcnow()
        db.session.add(Chapter(
            manga_id=manga.id, number=number, title=clean_text(ch["title"], 255), slug=f"chapter-{label}",
            pages=[md.PLACEHOLDER + str(i) for i in range(ch["pages"])], status="published", visibility="public",
            published_at=published, source="mangadex", external_id=ch["id"], group_name=clean_text(ch["group"], 255)))
        added += 1
        if added % 100 == 0:
            db.session.commit()
    manga.updated_at = datetime.utcnow()
    db.session.commit()
    return added


def sync_chapters(manga):
    """Add the chapters MangaDex has and we do not. Safe to run again (new releases)."""
    chapters = usable_chapters(md.chapter_feed(manga.external_id, manga.source_lang or "fr"))
    added = _insert_chapters(manga, chapters)
    return added, len(chapters) - added


def _synopsis(info, lang=None):
    """-> (text, kind). The synopsis is ALWAYS French, whatever the chapter language:
    'vf' (MangaDex has a French one), 'auto' (machine-translated), 'en' (translation unavailable: original kept) or 'none'."""
    if info.get("description_fr"):
        return info["description_fr"], "vf"
    source, text = "en", info.get("description_en")
    if not text and info.get("description_other"):
        source, text = info["description_other"]
    text = text or info.get("description") or ""
    if not text:
        return "", "none"
    result = to_french(text, source)
    if result and result[1] == "already":
        return result[0], "vf"
    if result:
        return result[0] + "\n\n" + NOTE, "auto"
    return text, "en"


@mangadex_bp.post("/import")
@require_admin
def import_title():
    """{id, section, content_type, lang, notify}: creates the title (synopsis in the chosen language, cover stored in our database)
    and imports ALL its chapters numbered from the first one that exists. A title without any readable chapter is refused."""
    data = request.get_json(silent=True) or {}
    mid, lang = data.get("id"), _lang()
    section, ctype = data.get("section", SECTION_NORMAL), data.get("content_type", "manga")
    notify = data.get("notify", True) is not False
    err = _check_combo(section, ctype)
    if err:
        return fail(err)
    if not _import_lock.acquire(blocking=False):
        return fail("Un import est déjà en cours, patiente quelques secondes.", 429)
    try:
        existing = Manga.query.filter_by(source="mangadex", external_id=mid).first() if md.UUID_RE.match(mid or "") else None
        if existing and data.get("mode") == "coming":
            return fail("Ce titre est déjà dans ton catalogue.")
        if existing:
            added, skipped = sync_chapters(existing)
            if notify:
                maybe_announce(existing)
            return jsonify(success=True, manga=existing.to_dict(), added=added, skipped=skipped, already=True)
        info = md.get_manga(mid, lang)
        if info["rating"] in md.ADULT_RATINGS and section != SECTION_ADULT:
            return fail("Ce titre est classé adulte : importe-le dans La Sainte Culture.")
        coming = data.get("mode") == "coming"
        chapters = [] if coming else usable_chapters(md.chapter_feed(mid, lang))
        if not coming and not chapters:
            return fail(f"Aucun chapitre lisible en « {lang} » (numéro supérieur à 0) : le titre n'a pas été importé. "
                        "Tu peux l'ajouter à « Bientôt ».")
        text, synopsis_kind = _synopsis(info, lang)
        cover = None
        if info["cover_url"]:
            try:
                raw, _ = md.fetch_bytes(info["cover_url"])
                blob = _save(raw, 900)
                db.session.flush()
                cover = _public_url(blob.id)
            except (md.MangaDexError, ImportFailure):
                cover = None                      # the title is still imported, without cover
        description = clean_multiline(text, 4800) or ""
        genres = ", ".join(info["genres"])
        if genres:
            description = (description + f"\n\nGenres : {genres}.").strip()
        manga = Manga(title=clean_text(info["title"], 255) or "Sans titre", slug=unique_slug(Manga, slugify(info["title"], "manga")),
                      description=description or None, cover_url=cover, status=info["status"], visibility="public",
                      section=section, content_type=ctype, source="mangadex", external_id=mid, source_lang=lang,
                      coming_soon=coming, announced_at=None if (notify or coming) else datetime.utcnow())
        db.session.add(manga)
        db.session.commit()
        if coming:                                    # "Bientôt": fiche only, no chapters, released automatically when complete in VF
            return jsonify(success=True, manga=manga.to_dict(), added=0, skipped=0, already=False, synopsis=synopsis_kind,
                           coming=True, count=0, first=None, last=None, notified=False), 201
        added = _insert_chapters(manga, chapters)
        if notify:
            maybe_announce(manga)
        count, first, last = chapter_stats(manga.id)
        return jsonify(success=True, manga=manga.to_dict(), added=added, skipped=0, already=False, synopsis=synopsis_kind,
                       first=first, last=last, count=count, notified=notify), 201
    except md.MangaDexError as exc:
        db.session.rollback()
        return fail(str(exc), 502)
    finally:
        _import_lock.release()


@mangadex_bp.post("/sync/<int:manga_id>")
@require_admin
def sync(manga_id):
    manga = Manga.query.get(manga_id)
    if not manga or manga.source != "mangadex":
        return fail("Ce titre n'a pas été importé de MangaDex.", 404)
    if not _import_lock.acquire(blocking=False):
        return fail("Un import est déjà en cours, patiente quelques secondes.", 429)
    try:
        added, skipped = sync_chapters(manga)
        return jsonify(success=True, added=added, skipped=skipped)
    except md.MangaDexError as exc:
        db.session.rollback()
        return fail(str(exc), 502)
    finally:
        _import_lock.release()


@mangadex_bp.get("/page/<int:chapter_id>/<int:index>.jpg")
def page(chapter_id, index):
    """Public relay of one page image. The signed query string (made by the gated read endpoints) is the access token."""
    if not md.verify(chapter_id, index, request.args.get("e"), request.args.get("s")):
        return fail("Lien expiré", 403)
    chapter = Chapter.query.get(chapter_id)
    if not chapter or chapter.source != "mangadex":
        return fail("Introuvable", 404)
    try:
        data, ctype = md.page_image(chapter.external_id, index)
    except md.MangaDexError as exc:
        current_app.logger.warning("MangaDex page relay failed: %s", exc)
        return fail(str(exc), 502)
    resp = Response(data, mimetype=ctype)
    resp.headers["Cache-Control"] = "private, max-age=21600"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    return resp


def release_ready():
    """For every "Bientôt" title imported from MangaDex: when its chapters are now COMPLETE in the chosen language (series finished,
    no missing number), import them all, move the title out of "Bientôt" and announce it to the users. Returns the released titles."""
    released = []
    for manga in Manga.query.filter_by(source="mangadex", coming_soon=True).all():
        lang = manga.source_lang or "fr"
        try:
            info = md.get_manga(manga.external_id, lang)
            summary = md.chapter_summary(manga.external_id, lang, info.get("declared_last"), info["status"])
            if summary["count"] and summary["complete"]:
                sync_chapters(manga)
                maybe_announce(manga)                 # clears coming_soon and sends the "Nouveau" notification + bot message
                released.append(manga.title)
        except md.MangaDexError:
            db.session.rollback()
            continue
        time.sleep(0.5)                                # MangaDex: stay far below 5 requests / second
    return released


@mangadex_bp.post("/check-coming")
@require_admin
def check_coming():
    if not _import_lock.acquire(blocking=False):
        return fail("Un import est déjà en cours, patiente quelques secondes.", 429)
    try:
        released = release_ready()
        return jsonify(success=True, released=released, count=len(released))
    finally:
        _import_lock.release()
