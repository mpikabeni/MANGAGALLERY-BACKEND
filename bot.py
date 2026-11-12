#!/usr/bin/env python3
"""Manga Gallery FR - Telegram bot runner.

In production (Render) you do NOT need this file: the server registers the webhook, the commands and the
menu button by itself when it starts (BOT_AUTO_SETUP). It is only useful for local development or diagnosis.

Usage
    python bot.py              long polling (local development)
    python bot.py --webhook    register the webhook + commands + menu button, then exit
    python bot.py --setup      set the bot commands + the menu button, then exit
    python bot.py --info       print the bot / webhook / channel diagnostic, then exit

IMPORTANT: add the bot as an ADMINISTRATOR of the channel, otherwise Telegram does not let it read the member
list and nobody can pass the gate (or set REQUIRED_CHANNEL=off to disable the gate).
"""
import argparse
import json
import logging
import sys
import time

from config import Config
from services.telegram_service import (TelegramError, diagnose, ensure_webhook, handle_update, setup_bot, tg_call)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mgfr.bot")


def poll():
    tg_call("deleteWebhook", {"drop_pending_updates": False})  # polling and webhook are exclusive
    log.info("%s bot started (long polling). Ctrl+C to stop.", Config.APP_NAME)
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
    parser = argparse.ArgumentParser(description="Manga Gallery FR bot")
    parser.add_argument("--webhook", action="store_true")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--info", action="store_true")
    args = parser.parse_args()

    if not Config.TELEGRAM_BOT_TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN manquant (variable d'environnement).")
    if args.info:
        print(json.dumps(diagnose(), indent=2, ensure_ascii=False))
    elif args.setup:
        setup_bot()
        log.info("Commands and menu button configured.")
    elif args.webhook:
        log.info("Webhook set: %s", ensure_webhook())
        setup_bot()
        print(json.dumps(diagnose(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(diagnose(), indent=2, ensure_ascii=False))
        try:
            poll()
        except KeyboardInterrupt:
            log.info("Stopped.")


if __name__ == "__main__":
    main()
