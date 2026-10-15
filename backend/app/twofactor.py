"""Two-step verification: the sign-in challenge and the checking of codes. Routes live in routes/two_factor.py."""
from datetime import datetime, timedelta, timezone

import jwt
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import totp
from .config import settings
from .models import TotpRecoveryCode, User, UserTotp

CHALLENGE_MINUTES = 5
CHALLENGE_TYPE = "mfa-challenge"

def confirmed(db: Session, user_id: int) -> UserTotp | None:
    return db.scalar(sa.select(UserTotp).where(UserTotp.user_id == user_id, UserTotp.confirmed_at.is_not(None)))

def make_challenge(user: User) -> str:
    """Proof that the password step succeeded. It is not a session: it only lets /auth/login/2fa be tried."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "typ": CHALLENGE_TYPE, "tv": user.token_version or 0, "iat": now,
                       "exp": now + timedelta(minutes=CHALLENGE_MINUTES)}, settings.jwt_secret, algorithm="HS256")

def read_challenge(db: Session, token: str) -> User:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if data.get("typ") != CHALLENGE_TYPE:
            raise ValueError()
        user = db.get(User, int(data["sub"]))
        if not user or not user.active or not user.email_verified or int(data.get("tv", 0)) != (user.token_version or 0):
            raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "This sign-in expired. Enter your password again") from None

def check_second_step(db: Session, user: User, code: str) -> str | None:
    """Accept an authenticator code or a recovery code: returns "totp" or "recovery" (and uses it up), else None.

    The caller commits. The row is locked so two requests cannot both spend the same code.
    """
    row = db.scalar(sa.select(UserTotp).where(UserTotp.user_id == user.id, UserTotp.confirmed_at.is_not(None)).with_for_update())
    if row is None:
        return None
    if totp.looks_like_recovery_code(code):
        match = db.scalar(sa.select(TotpRecoveryCode).where(
            TotpRecoveryCode.user_id == user.id, TotpRecoveryCode.code_hash == totp.recovery_hash(code),
            TotpRecoveryCode.used_at.is_(None)).with_for_update())
        if match is None:
            return None
        match.used_at = datetime.now(timezone.utc)
        return "recovery"
    secret = totp.decrypt(row.secret_enc)
    step = totp.verify(secret, code, row.last_step) if secret else None
    if step is None:
        return None
    row.last_step = step
    return "totp"

def replace_recovery_codes(db: Session, user: User) -> list[str]:
    db.execute(sa.delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id))
    codes = totp.new_recovery_codes()
    for code in codes:
        db.add(TotpRecoveryCode(user_id=user.id, code_hash=totp.recovery_hash(code)))
    return codes

def recovery_codes_left(db: Session, user_id: int) -> int:
    return db.scalar(sa.select(sa.func.count(TotpRecoveryCode.id)).where(
        TotpRecoveryCode.user_id == user_id, TotpRecoveryCode.used_at.is_(None))) or 0
