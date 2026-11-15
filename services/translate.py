"""Free machine translation (MyMemory, no key) used ONLY when MangaDex has no French synopsis.

Limits (MyMemory): 500 bytes per request, 5 000 characters / day per IP, 50 000 with a contact e-mail (MYMEMORY_EMAIL).
Any failure returns None and the caller keeps the original text."""
import json
import re
from urllib import error, parse, request

from config import Config

URL = "https://api.mymemory.translated.net/get"
UA = "MangaGalleryFR/1.0 (synopsis translation)"


def _chunks(text, limit=420):
    """Split on sentences, then on words, keeping every piece under `limit` bytes."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        words = sentence.split(" ")
        for word in words:
            candidate = (current + " " + word).strip()
            if len(candidate.encode("utf-8")) > limit and current:
                pieces.append(current)
                current = word
            else:
                current = candidate
        if len(current.encode("utf-8")) > limit * 0.8:        # keep pieces short enough to translate well
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    return pieces


def translate(text, source="en", target="fr", max_chars=1600):
    text = re.sub(r"\s+", " ", (text or "")).strip()[:max_chars]
    if not text:
        return None
    out = []
    for chunk in _chunks(text):
        params = {"q": chunk, "langpair": f"{source}|{target}"}
        if Config.MYMEMORY_EMAIL:
            params["de"] = Config.MYMEMORY_EMAIL
        req = request.Request(URL + "?" + parse.urlencode(params), headers={"User-Agent": UA})
        try:
            with request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError, ValueError):
            return None
        piece = (data.get("responseData") or {}).get("translatedText") or ""
        upper = piece.upper()
        if str(data.get("responseStatus")) != "200" or not piece or "MYMEMORY WARNING" in upper or "LIMIT" in upper[:60]:
            return None
        out.append(piece)
    return " ".join(out)
