"""Durable transactional email scheduling for confirmed cinema tickets."""

from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from . import telegram
from .config import settings
from .database import SessionLocal
from .mail import (EmailDeliveryError, send_booking_confirmation_email, send_refund_email, send_screening_reminder_email,
                   send_waitlist_available_email, send_saved_movie_showtime_email)
from .models import (Booking, BookingNotification, BookingSeat, BookingStatus, Refund, Seat,
                     WaitlistEntry, WaitlistNotification, MovieWatchlist, MovieWatchlistNotification, Screening)

logger = logging.getLogger(__name__)

CONFIRMATION = "confirmation"
REMINDER_24H = "reminder_24h"
REMINDER_2H = "reminder_2h"
REFUND = "refund"


def schedule_booking_notifications(db, booking: Booking, *, include_confirmation: bool = True,
                                   now: datetime | None = None) -> None:
    """Queue messages once; the unique booking/event constraint is the final guard."""
    now = now or datetime.now(timezone.utc)
    events: list[tuple[str, datetime]] = []
    if include_confirmation:
        events.append((CONFIRMATION, now))
    for event_type, offset in ((REMINDER_24H, timedelta(hours=24)), (REMINDER_2H, timedelta(hours=2))):
        due_at = booking.screening.starts_at - offset
        if due_at > now:
            events.append((event_type, due_at))
    existing = set(db.scalars(sa.select(BookingNotification.event_type).where(
        BookingNotification.booking_id == booking.id)).all())
    for event_type, due_at in events:
        if event_type not in existing:
            db.add(BookingNotification(booking_id=booking.id, event_type=event_type, due_at=due_at))


def schedule_missing_reminders() -> None:
    """Backfill reminders after a deploy without sending historical confirmations."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        bookings = db.scalars(sa.select(Booking).where(Booking.status == BookingStatus.CONFIRMED)).all()
        for booking in bookings:
            if booking.screening.starts_at > now:
                schedule_booking_notifications(db, booking, include_confirmation=False, now=now)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()


def _details(booking: Booking) -> dict[str, str]:
    starts_at = booking.screening.starts_at.astimezone(ZoneInfo(settings.business_timezone))
    return {
        "movie": booking.screening.movie.title,
        "cinema": f"{booking.screening.auditorium.cinema_name} · {booking.screening.auditorium.name}",
        "starts_at": starts_at.strftime("%d %b %Y, %H:%M"),
        "seats": ", ".join(f"{item.seat.row_label}{item.seat.seat_number}" for item in booking.seat_assignments),
        "ticket_code": booking.ticket_code or str(booking.id),
    }


def _booking_message(event: str, booking: Booking, details: dict[str, str]) -> str:
    where = f"Movie: {details['movie']}\nCinema: {details['cinema']}\nTime: {details['starts_at']}\nSeats: {details['seats']}"
    if event == CONFIRMATION:
        return f"Phantora Cinema: your ticket is confirmed.\n{where}\nTicket code: {details['ticket_code']}\nPaid: {booking.total_price:,.0f} UZS"
    if event == REFUND:
        return (f"Phantora Cinema: your ticket was cancelled and {booking.refund_percent or 0}% was refunded "
                f"({booking.refund_amount:,.0f} UZS).\n{where}")
    when = "in about 24 hours" if event == REMINDER_24H else "in about 2 hours"
    return f"Phantora Cinema: your screening starts {when}.\n{where}\nTicket code: {details['ticket_code']}"


def _claim(db, model, notice_id: int):
    """Lock one notification for this worker. Returns None if another worker already holds it."""
    return db.scalar(sa.select(model).where(model.id == notice_id).with_for_update(skip_locked=True))


def _fail(notice, now: datetime, reason: str, label: str) -> None:
    """Schedule a retry, or abandon the notification once it has failed too often."""
    notice.attempts += 1
    if notice.attempts >= settings.notification_max_attempts:
        notice.sent_at = now
        notice.last_error = f"Gave up after {notice.attempts} attempts: {reason}"[:300]
        logger.error("Phantora %s abandoned after %s attempts: id=%s", label, notice.attempts, notice.id)
    else:
        notice.last_error = reason[:300]
        notice.due_at = now + timedelta(minutes=settings.notification_retry_minutes)
        logger.warning("Phantora %s retry scheduled: id=%s attempt=%s", label, notice.id, notice.attempts)


def _deliver_batch(model, handler, label: str, limit: int) -> int:
    """Run `handler` for each due notification in its own transaction.

    Committing after every message means a crash can lose track of at most the one email in
    flight, and SKIP LOCKED lets concurrent workers (and the post-payment background task)
    take different messages instead of queueing behind each other.
    """
    now = datetime.now(timezone.utc)
    delivered = 0
    with SessionLocal() as db:
        ids = db.scalars(sa.select(model.id).where(model.sent_at.is_(None), model.due_at <= now)
                         .order_by(model.due_at).limit(limit)).all()
        for notice_id in ids:
            try:
                if handler(db, notice_id, now):
                    delivered += 1
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.exception("Phantora %s failed unexpectedly: id=%s", label, notice_id)
                try:
                    notice = _claim(db, model, notice_id)
                    if notice and not notice.sent_at:
                        _fail(notice, now, f"{type(exc).__name__}: {exc}", label)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Phantora %s failure could not be recorded: id=%s", label, notice_id)
    return delivered


def _deliver_booking_notice(db, notice_id: int, now: datetime) -> bool:
    notice = _claim(db, BookingNotification, notice_id)
    if not notice or notice.sent_at or notice.due_at > now:
        return False
    booking = db.scalar(sa.select(Booking).where(Booking.id == notice.booking_id).with_for_update())
    wanted = BookingStatus.CANCELLED if notice.event_type == REFUND else BookingStatus.CONFIRMED
    if not booking or booking.status != wanted:
        notice.sent_at = now
        notice.last_error = "Skipped because the ticket is no longer confirmed"
        return False
    try:
        details = _details(booking)
        if notice.event_type == CONFIRMATION:
            send_booking_confirmation_email(booking.customer.email, amount=f"{booking.total_price:,.0f} UZS", **details)
        elif notice.event_type == REMINDER_24H:
            send_screening_reminder_email(booking.customer.email, when="in about 24 hours", **details)
        elif notice.event_type == REMINDER_2H:
            send_screening_reminder_email(booking.customer.email, when="in about 2 hours", **details)
        elif notice.event_type == REFUND:
            refund = db.scalar(sa.select(Refund).where(Refund.booking_id == booking.id))
            send_refund_email(booking.customer.email, movie=details["movie"], cinema=details["cinema"],
                              starts_at=details["starts_at"], amount=f"{booking.refund_amount:,.0f} UZS",
                              percent=booking.refund_percent or 0, points_restored=refund.points_restored if refund else 0)
        else:
            notice.sent_at = now
            notice.last_error = "Skipped unknown notification type"
            return False
    except EmailDeliveryError as exc:
        _fail(notice, now, str(exc), "booking notification")
        return False
    telegram.notify_user(db, booking.customer_id, _booking_message(notice.event_type, booking, details))
    notice.sent_at = now
    notice.last_error = None
    return True


def deliver_due_notifications(limit: int = 50) -> int:
    """Send due records and retry transient delivery errors on a short schedule."""
    return _deliver_batch(BookingNotification, _deliver_booking_notice, "booking notification", limit)


def _available_seats_for_waitlist(db, entry: WaitlistEntry, now: datetime) -> int:
    total = db.scalar(sa.select(sa.func.count(Seat.id)).where(
        Seat.auditorium_id == entry.screening.auditorium_id)) or 0
    occupied = db.scalar(sa.select(sa.func.count(BookingSeat.id)).join(Booking).where(
        BookingSeat.screening_id == entry.screening_id,
        BookingSeat.active.is_(True),
        sa.or_(
            Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.COMPLETED)),
            sa.and_(Booking.status == BookingStatus.PENDING, Booking.hold_expires_at > now),
        ),
    )) or 0
    return max(total - occupied, 0)


def queue_waitlist_notifications() -> int:
    """Create one durable alert once a full screening has enough newly free seats."""
    now = datetime.now(timezone.utc)
    queued = 0
    with SessionLocal() as db:
        entries = db.scalars(sa.select(WaitlistEntry).where(
            WaitlistEntry.status == "waiting"
        )).all()
        for entry in entries:
            if entry.screening.starts_at <= now or _available_seats_for_waitlist(db, entry, now) < entry.seat_count:
                continue
            existing = db.scalar(sa.select(WaitlistNotification.id).where(
                WaitlistNotification.waitlist_entry_id == entry.id))
            if existing:
                continue
            db.add(WaitlistNotification(waitlist_entry_id=entry.id, due_at=now))
            entry.status = "notified"
            queued += 1
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return queued


def _deliver_waitlist_notice(db, notice_id: int, now: datetime) -> bool:
    notice = _claim(db, WaitlistNotification, notice_id)
    if not notice or notice.sent_at or notice.due_at > now:
        return False
    entry = db.scalar(sa.select(WaitlistEntry).where(WaitlistEntry.id == notice.waitlist_entry_id).with_for_update())
    if not entry or entry.screening.status != "scheduled" or entry.screening.starts_at <= now:
        notice.sent_at = now
        notice.last_error = "Skipped because the screening is unavailable"
        return False
    try:
        starts_at = entry.screening.starts_at.astimezone(ZoneInfo(settings.business_timezone))
        send_waitlist_available_email(entry.user.email,
            movie=entry.screening.movie.title,
            cinema=f"{entry.screening.auditorium.cinema_name} · {entry.screening.auditorium.name}",
            starts_at=starts_at.strftime("%d %b %Y, %H:%M"), seat_count=entry.seat_count)
    except EmailDeliveryError as exc:
        _fail(notice, now, str(exc), "waitlist notification")
        return False
    telegram.notify_user(db, entry.user_id, f"Phantora Cinema: seats are available again for {entry.screening.movie.title} at "
                         f"{entry.screening.auditorium.cinema_name}, {starts_at.strftime('%d %b %Y, %H:%M')}. Seats go to whoever books first.")
    notice.sent_at = now
    notice.last_error = None
    return True


def deliver_due_waitlist_notifications(limit: int = 50) -> int:
    """Deliver availability alerts without reserving a seat or overselling a screening."""
    return _deliver_batch(WaitlistNotification, _deliver_waitlist_notice, "waitlist notification", limit)


def queue_saved_movie_notifications() -> int:
    """Queue an email for each saved movie's first future Phantora screening."""
    now = datetime.now(timezone.utc)
    queued = 0
    with SessionLocal() as db:
        watchlists = db.scalars(sa.select(MovieWatchlist).where(
            MovieWatchlist.alert_sent_at.is_(None)
        )).all()
        for watch in watchlists:
            screening = db.scalar(sa.select(Screening).where(
                Screening.movie_id == watch.movie_id,
                Screening.status == "scheduled",
                Screening.starts_at > now,
            ).order_by(Screening.starts_at))
            if not screening:
                continue
            existing = db.scalar(sa.select(MovieWatchlistNotification.id).where(
                MovieWatchlistNotification.watchlist_id == watch.id))
            if existing:
                continue
            db.add(MovieWatchlistNotification(watchlist_id=watch.id, screening_id=screening.id, due_at=now))
            queued += 1
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return queued


def _deliver_saved_movie_notice(db, notice_id: int, now: datetime) -> bool:
    notice = _claim(db, MovieWatchlistNotification, notice_id)
    if not notice or notice.sent_at or notice.due_at > now:
        return False
    watch = db.scalar(sa.select(MovieWatchlist).where(MovieWatchlist.id == notice.watchlist_id).with_for_update())
    screening = db.get(Screening, notice.screening_id)
    if not watch or not screening or screening.status != "scheduled" or screening.starts_at <= now:
        notice.sent_at = now
        notice.last_error = "Skipped because no future screening remains"
        return False
    try:
        starts_at = screening.starts_at.astimezone(ZoneInfo(settings.business_timezone))
        send_saved_movie_showtime_email(watch.user.email,
            movie=watch.movie.title,
            cinema=f"{screening.auditorium.cinema_name} · {screening.auditorium.name}",
            starts_at=starts_at.strftime("%d %b %Y, %H:%M"))
    except EmailDeliveryError as exc:
        _fail(notice, now, str(exc), "saved-movie notification")
        return False
    telegram.notify_user(db, watch.user_id, f"Phantora Cinema: {watch.movie.title} now has a showtime at "
                         f"{screening.auditorium.cinema_name}, {starts_at.strftime('%d %b %Y, %H:%M')}.")
    watch.alert_sent_at = now
    notice.sent_at = now
    notice.last_error = None
    return True


def deliver_due_saved_movie_notifications(limit: int = 50) -> int:
    return _deliver_batch(MovieWatchlistNotification, _deliver_saved_movie_notice, "saved-movie notification", limit)
