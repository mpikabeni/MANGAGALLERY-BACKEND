"""Announce a NEW TITLE to the users: an in-app notification + a message from the bot (with the cover and a Read button).

A title is announced once (Manga.announced_at), at the moment it is public AND has at least one published chapter, whether it
was imported or published by hand. Titles of La Sainte Culture (18+) are only announced to users who confirmed they are adults."""
import html
import logging
import threading
import time
from datetime import datetime

from flask import current_app

from config import Config
from database import db
from models.chapter import Chapter
from models.manga import SECTION_ADULT, Manga
from models.notification import Notification
from models.user import User

log = logging.getLogger("mgfr.announce")
TYPE_LABELS = {"manga": "Manga", "webtoon": "Webtoon", "comic": "Bande dessinée"}


def _num(n):
    return str(int(n)) if n == int(n) else str(n)


def chapter_stats(manga_id):
    """(count, first, last) over the chapters readers can see."""
    n, lo, hi = db.session.query(db.func.count(Chapter.id), db.func.min(Chapter.number), db.func.max(Chapter.number)) \
        .filter(Chapter.manga_id == manga_id, Chapter.status == "published", Chapter.visibility == "public").one()
    return n or 0, lo, hi


def maybe_announce(manga):
    """Call after chapters were saved. Returns True when an announcement was started."""
    if manga.announced_at or manga.visibility != "public":
        return False
    if chapter_stats(manga.id)[0] == 0:
        return False
    manga.announced_at = datetime.utcnow()           # set BEFORE sending: no duplicate even if two requests race
    db.session.commit()
    app = current_app._get_current_object()
    threading.Thread(target=_announce, args=(app, manga.id), name="announce", daemon=True).start()
    return True


def _recipients(adult):
    q = User.query.filter(User.status == "active")
    if adult:
        cond = User.adult_confirmed_at.isnot(None)
        if Config.ADMIN_TELEGRAM_ID:
            cond = db.or_(cond, User.telegram_id == Config.ADMIN_TELEGRAM_ID)
        q = q.filter(cond)
    return q.with_entities(User.id, User.telegram_id).all()


def _announce(app, manga_id):
    with app.app_context():
        try:
            manga = Manga.query.get(manga_id)
            if not manga:
                return
            adult = manga.section == SECTION_ADULT
            count, first, last = chapter_stats(manga.id)
            kind = TYPE_LABELS.get(manga.content_type, "Manga")
            span = f"chapitres {_num(first)} à {_num(last)} ({count})" if count > 1 else f"chapitre {_num(first)}"
            title = f"🆕 Nouveau : {manga.title}"[:200]
            message = f"{'🔞 La Sainte Culture · ' if adult else ''}{kind} · {span}. À lire maintenant !"
            users = _recipients(adult)
            db.session.bulk_save_objects([Notification(user_id=uid, title=title, message=message, type="manga",
                                                       data={"manga_id": manga.id, "section": manga.section}) for uid, _ in users])
            db.session.commit()
            sent = _telegram_broadcast(manga, kind, span, adult, [tid for _, tid in users if tid])
            log.warning("Announced '%s': %s notifications, %s bot messages", manga.title, len(users), sent)
        except Exception:
            db.session.rollback()
            log.exception("Announcement failed")
        finally:
            db.session.remove()


def _telegram_broadcast(manga, kind, span, adult, chat_ids):
    if not (Config.TELEGRAM_BOT_TOKEN and chat_ids):
        return 0
    from services.telegram_service import TelegramError, tg_call
    app_url = Config.TELEGRAM_MINI_APP_URL.rstrip("/")
    markup = {"inline_keyboard": [[{"text": "📖 Lire maintenant", "web_app": {"url": f"{app_url}/?m={manga.id}"}}]]} \
        if app_url.startswith("https://") else None
    synopsis = (manga.description or "").split("\n\nGenres")[0].strip()
    if len(synopsis) > 280:
        synopsis = synopsis[:277].rsplit(" ", 1)[0] + "…"
    caption = (f"<b>🆕 Nouveau sur {html.escape(Config.APP_NAME)}</b>\n\n<b>{html.escape(manga.title)}</b>\n"
               f"{'🔞 La Sainte Culture · ' if adult else ''}{kind} · {span}"
               + (f"\n\n{html.escape(synopsis)}" if synopsis else ""))[:1020]
    photo = manga.cover_url if (manga.cover_url or "").startswith("https://") else None
    sent = 0
    for chat_id in chat_ids:
        payload = {"chat_id": chat_id, "parse_mode": "HTML", "reply_markup": markup} if markup else {"chat_id": chat_id, "parse_mode": "HTML"}
        try:
            if photo:
                try:
                    tg_call("sendPhoto", {**payload, "photo": photo, "caption": caption})
                except TelegramError:
                    tg_call("sendMessage", {**payload, "text": caption, "disable_web_page_preview": True})
            else:
                tg_call("sendMessage", {**payload, "text": caption, "disable_web_page_preview": True})
            sent += 1
        except TelegramError:
            pass                                      # user never started the bot or blocked it
        time.sleep(0.06)                              # stay far below Telegram's ~30 messages / second
    return sent
