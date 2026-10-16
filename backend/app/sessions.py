"""Browser sessions: a short-lived access token plus a rotating refresh token in an httpOnly cookie.

The refresh token is a random secret that exists only in the cookie (JavaScript cannot read it)
and, as a SHA-256 hash, in the database. Every refresh issues a new one and retires the old one.
Replaying a retired token after a short grace period means it was copied, so the whole chain of
tokens (a "family", one per sign-in) is revoked and the user must sign in again.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from fastapi import Request, Response
from sqlalchemy.orm import Session
from .audit import record
from .config import settings
from .database import engine
from .models import RefreshToken, User
from .ratelimit import client_ip

COOKIE_NAME = "parda_refresh"
COOKIE_PATH = "/api/auth"      # the browser sends it only to the sign-in/refresh/sign-out endpoints

class SessionError(Exception):
    """The refresh token cannot be used; the message is safe to show."""

class NotSignedIn(SessionError):
    """The browser sent no refresh cookie at all: an ordinary visitor, not a failed attempt."""

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _cookie_options() -> dict:
    return {"path": COOKIE_PATH, "httponly": True, "secure": settings.is_production, "samesite": "strict"}

def set_cookie(response: Response, token: str, expires_at: datetime) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=max(0, int((expires_at - _now()).total_seconds())), **_cookie_options())

def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, **_cookie_options())

def _issue(db: Session, user_id: int, family_id: str, family_created_at: datetime, request: Request,
           mfa: bool = False) -> tuple[str, RefreshToken]:
    token = secrets.token_urlsafe(48)
    now = _now()
    row = RefreshToken(
        user_id=user_id, token_hash=_hash(token), family_id=family_id, family_created_at=family_created_at,
        expires_at=min(now + timedelta(days=settings.refresh_token_days),
                       family_created_at + timedelta(days=settings.refresh_family_max_days)),
        user_agent=request.headers.get("user-agent", "")[:200] or None, ip=client_ip(request), mfa=mfa)
    db.add(row)
    return token, row

def start_session(db: Session, user: User, request: Request, response: Response, mfa: bool = False) -> None:
    """Begin a new sign-in. `mfa` records that the second step was completed. The caller commits."""
    token, row = _issue(db, user.id, str(uuid.uuid4()), _now(), request, mfa)
    set_cookie(response, token, row.expires_at)

def revoke_family(db: Session, family_id: str) -> None:
    db.execute(sa.update(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=_now()))

def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(sa.update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=_now()))

def end_session(db: Session, request: Request, response: Response) -> None:
    """Sign out this browser: retire its token family and clear the cookie. The caller commits."""
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        row = db.scalar(sa.select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)))
        if row:
            revoke_family(db, row.family_id)
    clear_cookie(response)

def rotate_session(db: Session, request: Request, response: Response) -> tuple[User, bool]:
    """Validate the cookie's refresh token and replace it; returns the user and whether the session passed the
    second step. Raises SessionError; the caller commits on success."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise NotSignedIn("Not signed in")
    row = db.scalar(sa.select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)).with_for_update())
    now = _now()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise SessionError("Session expired. Sign in again")
    user = db.get(User, row.user_id)
    if not user or not user.active:
        raise SessionError("Session expired. Sign in again")
    if row.rotated_at is not None:
        if (now - row.rotated_at).total_seconds() <= settings.refresh_reuse_grace_seconds:
            # A token that was retired a moment ago is presented again. Either another tab raced this request, or the
            # reply to the first refresh never reached the browser (a dropped connection, a server that was restarting)
            # and the browser still holds the old cookie. Give this holder its own successor so its cookie is current
            # in both cases; leaving it on the retired token would sign the user out at the next reload. Presenting
            # the retired token after the grace period is still treated as theft.
            token, new_row = _issue(db, user.id, row.family_id, row.family_created_at, request, row.mfa)
            set_cookie(response, token, new_row.expires_at)
            return user, row.mfa
        revoke_family(db, row.family_id)
        record(db, user, "auth.refresh_reuse_detected", "user", user.id, family_id=row.family_id)
        db.commit()
        raise SessionError("Session expired. Sign in again")
    row.rotated_at = now
    token, new_row = _issue(db, user.id, row.family_id, row.family_created_at, request, row.mfa)
    set_cookie(response, token, new_row.expires_at)
    return user, row.mfa

def purge_expired_refresh_tokens(retain_days: int = 7) -> int:
    """Delete tokens that expired or were revoked more than `retain_days` ago."""
    cutoff = _now() - timedelta(days=retain_days)
    with engine.begin() as conn:
        return conn.execute(sa.delete(RefreshToken).where(sa.or_(
            RefreshToken.expires_at < cutoff, RefreshToken.revoked_at < cutoff))).rowcount
