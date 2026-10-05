from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from . import models
from .api import router
from .cinematica import router as cinematica_router, sync_active_cinematica_halls
from .config import settings
from .database import Base, SessionLocal, engine
from .models import Role, User
from .notifications import deliver_due_notifications, schedule_missing_reminders
from .security import hash_password
from .seed_demo import ensure_current_demo_schedule
from .tmdb import TMDBUnavailable, sync_catalog

logger = logging.getLogger(__name__)

def _refresh_tmdb_catalog() -> None:
    with SessionLocal() as db:
        now_playing, upcoming = sync_catalog(db)
    logger.info("TMDB refresh complete: %s now playing, %s upcoming", now_playing, upcoming)

def _refresh_cinematica_directory() -> None:
    with SessionLocal() as db:
        result = sync_active_cinematica_halls(db)
    logger.info("Cinematica hall directory refresh complete: %s", result)

async def _tmdb_refresh_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_refresh_tmdb_catalog)
        except TMDBUnavailable:
            logger.exception("TMDB catalog refresh failed")
        except Exception:
            logger.exception("Unexpected TMDB catalog refresh error")
        await asyncio.sleep(max(1, settings.tmdb_sync_interval_hours) * 60 * 60)

async def _booking_notification_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(schedule_missing_reminders)
            delivered = await asyncio.to_thread(deliver_due_notifications)
            if delivered:
                logger.info("Delivered %s customer booking notifications", delivered)
        except Exception:
            logger.exception("Booking notification delivery failed")
        await asyncio.sleep(max(30, settings.notification_poll_seconds))

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        migrations = Path(__file__).resolve().parent.parent / "migrations"
        # Apply only additive schema migrations here. 001_cinema_constraints.sql
        # contains a PL/pgSQL DO block and must not be split on semicolons; the
        # exclusion constraint is installed idempotently just below.
        for migration_name in ("002_persistent_product_data.sql", "003_email_verification_and_hall_type.sql", "004_booking_history_archive.sql", "005_demo_card_payments.sql", "006_catalog_screening_links.sql", "007_password_reset.sql", "008_cinematica_hall_directory.sql", "009_ticket_checkin.sql", "010_booking_notifications.sql"):
            migration = migrations / migration_name
            for statement in migration.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    conn.exec_driver_sql(statement)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        conn.execute(text("""DO $$ BEGIN
          ALTER TABLE screenings ADD CONSTRAINT screenings_no_overlap
          EXCLUDE USING gist (auditorium_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
          WHERE (status = 'scheduled');
        EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL; END $$;"""))
    _ensure_initial_admin()
    _ensure_operator_bootstrap()
    created = ensure_current_demo_schedule()
    if created:
        logger.info("Created %s rolling Parda demo screenings", created)
    # Discovery source failures must never prevent the booking API from
    # starting. A protected endpoint can retry the same idempotent sync.
    async def refresh_cinematica_once():
        try:
            await asyncio.to_thread(_refresh_cinematica_directory)
        except Exception:
            logger.exception("Cinematica hall directory refresh failed")
    directory_task = asyncio.create_task(refresh_cinematica_once())
    refresh_task = None
    notification_task = asyncio.create_task(_booking_notification_loop())
    if settings.tmdb_read_token:
        refresh_task = asyncio.create_task(_tmdb_refresh_loop())
    try:
        yield
    finally:
        directory_task.cancel()
        try:
            await directory_task
        except asyncio.CancelledError:
            pass
        if refresh_task:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        notification_task.cancel()
        try:
            await notification_task
        except asyncio.CancelledError:
            pass

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
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(cinematica_router)

@app.get("/health")
def health():
    return {"status": "ok"}
