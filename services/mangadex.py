"""MangaDex client (https://api.mangadex.org) - titles, chapters and page images.

MangaDex's acceptable use policy (https://api.mangadex.org/docs/): credit MangaDex, credit the scanlation groups when
chapters can be read, no ads and no paid services, and honour the removal requests of scanlation groups.
Page images are NOT hotlinkable from a browser: they are fetched by this server and relayed (see routes/mangadex.py).
"""
import hashlib
import hmac
import json
import re
import time
from urllib import error, parse, request

from config import Config

API = "https://api.mangadex.org"
UPLOADS = "https://uploads.mangadex.org"
USER_AGENT = "MangaGalleryFR/1.0 (Telegram mini app; non-commercial; credits MangaDex and scanlation groups)"
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SAFE_RATINGS = ["safe", "suggestive"]
ADULT_RATINGS = ["erotica", "pornographic"]
MAX_IMAGE_BYTES = 15 * 1024 * 1024
PLACEHOLDER = "mdx:"


class MangaDexError(Exception):
    """Message meant for the administrator (French)."""


def _open(url, timeout=20, accept="application/json"):
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        return request.urlopen(req, timeout=timeout)
    except error.HTTPError as exc:
        if exc.code == 429:
            raise MangaDexError("MangaDex limite le nombre de requêtes : patiente une minute puis réessaie.")
        if exc.code in (403, 404):
            raise MangaDexError(f"MangaDex a refusé la demande ({exc.code}).")
        raise MangaDexError(f"MangaDex a répondu avec une erreur ({exc.code}).")
    except (error.URLError, TimeoutError, OSError):
        raise MangaDexError("MangaDex est injoignable pour le moment. Réessaie dans un instant.")


def _get(path, params=None, timeout=20):
    url = API + path + (("?" + parse.urlencode(params, doseq=True)) if params else "")
    with _open(url, timeout) as resp:
        try:
            return json.loads(resp.read().decode("utf-8"))
        except ValueError:
            raise MangaDexError("Réponse illisible de MangaDex.")


def fetch_bytes(url, limit=MAX_IMAGE_BYTES, timeout=25):
    """-> (bytes, content_type). Used for page images and covers."""
    with _open(url, timeout, accept="image/*") as resp:
        ctype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not ctype.startswith("image/"):
            raise MangaDexError("MangaDex n'a pas renvoyé une image.")
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise MangaDexError("Image trop lourde.")
    return data, ctype


# ------------------------------------------------------------------ titles
def _pick(mapping, lang, fallbacks=("en",)):
    if not isinstance(mapping, dict) or not mapping:
        return ""
    for key in (lang, *fallbacks):
        if mapping.get(key):
            return mapping[key]
    return next(iter(mapping.values()), "") or ""


def _title(attrs, lang):
    title = attrs.get("title") or {}
    if title.get(lang):
        return title[lang]
    for alt in attrs.get("altTitles") or []:
        if alt.get(lang):
            return alt[lang]
    return _pick(title, lang, ("en", "ja-ro"))


def parse_manga(item, lang):
    a = item.get("attributes", {})
    cover = next((r for r in item.get("relationships", []) if r.get("type") == "cover_art"), None)
    file_name = ((cover or {}).get("attributes") or {}).get("fileName")
    tags = [t.get("attributes", {}) for t in a.get("tags", [])]
    names = [_pick(t.get("name"), "en") for t in tags]
    genres = [_pick(t.get("name"), "en") for t in tags if t.get("group") == "genre"]
    status = {"hiatus": "paused", "cancelled": "completed"}.get(a.get("status"), a.get("status") or "ongoing")
    guess = "webtoon" if ("Long Strip" in names or a.get("originalLanguage") in ("ko", "zh", "zh-hk")) else "manga"
    return {
        "id": item["id"], "title": _title(a, lang) or "Sans titre", "description": _pick(a.get("description"), lang),
        "cover_url": f"{UPLOADS}/covers/{item['id']}/{file_name}.512.jpg" if file_name else None,
        "status": status if status in ("ongoing", "completed", "paused") else "ongoing",
        "year": a.get("year"), "rating": a.get("contentRating"), "original_language": a.get("originalLanguage"),
        "genres": genres[:6], "type_guess": guess,
    }


def search(query, lang="fr", adult=False, offset=0, limit=20):
    params = [("limit", limit), ("offset", offset), ("includes[]", "cover_art"), ("hasAvailableChapters", "true"),
              ("availableTranslatedLanguage[]", lang)]
    params += [("contentRating[]", r) for r in (ADULT_RATINGS if adult else SAFE_RATINGS)]
    if query:
        params += [("title", query), ("order[relevance]", "desc")]
    else:
        params += [("order[followedCount]", "desc")]
    data = _get("/manga", params)
    return [parse_manga(i, lang) for i in data.get("data", [])], data.get("total", 0)


def get_manga(manga_id, lang="fr"):
    if not UUID_RE.match(manga_id or ""):
        raise MangaDexError("Identifiant MangaDex invalide.")
    data = _get(f"/manga/{manga_id}", [("includes[]", "cover_art")])
    return parse_manga(data["data"], lang)


# ------------------------------------------------------------------ chapters
def chapter_feed(manga_id, lang):
    """Readable chapters in `lang`, oldest first. Chapters that only link to an external site (no pages) are skipped."""
    out, offset = [], 0
    while offset < 3000:
        params = [("limit", 500), ("offset", offset), ("translatedLanguage[]", lang), ("order[chapter]", "asc"),
                  ("includeExternalUrl", 0), ("includes[]", "scanlation_group")]
        params += [("contentRating[]", r) for r in SAFE_RATINGS + ADULT_RATINGS]
        data = _get(f"/manga/{manga_id}/feed", params)
        for item in data.get("data", []):
            a = item.get("attributes", {})
            if a.get("externalUrl") or not a.get("pages"):
                continue
            group = next((r for r in item.get("relationships", []) if r.get("type") == "scanlation_group"), None)
            out.append({"id": item["id"], "chapter": a.get("chapter"), "title": a.get("title"), "pages": int(a["pages"]),
                        "publish_at": a.get("publishAt"),
                        "group": ((group or {}).get("attributes") or {}).get("name")})
        offset += 500
        if offset >= data.get("total", 0):
            break
        time.sleep(0.25)       # stay far below MangaDex's 5 requests / second
    return out


_AT_HOME = {}      # chapter uuid -> (expires_at, payload): the at-home endpoint is limited to 40 calls / minute


def at_home(chapter_uuid):
    now = time.time()
    hit = _AT_HOME.get(chapter_uuid)
    if hit and hit[0] > now:
        return hit[1]
    data = _get(f"/at-home/server/{chapter_uuid}")
    ch = data.get("chapter") or {}
    payload = {"base": data.get("baseUrl"), "hash": ch.get("hash"), "data": ch.get("data") or [], "saver": ch.get("dataSaver") or []}
    if not (payload["base"] and payload["hash"]):
        raise MangaDexError("Chapitre indisponible chez MangaDex.")
    if len(_AT_HOME) > 300:
        _AT_HOME.clear()
    _AT_HOME[chapter_uuid] = (now + 8 * 60, payload)
    return payload


def page_image(chapter_uuid, index):
    """Bytes of page `index` (data-saver quality when available: lighter for this server and for the reader)."""
    info = at_home(chapter_uuid)
    files, quality = (info["saver"], "data-saver") if info["saver"] else (info["data"], "data")
    if not 0 <= index < len(files):
        raise MangaDexError("Page introuvable.")
    return fetch_bytes(f"{info['base']}/{quality}/{info['hash']}/{parse.quote(files[index])}")


# ------------------------------------------------------------------ signed page URLs (the proxy is public: <img> sends no token)
def _sig(chapter_id, index, exp):
    key = Config.SECRET_KEY.encode()
    return hmac.new(key, f"mdx:{chapter_id}:{index}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def verify(chapter_id, index, exp, sig):
    try:
        return int(exp) > time.time() and hmac.compare_digest(_sig(chapter_id, index, int(exp)), str(sig))
    except (TypeError, ValueError):
        return False


def signed_page_urls(chapter, base):
    """Public proxy URLs for an imported chapter, valid 6 hours. Only called by endpoints that already applied the
    visibility and 18+ rules."""
    exp = int(time.time()) + 6 * 3600
    return [f"{base}/api/mangadex/page/{chapter.id}/{i}.jpg?e={exp}&s={_sig(chapter.id, i, exp)}"
            for i in range(len(chapter.pages or []))]
