"""Synopses are ALWAYS shown in French: `to_french(text, source)` returns the text unchanged when it already is French, otherwise
machine-translates it.

Providers, tried in this order:
  1. DeepL API (best quality) - set DEEPL_API_KEY (the free plan gives 500 000 characters / month, a key ending with ":fx" is a free key).
  2. MyMemory (no key) - 5 000 characters / day per IP, 50 000 with MYMEMORY_EMAIL. Fine for a test, too small for a real catalogue.
Any failure returns None: the caller then keeps the original text and says it is not translated yet (the admin can translate it later).
"""
import json
import re
from urllib import error, parse, request

from config import Config

MYMEMORY_URL = "https://api.mymemory.translated.net/get"
UA = "MangaGalleryFR/1.0 (synopsis translation)"
MAX_CHARS = 4800

_FR = {"le", "les", "des", "du", "une", "et", "est", "dans", "pour", "qui", "il", "elle", "ils", "ses", "sur", "au", "aux", "avec", "pas",
       "cette", "mais", "sont", "plus", "leur", "où", "ne"}       # words that are NOT also Spanish / Italian / Portuguese
_EN = {"the", "and", "of", "to", "in", "is", "he", "she", "his", "her", "with", "for", "that", "by", "at", "an", "are", "was",
       "who", "it", "but", "this", "from", "their", "they", "when", "after", "has", "have", "been", "into", "one", "after"}
# Source languages we know how to name for the providers (MangaDex descriptions come in several languages).
LANGS = {"en": "EN", "es": "ES", "pt": "PT", "pt-br": "PT", "ja": "JA", "ko": "KO", "zh": "ZH", "de": "DE", "it": "IT", "ru": "RU"}


def looks_french(text):
    """Cheap language check: more French than English function words (and a few accented letters)."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", (text or "").lower())
    words = [w.split("'")[-1] if "'" in w else w for w in words]
    fr, en = sum(w in _FR for w in words), sum(w in _EN for w in words)
    return fr >= 3 and fr > en * 1.3


def _clip(text, limit):
    """Cut at the end of a sentence (never in the middle of one)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("… "))
    return cut[:end + 1] if end > limit * 0.5 else cut


def _http(url, body=None, headers=None, timeout=15):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    with request.urlopen(request.Request(url, data=data, headers=hdrs), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------------------------------------------ DeepL
def _deepl(text, source):
    key = Config.DEEPL_API_KEY
    if not key:
        return None
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    body = {"text": paragraphs, "target_lang": "FR", "preserve_formatting": True}
    if LANGS.get((source or "").lower()):
        body["source_lang"] = LANGS[source.lower()]
    try:
        data = _http(f"https://{host}/v2/translate", body, {"Authorization": f"DeepL-Auth-Key {key}"})
        out = [t.get("text", "") for t in data.get("translations") or []]
    except (error.URLError, TimeoutError, OSError, ValueError):
        return None
    return "\n\n".join(out) if len(out) == len(paragraphs) and all(out) else None


# ------------------------------------------------------------------ MyMemory
def _chunks(text, limit=420):
    """Split on sentences, then on words, keeping every piece under `limit` bytes."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        for word in sentence.split(" "):
            candidate = (current + " " + word).strip()
            if len(candidate.encode("utf-8")) > limit and current:
                pieces.append(current)
                current = word
            else:
                current = candidate
        if len(current.encode("utf-8")) > limit * 0.8:
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    return pieces


def _mymemory(text, source):
    text = _clip(re.sub(r"\s+", " ", text).strip(), 1600)      # the free quota is small: translate the beginning, cut on a sentence
    pair = f"{(source or 'en').lower().split('-')[0]}|fr"
    out = []
    for chunk in _chunks(text):
        params = {"q": chunk, "langpair": pair}
        if Config.MYMEMORY_EMAIL:
            params["de"] = Config.MYMEMORY_EMAIL
        try:
            data = _http(MYMEMORY_URL + "?" + parse.urlencode(params), timeout=12)
        except (error.URLError, TimeoutError, OSError, ValueError):
            return None
        piece = (data.get("responseData") or {}).get("translatedText") or ""
        upper = piece.upper()
        if str(data.get("responseStatus")) != "200" or not piece or "MYMEMORY WARNING" in upper or "LIMIT" in upper[:60]:
            return None
        out.append(piece)
    return " ".join(out) or None


# ------------------------------------------------------------------ public
def to_french(text, source=None):
    """-> (french_text, how) where how is 'already' | 'deepl' | 'mymemory', or None when no provider could translate."""
    text = (text or "").strip()
    if not text:
        return None
    src = (source or "").lower()
    if src.startswith("fr") or (not src and looks_french(text)):      # a known source language is trusted: no guessing
        return text, "already"
    text = _clip(text, MAX_CHARS)
    for name, fn in (("deepl", _deepl), ("mymemory", _mymemory)):
        result = fn(text, source)
        if result:
            return result, name
    return None


def translate(text, source="en", target="fr", max_chars=1600):
    """Backward compatible helper: the French text or None."""
    result = to_french(text, source) if target == "fr" else None
    return result[0] if result else None


NOTE = "(Synopsis traduit automatiquement.)"
