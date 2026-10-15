"""Two-step verification (authenticator app + recovery codes) for any account; required for operators when
REQUIRE_OPERATOR_2FA is on."""
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import ratelimit, sessions, totp, twofactor
from ..audit import record
from ..config import settings
from ..database import get_db
from ..models import Role, TotpRecoveryCode, User, UserTotp
from ..schemas import (LoginOut, TwoFactorCodeIn, TwoFactorEnabledOut, TwoFactorLoginIn, TwoFactorProtectedIn,
                       TwoFactorSetupIn, TwoFactorSetupOut, TwoFactorStatusOut)
from ..security import current_user, make_token, verify_password
from .auth import _access_seconds

router = APIRouter()

CODE_FAILURES = (5, 900)         # wrong second-step codes per account per 15 minutes
CODE_IP_LIMIT = (30, 300)

def _guard(user: User) -> None:
    ratelimit.check("mfa-fail", str(user.id), *CODE_FAILURES)

def _wrong_code(user: User) -> HTTPException:
    ratelimit.record_failure("mfa-fail", str(user.id), CODE_FAILURES[1])
    return HTTPException(422, "That code is not correct")

def _require_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        ratelimit.record_failure("mfa-fail", str(user.id), CODE_FAILURES[1])
        raise HTTPException(403, "The password is not correct")

@router.post("/auth/login/2fa", response_model=LoginOut, dependencies=[ratelimit.per_ip("mfa-login", *CODE_IP_LIMIT)])
def login_second_step(data: TwoFactorLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = twofactor.read_challenge(db, data.challenge)
    _guard(user)
    method = twofactor.check_second_step(db, user, data.code)
    if method is None:
        db.rollback()
        raise _wrong_code(user)
    ratelimit.reset("mfa-fail", str(user.id))
    if method == "recovery":
        db.flush()
        record(db, user, "2fa.recovery_code_used", "user", user.id, left=twofactor.recovery_codes_left(db, user.id))
    sessions.start_session(db, user, request, response, mfa=True)
    db.commit()
    return LoginOut(access_token=make_token(user, mfa=True), expires_in=_access_seconds())

@router.get("/auth/2fa", response_model=TwoFactorStatusOut)
def two_factor_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    enabled = twofactor.confirmed(db, user.id) is not None
    return TwoFactorStatusOut(enabled=enabled, recovery_codes_left=twofactor.recovery_codes_left(db, user.id) if enabled else 0,
                              required=settings.require_operator_2fa and user.role == Role.ADMIN)

@router.post("/auth/2fa/setup", response_model=TwoFactorSetupOut)
def start_enrolment(data: TwoFactorSetupIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Begin turning on two-step verification. Nothing changes for sign-in until /auth/2fa/enable confirms a code."""
    _guard(user)
    _require_password(user, data.password)
    if twofactor.confirmed(db, user.id):
        raise HTTPException(409, "Two-step verification is already on")
    secret = totp.new_secret()
    db.execute(sa.delete(UserTotp).where(UserTotp.user_id == user.id))
    db.add(UserTotp(user_id=user.id, secret_enc=totp.encrypt(secret)))
    db.commit()
    return TwoFactorSetupOut(secret=secret, otpauth_uri=totp.otpauth_uri(secret, user.email))

@router.post("/auth/2fa/enable", response_model=TwoFactorEnabledOut)
def finish_enrolment(data: TwoFactorCodeIn, request: Request, response: Response, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    """Confirm the first code from the authenticator app. Other sign-ins end; this one continues with a new token."""
    _guard(user)
    row = db.scalar(sa.select(UserTotp).where(UserTotp.user_id == user.id, UserTotp.confirmed_at.is_(None)).with_for_update())
    if row is None:
        raise HTTPException(409, "Start the setup first")
    secret = totp.decrypt(row.secret_enc)
    step = totp.verify(secret, data.code) if secret else None
    if step is None:
        db.rollback()
        raise _wrong_code(user)
    row.confirmed_at = datetime.now(timezone.utc)
    row.last_step = step
    codes = twofactor.replace_recovery_codes(db, user)
    user.token_version = (user.token_version or 0) + 1
    sessions.revoke_user_sessions(db, user.id)
    sessions.start_session(db, user, request, response, mfa=True)
    record(db, user, "2fa.enabled", "user", user.id)
    db.commit()
    ratelimit.reset("mfa-fail", str(user.id))
    return TwoFactorEnabledOut(recovery_codes=codes, access_token=make_token(user, mfa=True), expires_in=_access_seconds())

@router.post("/auth/2fa/disable", status_code=204)
def disable(data: TwoFactorProtectedIn, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _guard(user)
    _require_password(user, data.password)
    if settings.require_operator_2fa and user.role == Role.ADMIN:
        raise HTTPException(409, "Operator accounts must keep two-step verification on")
    if twofactor.check_second_step(db, user, data.code) is None:
        db.rollback()
        raise _wrong_code(user)
    db.execute(sa.delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id))
    db.execute(sa.delete(UserTotp).where(UserTotp.user_id == user.id))
    user.token_version = (user.token_version or 0) + 1
    sessions.revoke_user_sessions(db, user.id)
    sessions.clear_cookie(response)
    record(db, user, "2fa.disabled", "user", user.id)
    db.commit()

@router.post("/auth/2fa/recovery-codes")
def new_recovery_codes(data: TwoFactorProtectedIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Replace all recovery codes with ten new ones (shown once)."""
    _guard(user)
    _require_password(user, data.password)
    if twofactor.check_second_step(db, user, data.code) is None:
        db.rollback()
        raise _wrong_code(user)
    codes = twofactor.replace_recovery_codes(db, user)
    record(db, user, "2fa.recovery_codes_replaced", "user", user.id)
    db.commit()
    return {"recovery_codes": codes}
