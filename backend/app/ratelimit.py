"""PostgreSQL-backed fixed-window rate limiting.

State lives in the database so limits hold across several API instances and
restarts without needing Redis. Every call uses its own short transaction: a
failed attempt must still be counted when the request itself then errors out.
"""
import hashlib
import ipaddress
import logging
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .config import settings
from .database import engine

logger = logging.getLogger(__name__)

_HIT = text("""
INSERT INTO rate_limit_buckets AS b (key, window_start, hits)
VALUES (:key, now(), 1)
ON CONFLICT (key) DO UPDATE SET
  hits = CASE WHEN b.window_start <= now() - make_interval(secs => :window) THEN 1 ELSE b.hits + 1 END,
  window_start = CASE WHEN b.window_start <= now() - make_interval(secs => :window) THEN now() ELSE b.window_start END
RETURNING hits, GREATEST(1, CEIL(EXTRACT(EPOCH FROM (window_start + make_interval(secs => :window) - now()))))::int AS retry_after
""")
_PEEK = text("""
SELECT hits, GREATEST(1, CEIL(EXTRACT(EPOCH FROM (window_start + make_interval(secs => :window) - now()))))::int
FROM rate_limit_buckets WHERE key = :key AND window_start > now() - make_interval(secs => :window)
""")

def _key(scope: str, identifier: str) -> str:
    return f"{scope}:{hashlib.sha256(identifier.strip().lower().encode()).hexdigest()[:40]}"

def client_ip(request: Request) -> str:
    """Caller address. A forwarded header is trusted only when explicitly configured
    (e.g. CLIENT_IP_HEADER=cf-connecting-ip on Render); otherwise the socket peer."""
    header = settings.client_ip_header.strip()
    if header:
        value = request.headers.get(header, "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"

def _too_many(retry_after: int, message: str | None = None) -> HTTPException:
    minutes = max(1, -(-retry_after // 60))
    detail = message or (f"Too many attempts. Try again in {retry_after} seconds" if retry_after < 60
                         else f"Too many attempts. Try again in {minutes} minutes")
    return HTTPException(429, detail, headers={"Retry-After": str(retry_after)})

def hit(scope: str, identifier: str, limit: int, window_seconds: int) -> None:
    """Count one event and raise 429 once more than `limit` happen inside the window."""
    if not settings.rate_limit_enabled:
        return
    try:
        with engine.begin() as conn:
            hits, retry_after = conn.execute(_HIT, {"key": _key(scope, identifier), "window": window_seconds}).one()
    except SQLAlchemyError:
        logger.exception("Rate limiter unavailable; allowing request")
        return
    if hits > limit:
        raise _too_many(retry_after)

def check(scope: str, identifier: str, limit: int, window_seconds: int) -> None:
    """Raise 429 if `limit` failures were already recorded, without counting this call."""
    if not settings.rate_limit_enabled:
        return
    try:
        with engine.connect() as conn:
            row = conn.execute(_PEEK, {"key": _key(scope, identifier), "window": window_seconds}).first()
    except SQLAlchemyError:
        logger.exception("Rate limiter unavailable; allowing request")
        return
    if row and row[0] >= limit:
        raise _too_many(row[1])

def record_failure(scope: str, identifier: str, window_seconds: int) -> None:
    if not settings.rate_limit_enabled:
        return
    try:
        with engine.begin() as conn:
            conn.execute(_HIT, {"key": _key(scope, identifier), "window": window_seconds})
    except SQLAlchemyError:
        logger.exception("Rate limiter unavailable; failure not recorded")

def reset(scope: str, identifier: str) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_buckets WHERE key = :key"), {"key": _key(scope, identifier)})
    except SQLAlchemyError:
        logger.exception("Rate limiter unavailable; counter not reset")

def purge_expired(older_than_hours: int = 24) -> int:
    with engine.begin() as conn:
        return conn.execute(text("DELETE FROM rate_limit_buckets WHERE window_start < now() - make_interval(hours => :h)"),
                            {"h": older_than_hours}).rowcount

def per_ip(scope: str, limit: int, window_seconds: int):
    """FastAPI dependency limiting every call from one client address."""
    def dependency(request: Request) -> None:
        hit(scope, client_ip(request), limit, window_seconds)
    return Depends(dependency)
