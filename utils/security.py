"""Security helpers that do not depend on Flask (easy to unit-test)."""
import hashlib
import hmac
import json
import re
import threading
import time
from collections import defaultdict, deque
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


def verify_init_data(init_data, bot_token, max_age=86400, now=None):
    """Validate Telegram WebApp initData (HMAC-SHA256, see core.telegram.org/bots/webapps).

    Returns the Telegram user dict. Raises InitDataError when the data is forged,
    malformed or too old. Never trust `initDataUnsafe` from the browser.
    """
    if not init_data or not bot_token:
        raise InitDataError("missing_init_data")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = pairs.pop("hash", None)
    if not received:
        raise InitDataError("missing_hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("bad_signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("bad_auth_date")
    if max_age and (now or time.time()) - auth_date > max_age:
        raise InitDataError("expired")

    try:
        user = json.loads(pairs.get("user", ""))
    except (ValueError, TypeError):
        raise InitDataError("bad_user")
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("bad_user")
    return user


class RateLimiter:
    """Small in-memory sliding-window limiter (per process)."""

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key, limit, window):
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 20000:  # keep memory bounded
                for k in [k for k, v in self._hits.items() if not v][:5000]:
                    self._hits.pop(k, None)
            return True


limiter = RateLimiter()

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_TAGS = re.compile(r"[<>\"'`]")


def clean_text(value, max_len=100):
    """Normalise untrusted display text (names, usernames): no markup, no control/bidi chars."""
    if value is None:
        return None
    s = _TAGS.sub("", _CTRL.sub("", str(value))).strip()
    return s[:max_len] or None


def clean_multiline(value, max_len=1000):
    s = _CTRL.sub("", str(value or "")).replace("\r\n", "\n").strip()
    return s[:max_len]


def is_safe_url(value, allow_relative=True):
    """Only http(s) (or site-relative) URLs may be stored for images."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    v = value.strip()
    if re.match(r"^https?://[^\s<>\"']+$", v, re.I):
        return True
    return allow_relative and v.startswith("/") and not v.startswith("//") and not re.search(r"[\s<>\"']", v)
