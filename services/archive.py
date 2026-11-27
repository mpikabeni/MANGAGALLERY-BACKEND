"""Internet Archive (archive.org): BD / comics WITH their pages, from the official public API (no key).

  search   https://archive.org/advancedsearch.php      (collection "comics", with a Creative Commons / public domain licence)
  item     https://archive.org/metadata/<identifier>   (files + licence)
  file     https://archive.org/download/<identifier>/<file>   (CBZ or PDF, converted by the normal chapter pipeline)

Only items with an EXPLICIT free licence are offered: public domain / CC0, CC BY, CC BY-SA. Everything else on archive.org (including many
comics uploaded by their authors, "all rights reserved") is refused: "available to read" does not mean "allowed to republish".
NC (non commercial) and ND (no derivatives) licences are refused too, because the pages are resized and converted.
"""
import json
import re
from urllib import error, parse, request

USER_AGENT = "MangaGalleryFR/1.0 (Telegram mini app; free-licensed comics only)"
SEARCH = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
IMG = "https://archive.org/services/img/"
HOST = "archive.org"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")          # our external_id column holds 64 characters
LANG_QUERY = {"fr": "language:(french OR fre OR fra OR fr)", "en": "language:(english OR eng OR en)"}


class ArchiveError(Exception):
    """Message meant for the administrator (French)."""


def licence(url):
    """-> 'CC BY 4.0' style label for an accepted free licence, else None."""
    u = (url or "").lower()
    ver = re.search(r"/(\d\.\d)/?", u)
    ver = f" {ver.group(1)}" if ver else ""
    if "creativecommons.org/publicdomain/zero" in u:
        return "CC0 (domaine public)"
    if "creativecommons.org/publicdomain/" in u:
        return "Domaine public"
    if "creativecommons.org/licenses/by-sa/" in u:
        return "CC BY-SA" + ver
    if "creativecommons.org/licenses/by/" in u:
        return "CC BY" + ver
    return None


def _get(url, timeout=25):
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise ArchiveError("Internet Archive a refusé la demande." if exc.code != 429 else "Internet Archive limite les requêtes : réessaie dans une minute.")
    except (error.URLError, TimeoutError, OSError):
        raise ArchiveError("Internet Archive est injoignable pour le moment.")
    except ValueError:
        raise ArchiveError("Réponse illisible d'Internet Archive.")


def _first(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _words(query):
    return [w for w in re.sub(r'[+\-&|!(){}\[\]^"~*?:\\/]', " ", query or "").split() if w][:6]


def search(query, lang, offset, per_page):
    """-> (docs, has_more). Only comics with a free licence (the licence is checked again, exactly, on the results)."""
    q = "collection:comics AND mediatype:texts AND licenseurl:(*creativecommons.org*)"
    words = _words(query)
    if words:
        joined = " AND ".join(words)
        q += f" AND (title:({joined}) OR creator:({joined}) OR subject:({joined}))"
    if lang in LANG_QUERY:
        q += " AND " + LANG_QUERY[lang]
    params = [("q", q), ("rows", per_page), ("page", offset // per_page + 1), ("output", "json"), ("sort[]", "downloads desc")]
    params += [("fl[]", f) for f in ("identifier", "title", "description", "creator", "date", "licenseurl", "language")]
    data = _get(SEARCH + "?" + parse.urlencode(params))
    res = data.get("response") or {}
    docs = []
    for d in res.get("docs") or []:
        label = licence(_first(d.get("licenseurl")))
        ident = d.get("identifier") or ""
        if label and ID_RE.match(ident):
            docs.append({**d, "_licence": label})
    return docs, (res.get("start", 0) + per_page) < (res.get("numFound") or 0)


def metadata(identifier):
    if not ID_RE.match(identifier or ""):
        raise ArchiveError("Identifiant invalide.")
    data = _get(META + parse.quote(identifier))
    if not data.get("metadata"):
        raise ArchiveError("Livre introuvable sur Internet Archive.")
    label = licence(_first(data["metadata"].get("licenseurl")))
    if not label:
        raise ArchiveError("Ce livre n'a pas de licence libre explicite (domaine public, CC0, CC BY ou CC BY-SA) : import refusé.")
    data["_licence"] = label
    return data


def pick_file(meta, max_bytes):
    """-> (file name, size) of the best readable file: CBZ first, then the original PDF. CBR (RAR) is not supported."""
    files = meta.get("files") or []
    def size(f):
        return int(f.get("size") or 0) if str(f.get("size") or "0").isdigit() else 0
    cbz = [f for f in files if (f.get("name") or "").lower().endswith(".cbz")]
    pdf = [f for f in files if (f.get("name") or "").lower().endswith(".pdf") and not (f.get("name") or "").lower().endswith("_text.pdf")]
    pdf.sort(key=lambda f: (f.get("source") != "original", -size(f)))
    for f in cbz + pdf:
        if 0 < size(f) <= max_bytes:
            return f["name"], size(f)
    if cbz or pdf:
        raise ArchiveError(f"Le fichier de ce livre dépasse {max_bytes // (1024 * 1024)} Mo : import impossible ici.")
    raise ArchiveError("Aucun fichier CBZ ou PDF lisible dans ce livre (les formats CBR / EPUB ne sont pas pris en charge).")


class _SameSite(request.HTTPRedirectHandler):
    """archive.org redirects downloads to its storage servers: follow only redirects that stay on archive.org."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (parse.urlsplit(newurl).hostname or "").lower()
        if parse.urlsplit(newurl).scheme != "https" or not (host == HOST or host.endswith("." + HOST)):
            raise ArchiveError("Redirection refusée (hors d'archive.org).")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_url(identifier, name):
    return f"https://{HOST}/download/{parse.quote(identifier)}/{parse.quote(name)}"


def download(identifier, name, dest, max_bytes, on_tick=None):
    """Streams the file to `dest` (never more than `max_bytes`). `on_tick` is called every few seconds (job heartbeat)."""
    import time
    opener = request.build_opener(_SameSite)
    req = request.Request(download_url(identifier, name), headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(req, timeout=40) as resp, open(dest, "wb") as out:
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared and declared > max_bytes:
                raise ArchiveError(f"Fichier trop lourd (plus de {max_bytes // (1024 * 1024)} Mo).")
            total, last = 0, time.monotonic()
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ArchiveError(f"Fichier trop lourd (plus de {max_bytes // (1024 * 1024)} Mo).")
                out.write(chunk)
                if on_tick and time.monotonic() - last > 4:
                    on_tick()
                    last = time.monotonic()
    except error.HTTPError:
        raise ArchiveError("Téléchargement refusé par Internet Archive (fichier restreint ou introuvable).")
    except (error.URLError, TimeoutError, OSError):
        raise ArchiveError("Téléchargement interrompu (Internet Archive ne répond pas). Réessaie.")
