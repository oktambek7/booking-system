"""Scheduled background work: notification delivery and catalogue refreshes.

Every job runs under a PostgreSQL advisory lock, so any number of API instances and
workers can run these loops without duplicating work: whoever holds the lock does the
pass, everyone else skips it and tries again next interval. The locks live on a database
connection, so a crashed process releases its lock automatically.
"""
import asyncio
import logging
from contextlib import contextmanager
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .cinematica import sync_active_cinematica_halls
from .config import settings
from .database import SessionLocal, engine as default_engine
from .notifications import (deliver_due_notifications, deliver_due_saved_movie_notifications,
                            deliver_due_waitlist_notifications, queue_saved_movie_notifications,
                            queue_waitlist_notifications, retire_pending_reminders)
from .ratelimit import purge_expired as purge_expired_rate_limits
from .sessions import purge_expired_refresh_tokens
from .tmdb import TMDBUnavailable, sync_catalog

logger = logging.getLogger(__name__)

LOCK_NOTIFICATIONS = 0x70617201
LOCK_CINEMATICA = 0x70617202
LOCK_TMDB = 0x70617203

@contextmanager
def exclusive(key: int, engine: Engine | None = None):
    """Yield True if this caller now holds the cross-process lock `key`, else False."""
    with (engine or default_engine).connect() as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                conn.commit()

def notification_cycle() -> dict | None:
    """One pass of queueing and delivery. Returns counts, or None if another process is running it."""
    with exclusive(LOCK_NOTIFICATIONS) as acquired:
        if not acquired:
            return None
        retire_pending_reminders()
        purge_expired_rate_limits()
        purge_expired_refresh_tokens()
        result = {
            "waitlist_queued": queue_waitlist_notifications(),
            "saved_movie_queued": queue_saved_movie_notifications(),
            "bookings": deliver_due_notifications(),
            "waitlist": deliver_due_waitlist_notifications(),
            "saved_movies": deliver_due_saved_movie_notifications(),
        }
        if any(result.values()):
            logger.info("Customer notifications: %s", result)
        return result

def cinematica_refresh() -> dict | None:
    """Warm the durable public-catalogue cache outside customer requests."""
    with exclusive(LOCK_CINEMATICA) as acquired:
        if not acquired:
            return None
        with SessionLocal() as db:
            result = sync_active_cinematica_halls(db)
        logger.info("Cinematica hall directory refresh complete: %s", result)
        return result

def tmdb_refresh() -> tuple[int, int] | None:
    with exclusive(LOCK_TMDB) as acquired:
        if not acquired:
            return None
        with SessionLocal() as db:
            now_playing, upcoming = sync_catalog(db)
        logger.info("TMDB refresh complete: %s now playing, %s upcoming", now_playing, upcoming)
        return now_playing, upcoming

async def _loop(name: str, job, interval_seconds, tolerated: tuple[type[Exception], ...] = ()) -> None:
    while True:
        try:
            await asyncio.to_thread(job)
        except tolerated:
            logger.exception("%s failed", name)
        except Exception:
            # A failing pass must never stop the loop; discovery and delivery are retried next interval.
            logger.exception("Unexpected %s error", name)
        await asyncio.sleep(interval_seconds())

def start_all() -> list[asyncio.Task]:
    """Start the loops on the running event loop. TMDB only runs when a token is configured."""
    tasks = [
        asyncio.create_task(_loop("Cinematica background cache refresh", cinematica_refresh,
                                  lambda: max(60, settings.cinematica_refresh_interval_seconds))),
        asyncio.create_task(_loop("Booking notification delivery", notification_cycle,
                                  lambda: max(30, settings.notification_poll_seconds))),
    ]
    if settings.tmdb_read_token:
        tasks.append(asyncio.create_task(_loop("TMDB catalog refresh", tmdb_refresh,
                                               lambda: max(1, settings.tmdb_sync_interval_hours) * 3600,
                                               tolerated=(TMDBUnavailable,))))
    return tasks

async def stop_all(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
