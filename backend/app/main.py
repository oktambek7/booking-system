from contextlib import asynccontextmanager
import asyncio
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from . import models  # noqa: F401  (registers every table on Base.metadata)
from . import jobs
from .api import router
from .cinematica import router as cinematica_router
from .config import settings
from .database import SessionLocal, health_engine
from .live import start_live_updates, stop_live_updates
from .migrate import assert_schema_current, upgrade_to_head
from .models import Role, User
from .monitoring import init_sentry
from .observability import RequestContextMiddleware, configure_logging
from .security import hash_password
from .seed_demo import ensure_current_demo_schedule

configure_logging()
init_sentry()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.assert_production_ready()
    if not settings.is_production and settings.production_problems():
        logger.warning("Development configuration: %s production setting(s) would be rejected", len(settings.production_problems()))
    if settings.auto_migrate:
        upgrade_to_head()
    else:
        assert_schema_current()
    _ensure_initial_admin()
    _ensure_operator_bootstrap()
    created = ensure_current_demo_schedule()
    if created:
        logger.info("Created %s rolling Phantora demo screenings", created)
    # Discovery source failures must never prevent the booking API from
    # starting. Refresh catalogue data in the background instead.
    tasks = jobs.start_all() if settings.run_background_jobs else []
    await start_live_updates()
    try:
        yield
    finally:
        await stop_live_updates()
        await jobs.stop_all(tasks)

def _ensure_initial_admin() -> None:
    if not settings.admin_email and not settings.admin_password:
        return
    if not settings.admin_email or not settings.admin_password:
        raise RuntimeError("ADMIN_EMAIL and ADMIN_PASSWORD must be set together")
    if len(settings.admin_password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters")

    email = settings.admin_email.strip().lower()
    nickname = settings.admin_nickname.strip().lower()
    valid_nickname = nickname.replace("_", "").replace("-", "").replace(".", "").isalnum()
    if not nickname or len(nickname) > 40 or not valid_nickname:
        raise RuntimeError("ADMIN_NICKNAME must use letters, numbers, dot, dash, or underscore")

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            if existing.role != Role.ADMIN:
                raise RuntimeError("ADMIN_EMAIL already belongs to a non-admin account")
            if not existing.email_verified:
                existing.email_verified = True
                db.commit()
            return
        if db.scalar(select(User).where(User.nickname == nickname)):
            raise RuntimeError("ADMIN_NICKNAME is already in use")
        db.add(User(email=email, name=nickname, nickname=nickname,
                    password_hash=hash_password(settings.admin_password), role=Role.ADMIN,
                    active=True, phone_verified=False, email_verified=True))
        db.commit()

def _ensure_operator_bootstrap() -> None:
    """Promote one existing account when explicitly configured by the owner.

    This is deliberately configuration-only: public registration and regular
    users cannot grant themselves elevated access. The deployment variable is
    removed once the intended account has been promoted.
    """
    nickname = settings.operator_bootstrap_nickname.strip().lower()
    if not nickname:
        return
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.nickname == nickname))
        if not user:
            logger.warning("Configured operator bootstrap nickname was not found")
            return
        changed = user.role != Role.ADMIN or not user.email_verified
        user.role = Role.ADMIN
        user.email_verified = True
        if changed:
            db.commit()
            logger.info("Configured operator account promoted")

app = FastAPI(title="Booking System API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
app.add_middleware(RequestContextMiddleware)    # added last = outermost: request ids and headers cover every response
app.include_router(router)
app.include_router(cinematica_router)

HEALTH_TIMEOUT_SECONDS = 3.0

def _ping_database() -> None:
    with health_engine.connect() as conn:
        conn.execute(text("SELECT 1"))

async def _database_reachable() -> bool:
    # A database that stops answering without closing the socket would block the ping forever,
    # so the answer is bounded here rather than relying on driver timeouts.
    try:
        await asyncio.wait_for(asyncio.to_thread(_ping_database), HEALTH_TIMEOUT_SECONDS)
        return True
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)
        return False

def _build_version() -> str:
    """Short commit id of the running build, from the host's environment (Render sets RENDER_GIT_COMMIT)."""
    for name in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_VERSION"):
        value = os.environ.get(name, "").strip()
        if value:
            return value[:7]
    return ""

@app.get("/health/live")
def health_live():
    """Liveness: the process is up and serving. Never touches the database."""
    return {"status": "ok"}

@app.get("/health")
async def health():
    """Readiness: the API can reach its database. This is the path hosting health checks should use."""
    if await _database_reachable():
        body = {"status": "ok", "database": "ok"}
        version = _build_version()
        if version:
            body["version"] = version      # which commit is running, so a deploy can be checked from the browser
        return body
    return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unreachable"})
