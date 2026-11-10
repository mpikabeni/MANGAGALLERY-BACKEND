import hmac

from flask import Blueprint, current_app, jsonify, request

from config import Config
from services.telegram_service import TelegramError, channel_username, handle_update, tg_call
from utils.authz import require_admin
from utils.http import fail

telegram_bp = Blueprint("telegram", __name__)


@telegram_bp.post("/webhook")
def webhook():
    secret = Config.TELEGRAM_WEBHOOK_SECRET
    if not secret:  # without a secret anybody could forge updates: refuse to run
        return fail("Webhook désactivé : TELEGRAM_WEBHOOK_SECRET manquant", 503)
    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(received.encode(), secret.encode()):
        return fail("Unauthorized", 401)
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return fail("Invalid update", 400)
    try:
        handle_update(update)
    except Exception:
        current_app.logger.exception("Telegram webhook processing failed")
        # Always 200: otherwise Telegram retries the same update in a loop.
    return jsonify(success=True), 200


@telegram_bp.get("/status")
@require_admin
def status():
    return jsonify(success=True, configured=bool(Config.TELEGRAM_BOT_TOKEN),
                   bot_username=Config.TELEGRAM_BOT_USERNAME or None, channel=Config.REQUIRED_CHANNEL,
                   mini_app_configured=Config.TELEGRAM_MINI_APP_URL.startswith("https://"),
                   webhook_configured=bool(Config.PUBLIC_BACKEND_URL and Config.TELEGRAM_WEBHOOK_SECRET))


@telegram_bp.post("/set-webhook")
@require_admin
def set_webhook():
    if not (Config.TELEGRAM_BOT_TOKEN and Config.PUBLIC_BACKEND_URL and Config.TELEGRAM_WEBHOOK_SECRET):
        return fail("TELEGRAM_BOT_TOKEN, PUBLIC_BACKEND_URL et TELEGRAM_WEBHOOK_SECRET sont requis", 400)
    url = Config.PUBLIC_BACKEND_URL.rstrip("/") + "/api/telegram/webhook"
    try:
        tg_call("setWebhook", {"url": url, "secret_token": Config.TELEGRAM_WEBHOOK_SECRET,
                               "allowed_updates": ["message", "callback_query"]})
    except TelegramError as exc:
        return fail(str(exc), 502)
    return jsonify(success=True, message="Webhook configuré", webhook_url=url)
