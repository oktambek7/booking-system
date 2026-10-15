from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from .models import Role, User

password_hash = PasswordHash.recommended()
bearer = HTTPBearer()

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)

def make_token(user: User, mfa: bool = False) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user.id), "role": user.role.value, "tv": user.token_version or 0, "mfa": bool(mfa), "iat": now,
                       "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm="HS256")

def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    try:
        data = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        if data.get("typ"):
            raise ValueError()           # purpose-built tokens (e.g. the sign-in challenge) are never access tokens
        user = db.get(User, int(data["sub"]))
        if not user or not user.active:
            raise ValueError()
        # Tokens minted before versioning existed carry no "tv" claim and count as version 0.
        if int(data.get("tv", 0)) != (user.token_version or 0):
            raise ValueError()
        user.mfa_verified = bool(data.get("mfa"))       # not stored: only says how THIS sign-in was made
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})

def acts_as_operator(user: User) -> bool:
    """Whether this request may use operator powers: an operator account, and with REQUIRE_OPERATOR_2FA on, a
    sign-in that included the second step. Use this, not `user.role`, for every decision about operator access."""
    if user.role != Role.ADMIN:
        return False
    return not settings.require_operator_2fa or bool(getattr(user, "mfa_verified", False))

TWO_STEP_REQUIRED = "Operator accounts need two-step verification. Turn it on in your profile, then sign in again"

def require_roles(*roles: Role):
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Insufficient permissions")
        if user.role == Role.ADMIN and not acts_as_operator(user):
            raise HTTPException(403, TWO_STEP_REQUIRED)
        return user
    return check
