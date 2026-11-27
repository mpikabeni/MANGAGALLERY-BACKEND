"""Catalogue clients (metadata only): AniList, Jikan (MyAnimeList), Kitsu and MangaUpdates.

Together with MangaDex (services/mangadex.py, the only source that also serves readable chapters) these are the 5 sources of the
admin "Importer" page. Each client answers the SAME normalised shape, so the admin page and the import route do not care which
site a title comes from:

    {id, source, title, description, cover_url, status, year, rating, genres, type_guess, chapters_declared, url}

`rating` is "adult" or "safe". Titles of La Sainte Culture (18+) come from the adult search only, normal titles from the safe one.
Lolicon / shotacon material is refused everywhere (see `_blocked`).

These sources give NO chapters: an imported title is a fiche (cover, synopsis, genres) to which the admin then adds chapters
(PDF / CBZ upload) or which stays in "Bientôt". Credits (site name + link) are stored in SOURCES and shown with the title.
"""
import json
import re
import time
from urllib import error, parse, request

from config import Config
from services import archive

USER_AGENT = "MangaGalleryFR/1.0 (Telegram mini app; non-commercial; credits the metadata sources)"
PER_PAGE = 20


class CatalogError(Exception):
    """Message meant for the administrator (French)."""


# name, label, site, link template for the credit, whether it also serves chapters
SOURCES = {
    "mangadex": {"label": "MangaDex", "site": "https://mangadex.org", "title_url": "https://mangadex.org/title/{id}", "chapters": True},
    "anilist": {"label": "AniList", "site": "https://anilist.co", "title_url": "https://anilist.co/manga/{id}", "chapters": False},
    "jikan": {"label": "MyAnimeList (Jikan)", "site": "https://myanimelist.net", "title_url": "https://myanimelist.net/manga/{id}", "chapters": False},
    "kitsu": {"label": "Kitsu", "site": "https://kitsu.app", "title_url": "https://kitsu.app/manga/{id}", "chapters": False},
    "mangaupdates": {"label": "MangaUpdates", "site": "https://www.mangaupdates.com", "title_url": "https://www.mangaupdates.com/series/{id}", "chapters": False},
    "internetarchive": {"label": "Internet Archive (BD libres)", "site": "https://archive.org", "title_url": "https://archive.org/details/{id}", "chapters": True},
    "googlebooks": {"label": "Google Books (BD)", "site": "https://books.google.com", "title_url": "https://books.google.com/books?id={id}", "chapters": False},
}
# Only these hosts may be downloaded as a cover (the cover URL comes from a third-party API: never fetch an arbitrary address).
COVER_HOSTS = ("anilist.co", "myanimelist.net", "kitsu.io", "kitsu.app", "mangaupdates.com", "books.google.com", "googleusercontent.com", "archive.org")
FORMATS = {"", "manhwa", "manhua", "manga"}       # origin filter: Korean / Chinese / Japanese
_BLOCKED = ("lolicon", "shotacon", "loli", "shota")


def source_url(source, external_id):
    tpl = (SOURCES.get(source) or {}).get("title_url")
    return tpl.format(id=external_id) if tpl and external_id else None


def cover_allowed(url):
    try:
        parts = parse.urlsplit(url or "")
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in COVER_HOSTS)


# ------------------------------------------------------------------ http
def _call(url, body=None, headers=None, timeout=20):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = request.Request(url, data=data, headers=hdrs, method="POST" if body is not None else "GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code == 429:
            raise CatalogError("Ce site limite le nombre de requêtes : patiente une minute puis réessaie.")
        if exc.code == 400:
            raise CatalogError("Ce site a refusé la recherche (400). Essaie un autre titre ou un autre filtre.")
        raise CatalogError(f"Ce site a répondu avec une erreur ({exc.code}).")
    except (error.URLError, TimeoutError, OSError):
        raise CatalogError("Ce site est injoignable pour le moment. Réessaie dans un instant.")
    except ValueError:
        raise CatalogError("Réponse illisible de ce site.")


# ------------------------------------------------------------------ helpers
def _text(value, limit=4800):
    """Plain text: tags and BBCode removed, <br> kept as line breaks."""
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    value = re.sub(r"<[^>]+>|\[/?[a-z]+(?:=[^\]]*)?\]", "", value, flags=re.I)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value[:limit]


def _blocked(names):
    return any(any(bad in (n or "").lower() for bad in _BLOCKED) for n in names)


def _guess(origin):
    return "comic" if origin == "comic" else "webtoon" if origin in ("manhwa", "manhua") else "manga"


def _item(source, ident, title, description, cover, status, year, adult, genres, origin, chapters=None, language="en", extra=""):
    return {"id": str(ident), "source": source, "title": (title or "").strip() or "Sans titre", "description": _text(description),
            "cover_url": cover or None, "status": status, "year": year, "rating": "adult" if adult else "safe",
            "genres": [g for g in genres if g][:6], "type_guess": _guess(origin), "chapters_declared": chapters,
            "language": language, "extra": extra, "url": source_url(source, ident)}


def _keep(items, adult):
    return [i for i in items if (i["rating"] == "adult") == bool(adult) and not _blocked(i["genres"])]


def _page(offset):
    return max(0, offset) // PER_PAGE + 1


# ------------------------------------------------------------------ AniList (GraphQL)
_ANILIST = """
query ($search: String, $page: Int, $per: Int, $adult: Boolean, $country: CountryCode, $sort: [MediaSort]) {
  Page(page: $page, perPage: $per) {
    pageInfo { total hasNextPage }
    media(search: $search, type: MANGA, format_in: [MANGA, ONE_SHOT], isAdult: $adult, countryOfOrigin: $country, sort: $sort) {
      id title { romaji english } description(asHtml: false) coverImage { extraLarge large } status chapters
      startDate { year } genres isAdult countryOfOrigin tags { name }
    }
  }
}"""
_ANILIST_STATUS = {"FINISHED": "completed", "CANCELLED": "completed", "HIATUS": "paused"}
_ANILIST_COUNTRY = {"manhwa": "KR", "manhua": "CN", "manga": "JP"}


_ANILIST_ONE = """
query ($id: Int) {
  Media(id: $id, type: MANGA) {
    id title { romaji english } description(asHtml: false) coverImage { extraLarge large } status chapters
    startDate { year } genres isAdult countryOfOrigin tags { name }
  }
}"""


def _anilist_item(m):
    t = m.get("title") or {}
    origin = {"KR": "manhwa", "CN": "manhua"}.get(m.get("countryOfOrigin"), "manga")
    img = m.get("coverImage") or {}
    if _blocked([x.get("name") for x in m.get("tags") or []]):
        return None
    return _item("anilist", m["id"], t.get("english") or t.get("romaji"), m.get("description"), img.get("extraLarge") or img.get("large"),
                 _ANILIST_STATUS.get(m.get("status"), "ongoing"), (m.get("startDate") or {}).get("year"), m.get("isAdult"),
                 m.get("genres") or [], origin, m.get("chapters"))


def anilist(query, adult, fmt, offset):
    variables = {"search": query or None, "page": _page(offset), "per": PER_PAGE, "adult": bool(adult),
                 "country": _ANILIST_COUNTRY.get(fmt), "sort": ["SEARCH_MATCH"] if query else ["POPULARITY_DESC"]}
    data = _call("https://graphql.anilist.co", {"query": _ANILIST, "variables": variables})
    if data.get("errors"):
        raise CatalogError("AniList a refusé la recherche.")
    page = (data.get("data") or {}).get("Page") or {}
    out = [i for i in map(_anilist_item, page.get("media") or []) if i]
    return {"items": _keep(out, adult), "next": offset + PER_PAGE, "has_more": bool((page.get("pageInfo") or {}).get("hasNextPage"))}


def _anilist_one(ident):
    data = _call("https://graphql.anilist.co", {"query": _ANILIST_ONE, "variables": {"id": int(ident)}})
    media = (data.get("data") or {}).get("Media")
    return _anilist_item(media) if media else None


# ------------------------------------------------------------------ Jikan (MyAnimeList, REST v4)
_JIKAN_STATUS = {"Finished": "completed", "On Hiatus": "paused", "Discontinued": "completed"}
_JIKAN_ADULT_GENRES = (12, 49)      # Hentai, Erotica


def _jikan_query(params):
    return _call("https://api.jikan.moe/v4/manga?" + parse.urlencode(params))


def _jikan_item(r):
    listed = (r.get("genres") or []) + (r.get("explicit_genres") or [])
    genres = [g.get("name") for g in listed + (r.get("themes") or [])]
    adult_title = any(g.get("mal_id") in _JIKAN_ADULT_GENRES for g in listed)
    origin = (r.get("type") or "Manga").lower()
    imgs = (r.get("images") or {}).get("jpg") or {}
    year = ((((r.get("published") or {}).get("prop") or {}).get("from")) or {}).get("year")
    return _item("jikan", r["mal_id"], r.get("title_english") or r.get("title"), r.get("synopsis"),
                 imgs.get("large_image_url") or imgs.get("image_url"), _JIKAN_STATUS.get(r.get("status"), "ongoing"),
                 year, adult_title, genres, origin, r.get("chapters"))


def jikan(query, adult, fmt, offset):
    base = {"page": _page(offset), "limit": PER_PAGE}
    if query:
        base["q"] = query
    else:
        base.update({"order_by": "members", "sort": "desc"})
    if fmt in ("manhwa", "manhua", "manga"):
        base["type"] = fmt
    rows, more = {}, False
    if adult:                                    # adult genres cannot be combined with OR: one request each, same page, merged
        for n, genre in enumerate(_JIKAN_ADULT_GENRES):
            if n:
                time.sleep(0.45)                 # Jikan: about 3 requests / second
            data = _jikan_query({**base, "genres": genre})
            more = more or bool((data.get("pagination") or {}).get("has_next_page"))
            for r in data.get("data") or []:
                rows[r["mal_id"]] = r
    else:
        data = _jikan_query({**base, "sfw": "true"})
        more = bool((data.get("pagination") or {}).get("has_next_page"))
        rows = {r["mal_id"]: r for r in data.get("data") or []}
    return {"items": _keep([_jikan_item(r) for r in rows.values()], adult), "next": offset + PER_PAGE, "has_more": more}


def _jikan_one(ident):
    row = _call(f"https://api.jikan.moe/v4/manga/{int(ident)}").get("data")
    return _jikan_item(row) if row else None


# ------------------------------------------------------------------ Kitsu (JSON:API)
_KITSU_STATUS = {"finished": "completed", "tba": "paused", "unreleased": "paused", "upcoming": "paused"}


def _kitsu_item(r):
    a = r.get("attributes") or {}
    titles = a.get("titles") or {}
    poster = a.get("posterImage") or {}
    nsfw = bool(a.get("nsfw")) or a.get("ageRating") == "R18"
    return _item("kitsu", r["id"], titles.get("en") or titles.get("en_jp") or a.get("canonicalTitle"), a.get("synopsis"),
                 poster.get("large") or poster.get("original"), _KITSU_STATUS.get(a.get("status"), "ongoing"),
                 (a.get("startDate") or "")[:4] or None, nsfw, [], a.get("subtype") or "manga", a.get("chapterCount"))


def kitsu(query, adult, fmt, offset):
    """Kitsu has no adult filter on manga: its `nsfw` flag is applied on our side, so we read up to 3 pages to fill one."""
    out, raw_offset, more = [], max(0, offset), True
    for _ in range(3):
        params = {"page[limit]": PER_PAGE, "page[offset]": raw_offset}
        if query:
            params["filter[text]"] = query
        else:
            params["sort"] = "-userCount"
        if fmt in ("manhwa", "manhua", "manga"):
            params["filter[subtype]"] = fmt
        data = _call("https://kitsu.io/api/edge/manga?" + parse.urlencode(params), headers={"Accept": "application/vnd.api+json"})
        rows = data.get("data") or []
        raw_offset += PER_PAGE
        more = bool((data.get("links") or {}).get("next")) and bool(rows)
        seen = {i["id"] for i in out}
        out += [i for i in map(_kitsu_item, rows) if i["id"] not in seen]
        kept = _keep(out, adult)
        if len(kept) >= 8 or not more:
            return {"items": kept, "next": raw_offset, "has_more": more}
    return {"items": _keep(out, adult), "next": raw_offset, "has_more": more}


def _kitsu_one(ident):
    data = _call(f"https://kitsu.io/api/edge/manga/{int(ident)}", headers={"Accept": "application/vnd.api+json"})
    return _kitsu_item(data["data"]) if data.get("data") else None


# ------------------------------------------------------------------ MangaUpdates (REST v1)
_MU_TYPE = {"manhwa": ["Manhwa"], "manhua": ["Manhua"], "manga": ["Manga"]}
_MU_ADULT = ["Adult", "Hentai", "Smut"]
_MU_BANNED = ["Lolicon", "Shotacon"]


def _mu_status(text):
    low = (text or "").lower()
    return "completed" if "complete" in low else "paused" if "hiatus" in low else "ongoing"


def _mu_item(r):
    genres = [g.get("genre") for g in r.get("genres") or []]
    year = str(r.get("year") or "")[:4]
    cover = (((r.get("image") or {}).get("url")) or {}).get("original")
    return _item("mangaupdates", r.get("series_id"), r.get("title"), r.get("description"), cover, _mu_status(r.get("status")),
                 int(year) if year.isdigit() else None, any(g in _MU_ADULT for g in genres), genres, (r.get("type") or "manga").lower())


def mangaupdates(query, adult, fmt, offset):
    body = {"page": _page(offset), "perpage": PER_PAGE, "exclude_genre": list(_MU_BANNED) if adult else _MU_ADULT + _MU_BANNED}
    if query:
        body["search"] = query
    if adult:
        body["genre"] = ["Adult"]
    if fmt in _MU_TYPE:
        body["type"] = _MU_TYPE[fmt]
    url = "https://api.mangaupdates.com/v1/series/search"
    try:
        data = _call(url, body if query else {**body, "orderby": "rating"})
    except CatalogError:
        if query:
            raise
        data = _call(url, body)                  # the sort key was refused: plain list
    out = [_mu_item(hit.get("record") or {}) for hit in data.get("results") or []]
    return {"items": _keep(out, adult), "next": offset + PER_PAGE, "has_more": body["page"] * PER_PAGE < (data.get("total_hits") or 0)}


def _mu_one(ident):
    row = _call(f"https://api.mangaupdates.com/v1/series/{int(ident)}")
    return _mu_item(row) if row.get("series_id") else None


# ------------------------------------------------------------------ Google Books (BD / comics, REST v1)
_GB = "https://www.googleapis.com/books/v1/volumes"
_GB_COVERS = ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail")


def _gb_cover(links):
    for key in _GB_COVERS:
        url = (links or {}).get(key)
        if url:
            return re.sub(r"&edge=curl", "", url.replace("http://", "https://"))
    return None


def _gb_item(v):
    info = v.get("volumeInfo") or {}
    cats = info.get("categories") or []
    if not any("comic" in c.lower() or "graphic" in c.lower() for c in cats):
        return None                                                   # not a BD (the query already asks for comics: this removes the rest)
    extra = " · ".join(x for x in [("Auteur(s) : " + ", ".join(info["authors"][:3])) if info.get("authors") else "",
                                   ("Éditeur : " + info["publisher"]) if info.get("publisher") else ""] if x)
    year = str(info.get("publishedDate") or "")[:4]
    title = info.get("title") or ""
    if info.get("subtitle"):
        title = f"{title} - {info['subtitle']}"
    return _item("googlebooks", v["id"], title, info.get("description"), _gb_cover(info.get("imageLinks")), "completed",
                 int(year) if year.isdigit() else None, info.get("maturityRating") == "MATURE", [], "comic",
                 info.get("pageCount") or None, language=info.get("language") or "en", extra=extra)


def _gb_params(extra):
    return parse.urlencode({**extra, **({"key": Config.GOOGLE_BOOKS_KEY} if Config.GOOGLE_BOOKS_KEY else {})})


def googlebooks(query, adult, fmt, offset, lang="fr"):
    """Bandes dessinées. `lang`: fr | en | '' (all languages). The adult section keeps only volumes Google marks MATURE."""
    q = (query + " " if query else "") + "subject:comics"
    params = {"q": q, "maxResults": PER_PAGE, "startIndex": offset, "printType": "books", "orderBy": "relevance"}
    if lang in ("fr", "en"):
        params["langRestrict"] = lang
    data = _call(_GB + "?" + _gb_params(params))
    out = [i for i in map(_gb_item, data.get("items") or []) if i]
    return {"items": _keep(out, adult), "next": offset + PER_PAGE, "has_more": offset + PER_PAGE < (data.get("totalItems") or 0) and bool(data.get("items"))}


def _gb_one(ident):
    return _gb_item(_call(f"{_GB}/{parse.quote(ident)}" + ("?" + _gb_params({}) if Config.GOOGLE_BOOKS_KEY else "")))


# ------------------------------------------------------------------ Internet Archive (BD / comics with their pages, free licences only)
def _ia_lang(value):
    v = str(value[0] if isinstance(value, list) and value else value or "").lower()
    return "fr" if v.startswith("fr") else "en" if v in ("en", "eng", "english") else None


def _ia_item(d):
    ident = d["identifier"]
    creators = d.get("creator") if isinstance(d.get("creator"), list) else [d.get("creator")] if d.get("creator") else []
    desc = d.get("description")
    desc = "\n".join(desc) if isinstance(desc, list) else desc
    year = archive._first(d.get("date"))[:4]
    extra = " · ".join(x for x in [("Auteur(s) : " + ", ".join(str(c) for c in creators[:3])) if creators else "",
                                   "Licence : " + d["_licence"]] if x)
    item = _item("internetarchive", ident, archive._first(d.get("title")) or ident, desc, archive.IMG + ident, "completed",
                 int(year) if year.isdigit() else None, False, [], "comic", None, language=_ia_lang(d.get("language")), extra=extra)
    item["readable"] = True                      # the pages come with the title: the admin imports the title AND its chapter in one click
    item["licence"] = d["_licence"]
    return item


def internetarchive(query, adult, fmt, offset, lang="fr"):
    """Free-licensed comics only (see services/archive.py). Nothing here is rated adult: the adult section stays empty."""
    if adult:
        return {"items": [], "next": offset, "has_more": False}
    try:
        docs, more = archive.search(query, lang, offset, PER_PAGE)
    except archive.ArchiveError as exc:
        raise CatalogError(str(exc))
    return {"items": [_ia_item(d) for d in docs], "next": offset + PER_PAGE, "has_more": more}


def _ia_one(ident):
    try:
        meta = archive.metadata(ident)
    except archive.ArchiveError as exc:
        raise CatalogError(str(exc))
    return _ia_item({**meta["metadata"], "identifier": ident, "_licence": meta["_licence"]})


CLIENTS = {"anilist": anilist, "jikan": jikan, "kitsu": kitsu, "mangaupdates": mangaupdates, "googlebooks": googlebooks, "internetarchive": internetarchive}
_ONE = {"anilist": _anilist_one, "jikan": _jikan_one, "kitsu": _kitsu_one, "mangaupdates": _mu_one, "googlebooks": _gb_one, "internetarchive": _ia_one}


def search(source, query, adult=False, fmt="", offset=0, lang="fr"):
    if source not in CLIENTS:
        raise CatalogError("Source inconnue.")
    if source in ("googlebooks", "internetarchive"):
        return CLIENTS[source](query, adult, "", max(0, offset), lang if lang in ("fr", "en", "all") else "fr")
    return CLIENTS[source](query, adult, fmt if fmt in FORMATS else "", max(0, offset))


def get_one(source, ident):
    """One title by id, re-read from the site at import time (the browser only sends the id, never the data)."""
    pattern = {"googlebooks": r"[A-Za-z0-9_-]{6,24}", "internetarchive": archive.ID_RE.pattern}.get(source, r"[0-9]{1,12}")      # these ids are not numbers
    if source not in _ONE or not re.fullmatch(pattern, str(ident or "")):
        raise CatalogError("Identifiant invalide.")
    item = _ONE[source](ident)
    if not item:
        raise CatalogError("Titre introuvable ou refusé (contenu non autorisé).")
    return item
