"""Telegram notifications: linking an account to a chat, the bot's replies, and best-effort delivery.

The feature is off until TELEGRAM_BOT_TOKEN is set. Linking works like this: a signed-in customer asks for a link
token (single use, 15 minutes, only its hash is stored) and opens https://t.me/<bot>?start=<token>; Telegram then
calls our webhook with "/start <token>" and the chat id, which is stored against that customer. Webhook calls are
accepted only with the secret header that was registered with Telegram. Messages are plain text (no markup, so a
film title cannot change formatting) and are sent best-effort next to the e-mail; a chat that blocked the bot is
unlinked automatically.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
import httpx
import sqlalchemy as sa
from sqlalchemy.orm import Session
from .config import settings
from .models import TelegramLink, TelegramLinkToken, User

logger = logging.getLogger("parda.telegram")
TOKEN_MINUTES = 15
MAX_ACTIVE_TOKENS = 5

class TelegramError(Exception):
    def __init__(self, status: int, description: str):
        super().__init__(f"Telegram API error {status}: {description}")
        self.status, self.description = status, description

def configured() -> bool:
    return bool(settings.telegram_bot_token)

def _api(method: str, payload: dict) -> dict:
    """One call to the Bot API. Tests replace this function."""
    try:
        response = httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=payload, timeout=6.0)
    except httpx.HTTPError as exc:
        raise TelegramError(0, type(exc).__name__) from exc
    if response.status_code != 200:
        description = ""
        try:
            description = response.json().get("description", "")
        except ValueError:
            pass
        raise TelegramError(response.status_code, description)
    return response.json()

def send_text(chat_id: int, text: str) -> None:
    _api("sendMessage", {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True})

def webhook_secret_ok(header_value: str | None) -> bool:
    expected = settings.telegram_webhook_secret
    return bool(expected) and header_value is not None and hmac.compare_digest(header_value.encode(), expected.encode())

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _now() -> datetime:
    return datetime.now(timezone.utc)

def status_for(db: Session, user: User) -> dict:
    link = db.scalar(sa.select(TelegramLink).where(TelegramLink.user_id == user.id))
    return {"configured": configured(), "bot_username": settings.telegram_bot_username or None,
            "linked": link is not None and link.enabled}

def create_link(db: Session, user: User) -> dict:
    """Issue a one-time token and the deep link that carries it. The caller commits."""
    db.execute(sa.delete(TelegramLinkToken).where(TelegramLinkToken.user_id == user.id,
                                                  sa.or_(TelegramLinkToken.used_at.is_not(None), TelegramLinkToken.expires_at <= _now())))
    active = db.scalar(sa.select(sa.func.count(TelegramLinkToken.id)).where(TelegramLinkToken.user_id == user.id)) or 0
    if active >= MAX_ACTIVE_TOKENS:
        oldest = db.scalar(sa.select(TelegramLinkToken.id).where(TelegramLinkToken.user_id == user.id).order_by(TelegramLinkToken.id).limit(1))
        db.execute(sa.delete(TelegramLinkToken).where(TelegramLinkToken.id == oldest))
    token = secrets.token_urlsafe(24)
    expires = _now() + timedelta(minutes=TOKEN_MINUTES)
    db.add(TelegramLinkToken(user_id=user.id, token_hash=_hash(token), expires_at=expires))
    return {"url": f"https://t.me/{settings.telegram_bot_username}?start={token}", "expires_at": expires}

def unlink(db: Session, user_id: int) -> bool:
    link = db.scalar(sa.select(TelegramLink).where(TelegramLink.user_id == user_id))
    if link:
        db.delete(link)
    return link is not None

HELP = ("Phantora Cinema notifications.\n\nTo connect this chat, open your profile on the Phantora website, choose "
        "Telegram and press Connect. Send /stop to stop receiving messages here.")

def handle_update(db: Session, update: dict) -> tuple[int, str] | None:
    """Apply one Telegram update. Returns (chat_id, reply) or None when there is nothing to answer. Caller commits."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    chat_id = chat.get("id")
    if not isinstance(chat_id, int) or chat.get("type") != "private" or not text.startswith("/"):
        return None
    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()
    argument = argument.strip()
    if command == "/stop":
        link = db.scalar(sa.select(TelegramLink).where(TelegramLink.chat_id == chat_id))
        if link:
            db.delete(link)
            return chat_id, "Notifications stopped. You can connect again from your Phantora profile."
        return chat_id, "This chat is not connected to a Phantora account."
    if command == "/start" and argument:
        return chat_id, _redeem(db, chat_id, argument)
    return chat_id, HELP

def _redeem(db: Session, chat_id: int, token: str) -> str:
    record = db.scalar(sa.select(TelegramLinkToken).where(TelegramLinkToken.token_hash == _hash(token)).with_for_update())
    if record is None or record.used_at is not None or record.expires_at <= _now():
        return "This link has expired or was already used. Create a new one in your Phantora profile."
    owner = db.scalar(sa.select(TelegramLink).where(TelegramLink.chat_id == chat_id))
    if owner is not None and owner.user_id != record.user_id:
        return "This Telegram chat is already connected to another Phantora account. Send /stop first to disconnect it."
    record.used_at = _now()
    existing = db.scalar(sa.select(TelegramLink).where(TelegramLink.user_id == record.user_id))
    if existing:
        existing.chat_id, existing.enabled = chat_id, True
    else:
        db.add(TelegramLink(user_id=record.user_id, chat_id=chat_id))
    return "Connected! You will receive your ticket confirmations and refunds here."

def notify_user(db: Session, user_id: int, text: str) -> None:
    """Best-effort message to a customer's linked chat. Never raises: e-mail stays the primary channel."""
    if not configured():
        return
    link = db.scalar(sa.select(TelegramLink).where(TelegramLink.user_id == user_id, TelegramLink.enabled.is_(True)))
    if link is None:
        return
    try:
        send_text(link.chat_id, text)
    except TelegramError as exc:
        if exc.status in (400, 403):          # blocked the bot, deleted the chat: stop trying
            logger.info("Telegram chat for user %s is unreachable (%s); unlinking", user_id, exc.description)
            db.delete(link)
        else:
            logger.warning("Telegram delivery failed for user %s: %s", user_id, exc)
    except Exception:
        logger.exception("Unexpected Telegram failure for user %s", user_id)

def register_webhook(url: str) -> dict:
    """Tell Telegram where to send updates (used once per deployment by `python -m app.telegram_setup`)."""
    return _api("setWebhook", {"url": url, "secret_token": settings.telegram_webhook_secret,
                               "allowed_updates": ["message"], "drop_pending_updates": True})
