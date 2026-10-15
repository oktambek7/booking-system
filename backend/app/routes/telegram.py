import logging
from datetime import datetime
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import ratelimit, telegram
from ..config import settings
from ..database import get_db
from ..models import User
from ..security import current_user

logger = logging.getLogger("parda.telegram")
router = APIRouter()

class TelegramStatusOut(BaseModel):
    configured: bool
    bot_username: str | None
    linked: bool

class TelegramLinkOut(BaseModel):
    url: str
    expires_at: datetime

@router.get("/telegram", response_model=TelegramStatusOut)
def telegram_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return telegram.status_for(db, user)

@router.post("/telegram/link", response_model=TelegramLinkOut)
def telegram_link(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """A one-time link that connects the customer's Telegram chat to their account."""
    if not telegram.configured() or not settings.telegram_bot_username:
        raise HTTPException(503, "Telegram notifications are not available")
    ratelimit.hit("telegram-link", str(user.id), 10, 3600)
    link = telegram.create_link(db, user)
    db.commit()
    return link

@router.delete("/telegram/link", status_code=204)
def telegram_unlink(db: Session = Depends(get_db), user: User = Depends(current_user)):
    telegram.unlink(db, user.id)
    db.commit()

@router.post("/telegram/webhook", dependencies=[ratelimit.per_ip("telegram-webhook", 1000, 60)])
def telegram_webhook(update: dict = Body(...), db: Session = Depends(get_db),
                     x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    """Called by Telegram only: every request must carry the secret registered with setWebhook."""
    if not telegram.configured():
        raise HTTPException(404, "Not found")
    if not telegram.webhook_secret_ok(x_telegram_bot_api_secret_token):
        raise HTTPException(403, "Forbidden")
    reply = telegram.handle_update(db, update)
    db.commit()
    if reply:
        try:
            telegram.send_text(*reply)
        except telegram.TelegramError as exc:
            logger.warning("Could not answer a Telegram message: %s", exc)
    return {"ok": True}      # always 200 once authenticated, or Telegram retries the same update
