"""Time-based one-time passwords (RFC 6238) and recovery codes for two-step verification.

The shared secret is encrypted at rest (Fernet) with a key derived from TOTP_ENCRYPTION_KEY, falling back to
OTP_SECRET and then JWT_SECRET, so a copy of the database alone does not yield working codes. Recovery codes are
stored only as keyed hashes. A code can be used once: the time step of the last accepted code is remembered and
anything at or before it is refused, which also stops a code shoulder-surfed or phished within its 30 seconds
from being replayed.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1                      # accept the previous and next step too, for clock drift
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"       # no look-alikes (i l o 0 1)

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")

def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(number).zfill(DIGITS)

def code_at(secret: str, at: float) -> str:
    return _hotp(secret, int(at // STEP_SECONDS))

def verify(secret: str, code: str, last_step: int | None = None, now: float | None = None) -> int | None:
    """The time step the code belongs to if it is valid and newer than `last_step`, else None."""
    code = "".join(code.split())
    if len(code) != DIGITS or not (code.isascii() and code.isdigit()):
        return None
    current = int((time.time() if now is None else now) // STEP_SECONDS)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None

def otpauth_uri(secret: str, email: str, issuer: str = "Phantora") -> str:
    label = quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"

def _fernet() -> Fernet:
    material = (settings.totp_encryption_key or settings.otp_secret or settings.jwt_secret).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"parda-totp-v1:" + material).digest()))

def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()

def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None

def new_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"
    return [one() for _ in range(count)]

def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())

def recovery_hash(code: str) -> str:
    key = (settings.otp_secret or settings.jwt_secret).encode()
    return hmac.new(key, b"recovery:" + normalize_recovery_code(code).encode(), hashlib.sha256).hexdigest()

def looks_like_recovery_code(code: str) -> bool:
    return len(normalize_recovery_code(code)) == 10 and not code.strip().isdigit()
