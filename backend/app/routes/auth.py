from datetime import datetime, timedelta, timezone
from base64 import b64decode
from binascii import Error as BinasciiError
import re
import sqlalchemy as sa
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from .. import ratelimit, sessions
from ..config import settings
from ..database import get_db
from ..models import (EmailOtpChallenge, PasswordResetChallenge, Role, User)
from ..schemas import (EmailChallengeOut, EmailCodeVerify, EmailResend, Login, PasswordResetConfirm, PasswordResetRequest, ProfileUpdate, Token, UserCreate)
from ..operators import scope_of
from ..security import current_user, hash_password, make_token, verify_password
from ..otp import new_code
from ..mail import (EmailDeliveryError, email_code_hash, email_code_matches, send_email_code,
                   send_password_reset_email)
from ..services import enforce_resend_cooldown, resend_available_at
from ..audit import record

router = APIRouter()

# Abuse limits: (max events, window seconds). Per-IP limits are generous because
# mobile carriers often share one address between many customers; the per-account
# failure counters are what actually stop password and code guessing.
LOGIN_IP_LIMIT = (60, 300)

LOGIN_ACCOUNT_IP_FAILURES = (5, 900)     # one account guessed from one address

LOGIN_ACCOUNT_FAILURES = (20, 3600)      # one account guessed from many addresses

REGISTER_IP_LIMIT = (20, 3600)

EMAIL_RESEND_IP_LIMIT = (20, 3600)

CODE_IP_LIMIT = (60, 600)

CODE_ACCOUNT_FAILURES = (10, 1800)

RESET_REQUEST_IP_LIMIT = (20, 3600)
REFRESH_IP_LIMIT = (120, 600)

def _access_seconds() -> int:
    return settings.jwt_expire_minutes * 60

def require_trusted_origin(request: Request) -> None:
    """Cookie-authenticated calls must come from our own pages. SameSite=Strict already stops browsers sending
    the cookie cross-site; this is the second line of defence."""
    if request.headers.get("sec-fetch-site") == "same-origin":
        return          # set by the browser itself and not forgeable by page script
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = {o.strip().rstrip("/") for o in settings.cors_origins.split(",") if o.strip()}
    allowed.add(str(request.base_url).rstrip("/"))
    if origin.rstrip("/") not in allowed:
        raise HTTPException(403, "Cross-site request refused")

PASSWORD_RESET_CODE_MINUTES = 10

PASSWORD_RESET_MAX_ATTEMPTS = 5

PASSWORD_RESET_REQUEST_LIMIT = 3

_AVATAR_DATA_URL = re.compile(r"^data:image/(?:jpeg|png|webp);base64,([A-Za-z0-9+/]+={0,2})$")

_MAX_AVATAR_BYTES = 300 * 1024

def _user_payload(user: User, db: Session | None = None) -> dict:
    payload = {"id": user.id, "name": user.nickname, "nickname": user.nickname,
            "email": user.email, "role": user.role.value, "created_at": user.created_at,
            "avatar_data": user.avatar_data}
    if user.role == Role.ADMIN:
        # null = an owner (every cinema); a list = an operator limited to those cinemas
        scope = scope_of(db, user) if db is not None else None
        payload["operator_cinemas"] = None if scope is None else sorted(scope)
    return payload

def _validated_avatar(value: str | None) -> str | None:
    if value is None:
        return None
    match = _AVATAR_DATA_URL.fullmatch(value)
    if not match:
        raise HTTPException(422, "Profile photo must be a PNG, JPEG, or WebP image")
    try:
        image = b64decode(match.group(1), validate=True)
    except (ValueError, BinasciiError) as exc:
        raise HTTPException(422, "Profile photo is not valid") from exc
    if not image or len(image) > _MAX_AVATAR_BYTES:
        raise HTTPException(422, "Profile photo must be smaller than 300 KB")
    return value

@router.post("/auth/register", status_code=201, dependencies=[ratelimit.per_ip("register", *REGISTER_IP_LIMIT)])
def register(data: UserCreate, db: Session = Depends(get_db)):
    nickname=data.nickname.strip().lower()
    email = str(data.email).lower()
    existing = db.scalar(sa.select(User).where(sa.or_(
        User.email == email, sa.func.lower(User.nickname) == nickname
    )))
    if existing:
        if existing.email == email and existing.active and not existing.email_verified:
            latest = db.scalar(sa.select(EmailOtpChallenge).where(EmailOtpChallenge.user_id == existing.id)
                .order_by(EmailOtpChallenge.created_at.desc()))
            now = datetime.now(timezone.utc)
            return EmailChallengeOut(
                email=existing.email,
                expires_at=latest.expires_at if latest and latest.expires_at > now else now + timedelta(minutes=10),
                resend_available_at=resend_available_at(latest.created_at) if latest else now,
                demo_mode=False,
                demo_code=None,
            )
        if existing.email == email:
            raise HTTPException(409, "This email is already registered. Sign in or reset the password")
        raise HTTPException(409, "This nickname is already in use")
    user = User(name=nickname, nickname=nickname, email=email,
                password_hash=hash_password(data.password), role=Role.CUSTOMER)
    db.add(user)
    try:
        db.flush()
        recent = db.scalar(sa.select(sa.func.count(EmailOtpChallenge.id)).where(
            EmailOtpChallenge.user_id == user.id,
            EmailOtpChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
        if recent >= 3:
            raise HTTPException(429, "Too many verification emails. Try again in 10 minutes")
        code = new_code()
        challenge = EmailOtpChallenge(user_id=user.id, code_hash=email_code_hash(user.id, code),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
        is_demo = send_email_code(user.email, code)
        db.add(challenge)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This email or nickname is already registered")
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return EmailChallengeOut(email=user.email, expires_at=challenge.expires_at,
        resend_available_at=resend_available_at(), demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/email/resend", response_model=EmailChallengeOut, dependencies=[ratelimit.per_ip("email-resend", *EMAIL_RESEND_IP_LIMIT)])
def resend_email_code(data: EmailResend, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    user = db.scalar(sa.select(User).where(User.email == email, User.active.is_(True)))
    if not user or user.email_verified:
        raise HTTPException(404, "Account awaiting verification was not found")
    latest = db.scalar(sa.select(EmailOtpChallenge).where(EmailOtpChallenge.user_id == user.id)
        .order_by(EmailOtpChallenge.created_at.desc()))
    enforce_resend_cooldown(latest.created_at if latest else None, "email verification")
    recent = db.scalar(sa.select(sa.func.count(EmailOtpChallenge.id)).where(
        EmailOtpChallenge.user_id == user.id,
        EmailOtpChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
    if recent >= 3:
        raise HTTPException(429, "Too many verification emails. Try again in 10 minutes")
    code = new_code()
    challenge = EmailOtpChallenge(user_id=user.id, code_hash=email_code_hash(user.id, code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    try:
        is_demo = send_email_code(user.email, code)
        db.add(challenge)
        db.commit()
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return EmailChallengeOut(email=user.email, expires_at=challenge.expires_at,
        resend_available_at=resend_available_at(), demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/email/verify", dependencies=[ratelimit.per_ip("email-verify", *CODE_IP_LIMIT)])
def verify_email(data: EmailCodeVerify, request: Request, response: Response, db: Session = Depends(get_db)):
    email_key = str(data.email).lower()
    ratelimit.check("email-verify-fail", email_key, *CODE_ACCOUNT_FAILURES)
    user = db.scalar(sa.select(User).where(User.email == str(data.email).lower()).with_for_update())
    if not user or not user.active:
        raise HTTPException(404, "Account awaiting verification was not found")
    if user.email_verified:
        # Nothing to verify. This must never hand out a session: no code has been checked, and anyone who
        # knows the address could otherwise sign in as this account. Signing in goes through /auth/login.
        raise HTTPException(404, "Account awaiting verification was not found")
    challenge = db.scalar(sa.select(EmailOtpChallenge).where(
        EmailOtpChallenge.user_id == user.id, EmailOtpChallenge.consumed_at.is_(None)
    ).order_by(EmailOtpChallenge.created_at.desc()).with_for_update())
    now = datetime.now(timezone.utc)
    if not challenge or challenge.expires_at <= now:
        raise HTTPException(410, "Verification code expired. Request another email")
    if challenge.attempts >= 5:
        raise HTTPException(429, "Too many incorrect codes. Request a new email")
    if not email_code_matches(user.id, data.code, challenge.code_hash):
        challenge.attempts += 1
        db.commit()
        ratelimit.record_failure("email-verify-fail", email_key, CODE_ACCOUNT_FAILURES[1])
        raise HTTPException(422, "Incorrect verification code")
    challenge.consumed_at = now
    user.email_verified = True
    sessions.start_session(db, user, request, response)
    db.commit()
    return {"access_token": make_token(user), "token_type": "bearer", "expires_in": _access_seconds(),
            "user": _user_payload(user, db)}

@router.post("/auth/login", response_model=Token)
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    email = data.email.lower()
    ip = ratelimit.client_ip(request)
    ratelimit.hit("login-ip", ip, *LOGIN_IP_LIMIT)
    ratelimit.check("login-fail-ip", f"{email}|{ip}", *LOGIN_ACCOUNT_IP_FAILURES)
    ratelimit.check("login-fail", email, *LOGIN_ACCOUNT_FAILURES)
    user = db.scalar(sa.select(User).where(User.email == email))
    if not user or not verify_password(data.password, user.password_hash) or not user.active:
        ratelimit.record_failure("login-fail-ip", f"{email}|{ip}", LOGIN_ACCOUNT_IP_FAILURES[1])
        ratelimit.record_failure("login-fail", email, LOGIN_ACCOUNT_FAILURES[1])
        raise HTTPException(401, "Email or password is incorrect")
    ratelimit.reset("login-fail-ip", f"{email}|{ip}")
    if not user.email_verified:
        raise HTTPException(403, "Verify your email before signing in")
    sessions.start_session(db, user, request, response)
    db.commit()
    return Token(access_token=make_token(user), expires_in=_access_seconds())

@router.post("/auth/refresh", response_model=Token, dependencies=[ratelimit.per_ip("refresh", *REFRESH_IP_LIMIT)])
def refresh_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """Trade the httpOnly refresh cookie for a new access token (and a new cookie)."""
    require_trusted_origin(request)
    try:
        user = sessions.rotate_session(db, request, response)
    except sessions.SessionError as exc:
        rejected = JSONResponse(status_code=401, content={"detail": str(exc)})
        sessions.clear_cookie(rejected)
        return rejected
    db.commit()
    return Token(access_token=make_token(user), expires_in=_access_seconds())

@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Sign this browser out. Needs only the cookie, so it works even after the access token expired."""
    require_trusted_origin(request)
    sessions.end_session(db, request, response)
    db.commit()

@router.post("/auth/password-reset/request", response_model=EmailChallengeOut, dependencies=[ratelimit.per_ip("reset-request", *RESET_REQUEST_IP_LIMIT)])
def request_password_reset(data: PasswordResetRequest, db: Session = Depends(get_db)):
    """Start a reset without revealing whether an address owns an account."""
    email = str(data.email).lower()
    now = datetime.now(timezone.utc)
    generic = EmailChallengeOut(email=email, expires_at=now + timedelta(minutes=PASSWORD_RESET_CODE_MINUTES),
                                resend_available_at=resend_available_at(now), demo_mode=False, demo_code=None)
    # Possession of a reset code proves ownership of the mailbox as well.  Let
    # people who left registration before email verification recover their
    # account instead of leaving them unable to sign in or reset their password.
    user = db.scalar(sa.select(User).where(User.email == email, User.active.is_(True)))
    if not user:
        return generic
    latest = db.scalar(sa.select(PasswordResetChallenge).where(PasswordResetChallenge.user_id == user.id)
        .order_by(PasswordResetChallenge.created_at.desc()))
    enforce_resend_cooldown(latest.created_at if latest else None, "password reset")
    recent = db.scalar(sa.select(sa.func.count(PasswordResetChallenge.id)).where(
        PasswordResetChallenge.user_id == user.id,
        PasswordResetChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
    if recent >= PASSWORD_RESET_REQUEST_LIMIT:
        return generic
    code = new_code()
    challenge = PasswordResetChallenge(user_id=user.id, code_hash=email_code_hash(user.id, code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_CODE_MINUTES))
    try:
        is_demo = send_password_reset_email(user.email, code)
        db.add(challenge)
        db.commit()
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return EmailChallengeOut(email=email, expires_at=challenge.expires_at,
                             resend_available_at=resend_available_at(), demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/password-reset/confirm", dependencies=[ratelimit.per_ip("reset-confirm", *CODE_IP_LIMIT)])
def confirm_password_reset(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    email_key = str(data.email).lower()
    ratelimit.check("reset-confirm-fail", email_key, *CODE_ACCOUNT_FAILURES)
    user = db.scalar(sa.select(User).where(User.email == str(data.email).lower(), User.active.is_(True)).with_for_update())
    if not user:
        raise HTTPException(422, "The code or email is not valid")
    challenge = db.scalar(sa.select(PasswordResetChallenge).where(
        PasswordResetChallenge.user_id == user.id, PasswordResetChallenge.consumed_at.is_(None)
    ).order_by(PasswordResetChallenge.created_at.desc()).with_for_update())
    now = datetime.now(timezone.utc)
    if not challenge or challenge.expires_at <= now:
        raise HTTPException(410, "This reset code has expired. Request a new code")
    if challenge.attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many incorrect codes. Request a new code")
    if not email_code_matches(user.id, data.code, challenge.code_hash):
        challenge.attempts += 1
        db.commit()
        ratelimit.record_failure("reset-confirm-fail", email_key, CODE_ACCOUNT_FAILURES[1])
        raise HTTPException(422, "The code or email is not valid")
    challenge.consumed_at = now
    user.password_hash = hash_password(data.password)
    user.email_verified = True
    user.token_version = (user.token_version or 0) + 1   # a reset signs the account out everywhere
    sessions.revoke_user_sessions(db, user.id)
    record(db, user, "auth.password_reset", "user", user.id)
    db.commit()
    return {"message": "Password reset complete"}

@router.post("/auth/logout-all", status_code=204)
def logout_all_devices(response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Revoke every access token issued to this account, including the caller's own."""
    db.execute(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))
    sessions.revoke_user_sessions(db, user.id)
    sessions.clear_cookie(response)
    record(db, user, "auth.sessions_revoked", "user", user.id)
    db.commit()

@router.get("/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _user_payload(user, db)

@router.patch("/auth/profile")
def update_profile(data: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    nickname = data.nickname.strip().lower()
    if nickname != user.nickname:
        existing = db.scalar(sa.select(User).where(sa.func.lower(User.nickname) == nickname, User.id != user.id))
        if existing:
            raise HTTPException(409, "This username is already in use")
        user.nickname = nickname
        user.name = nickname
    user.avatar_data = _validated_avatar(data.avatar_data)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This username is already in use") from exc
    db.refresh(user)
    return _user_payload(user, db)
