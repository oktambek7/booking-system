"""Durable transactional email scheduling for confirmed cinema tickets."""

from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from .config import settings
from .database import SessionLocal
from .mail import (EmailDeliveryError, send_booking_confirmation_email, send_screening_reminder_email,
                   send_waitlist_available_email)
from .models import (Booking, BookingNotification, BookingSeat, BookingStatus, Seat,
                     WaitlistEntry, WaitlistNotification)

logger = logging.getLogger(__name__)

CONFIRMATION = "confirmation"
REMINDER_24H = "reminder_24h"
REMINDER_2H = "reminder_2h"


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


def deliver_due_notifications(limit: int = 50) -> int:
    """Send due records and retry transient delivery errors on a short schedule."""
    now = datetime.now(timezone.utc)
    delivered = 0
    with SessionLocal() as db:
        ids = db.scalars(sa.select(BookingNotification.id).where(
            BookingNotification.sent_at.is_(None), BookingNotification.due_at <= now
        ).order_by(BookingNotification.due_at).limit(limit)).all()
        for notice_id in ids:
            notice = db.scalar(sa.select(BookingNotification).where(
                BookingNotification.id == notice_id).with_for_update())
            if not notice or notice.sent_at or notice.due_at > now:
                continue
            booking = db.scalar(sa.select(Booking).where(Booking.id == notice.booking_id).with_for_update())
            if not booking or booking.status != BookingStatus.CONFIRMED:
                notice.sent_at = now
                notice.last_error = "Skipped because the ticket is no longer confirmed"
                continue
            try:
                details = _details(booking)
                if notice.event_type == CONFIRMATION:
                    send_booking_confirmation_email(booking.customer.email, amount=f"{booking.total_price:,.0f} UZS", **details)
                elif notice.event_type == REMINDER_24H:
                    send_screening_reminder_email(booking.customer.email, when="in about 24 hours", **details)
                elif notice.event_type == REMINDER_2H:
                    send_screening_reminder_email(booking.customer.email, when="in about 2 hours", **details)
                else:
                    notice.sent_at = now
                    notice.last_error = "Skipped unknown notification type"
                    continue
                notice.sent_at = now
                notice.last_error = None
                delivered += 1
            except EmailDeliveryError as exc:
                notice.attempts += 1
                notice.last_error = str(exc)[:300]
                notice.due_at = now + timedelta(minutes=settings.notification_retry_minutes)
                logger.warning("Parda notification retry scheduled: booking=%s event=%s", booking.id, notice.event_type)
        db.commit()
    return delivered


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


def deliver_due_waitlist_notifications(limit: int = 50) -> int:
    """Deliver availability alerts without reserving a seat or overselling a screening."""
    now = datetime.now(timezone.utc)
    delivered = 0
    with SessionLocal() as db:
        ids = db.scalars(sa.select(WaitlistNotification.id).where(
            WaitlistNotification.sent_at.is_(None), WaitlistNotification.due_at <= now
        ).order_by(WaitlistNotification.due_at).limit(limit)).all()
        for notice_id in ids:
            notice = db.scalar(sa.select(WaitlistNotification).where(
                WaitlistNotification.id == notice_id).with_for_update())
            if not notice or notice.sent_at or notice.due_at > now:
                continue
            entry = db.scalar(sa.select(WaitlistEntry).where(
                WaitlistEntry.id == notice.waitlist_entry_id).with_for_update())
            if not entry or entry.screening.status != "scheduled" or entry.screening.starts_at <= now:
                notice.sent_at = now
                notice.last_error = "Skipped because the screening is unavailable"
                continue
            try:
                starts_at = entry.screening.starts_at.astimezone(ZoneInfo(settings.business_timezone))
                send_waitlist_available_email(entry.user.email,
                    movie=entry.screening.movie.title,
                    cinema=f"{entry.screening.auditorium.cinema_name} · {entry.screening.auditorium.name}",
                    starts_at=starts_at.strftime("%d %b %Y, %H:%M"), seat_count=entry.seat_count)
                notice.sent_at = now
                notice.last_error = None
                delivered += 1
            except EmailDeliveryError as exc:
                notice.attempts += 1
                notice.last_error = str(exc)[:300]
                notice.due_at = now + timedelta(minutes=settings.notification_retry_minutes)
                logger.warning("Parda waitlist notification retry scheduled: entry=%s", entry.id)
        db.commit()
    return delivered
