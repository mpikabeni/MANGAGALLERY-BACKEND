import hmac

from flask import Blueprint, current_app, jsonify, request

from config import Config
from services.telegram_service import (TelegramError, diagnose, ensure_webhook, handle_update, setup_bot,
                                        webhook_secret_token)
from utils.authz import require_admin
from utils.http import fail

telegram_bp = Blueprint("telegram", __name__)


@telegram_bp.post("/webhook")
def webhook():
    secret = webhook_secret_token()
    if not secret:  # without a secret anybody could forge updates: refuse to run
        return fail("Webhook désactivé : TELEGRAM_WEBHOOK_SECRET manquant", 503)
    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(received.encode(), secret.encode()):
        current_app.logger.warning("Telegram webhook refused: secret token mismatch (re-register with /api/telegram/health)")
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


@telegram_bp.get("/health")
def health():
    """Public, non-sensitive diagnostic: is the bot configured, is the webhook registered, is the bot admin of the channel?
    Open https://<backend>/api/telegram/health in a browser when /start does not answer."""
    return jsonify(success=True, **diagnose())


@telegram_bp.get("/status")
@require_admin
def status():
    return jsonify(success=True, **diagnose())


@telegram_bp.post("/set-webhook")
@require_admin
def set_webhook():
    try:
        url = ensure_webhook()
        setup_bot()
    except TelegramError as exc:
        return fail(str(exc), 502)
    return jsonify(success=True, message="Webhook et commandes configurés", webhook_url=url)
