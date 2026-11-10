#!/usr/bin/env python3
"""Nexa Manga - Telegram bot runner.

Before the mini app is shown, the bot checks that the user joined the Nexa channel
(@Nexa_CG). The mini app backend enforces the same rule, so opening the app URL directly
does not bypass it.

Usage
    python bot.py              long polling (local development / a separate worker)
    python bot.py --webhook    register the webhook on PUBLIC_BACKEND_URL (production, Render)
    python bot.py --setup      set bot commands + the menu button, then exit
    python bot.py --info       print the bot and channel status, then exit

IMPORTANT: add the bot as an ADMINISTRATOR of the channel, otherwise Telegram does not let
it read the member list and nobody can pass the gate.
"""
import argparse
import logging
import sys
import time

from config import Config
from services.telegram_service import (TelegramError, channel_username, handle_update, tg_call)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nexa.bot")


def check_channel():
    me = tg_call("getMe")
    log.info("Bot: @%s", me.get("username"))
    try:
        chat = tg_call("getChat", {"chat_id": channel_username()})
        member = tg_call("getChatMember", {"chat_id": channel_username(), "user_id": me["id"]})
        log.info("Channel: %s (%s) - bot status: %s", chat.get("title"), channel_username(), member.get("status"))
        if member.get("status") != "administrator":
            log.warning("The bot is NOT an administrator of %s: membership checks will fail.", channel_username())
    except TelegramError as exc:
        log.error("Cannot read %s: %s. Add the bot as administrator of the channel.", channel_username(), exc)


def setup():
    tg_call("setMyCommands", {"commands": [
        {"command": "start", "description": "Open Nexa Manga"},
        {"command": "help", "description": "Help"},
        {"command": "version", "description": "Version"}]})
    tg_call("setMyCommands", {"language_code": "fr", "commands": [
        {"command": "start", "description": "Ouvrir Nexa Manga"},
        {"command": "help", "description": "Aide"},
        {"command": "version", "description": "Version"}]})
    if Config.TELEGRAM_MINI_APP_URL.startswith("https://"):
        tg_call("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "Nexa Manga",
                                                       "web_app": {"url": Config.TELEGRAM_MINI_APP_URL}}})
    log.info("Commands and menu button configured.")


def set_webhook():
    if not (Config.PUBLIC_BACKEND_URL and Config.TELEGRAM_WEBHOOK_SECRET):
        sys.exit("PUBLIC_BACKEND_URL et TELEGRAM_WEBHOOK_SECRET sont requis pour le webhook.")
    url = Config.PUBLIC_BACKEND_URL.rstrip("/") + "/api/telegram/webhook"
    tg_call("setWebhook", {"url": url, "secret_token": Config.TELEGRAM_WEBHOOK_SECRET,
                           "allowed_updates": ["message", "callback_query"],
                           "drop_pending_updates": False})
    log.info("Webhook set: %s", url)


def poll():
    tg_call("deleteWebhook", {"drop_pending_updates": False})  # polling and webhook are exclusive
    log.info("Nexa bot started (long polling). Ctrl+C to stop.")
    offset = None
    while True:
        try:
            updates = tg_call("getUpdates", {"timeout": 30, "offset": offset,
                                             "allowed_updates": ["message", "callback_query"]}, timeout=45)
        except TelegramError as exc:
            log.warning("getUpdates failed: %s", exc)
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                handle_update(upd)
            except Exception:
                log.exception("update %s failed", upd.get("update_id"))


def main():
    parser = argparse.ArgumentParser(description="Nexa Manga bot")
    parser.add_argument("--webhook", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--info", action="store_true")
    args = parser.parse_args()

    if not Config.TELEGRAM_BOT_TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN manquant (variable d'environnement).")
    if args.info:
        check_channel()
    elif args.setup:
        setup()
    elif args.webhook:
        set_webhook()
        check_channel()
    else:
        check_channel()
        try:
            poll()
        except KeyboardInterrupt:
            log.info("Stopped.")


if __name__ == "__main__":
    main()
