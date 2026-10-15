"""Domain helpers shared by several route modules (holds, points, promotions, serializers)."""
from datetime import datetime, timedelta, timezone
from math import ceil
from secrets import choice
from decimal import Decimal, ROUND_DOWN
import sqlalchemy as sa
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import (Auditorium, Booking, BookingSeat, BookingStatus, Promotion, Screening, Seat, User)
from .schemas import (AuditoriumOut, BookingOut, ScreeningOut)

ACTIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)

EMAIL_RESEND_COOLDOWN_SECONDS = 120

POINT_VALUE_UZS = 100

POINT_EARN_RATE_UZS = 1000

def resend_available_at(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + timedelta(seconds=EMAIL_RESEND_COOLDOWN_SECONDS)

def enforce_resend_cooldown(created_at: datetime | None, label: str) -> None:
    if not created_at:
        return
    available_at = resend_available_at(created_at)
    remaining = max(0, int((available_at - datetime.now(timezone.utc)).total_seconds() + 0.999))
    if remaining:
        raise HTTPException(429, f"Wait {remaining} seconds before requesting another {label} code")

def lock_user(db: Session, user_id: int) -> User | None:
    """Row-lock an account and return it with its current balances.

    The signed-in user is already in the session's identity map, and a plain
    `SELECT ... FOR UPDATE` would hand back that object with its stale in-memory
    values, letting two parallel requests spend the same Parda Points. Sessions run
    with autoflush off, so pending edits are flushed first or the refresh would drop them.
    """
    db.flush()
    return db.scalar(sa.select(User).where(User.id == user_id).with_for_update()
                     .execution_options(populate_existing=True))

def release_pending_points(db: Session, booking: Booking) -> None:
    if not booking.points_redeemed:
        return
    customer = lock_user(db, booking.customer_id)
    if customer:
        customer.reserved_points = max(0, customer.reserved_points - booking.points_redeemed)

def expire_holds(db: Session):
    now = datetime.now(timezone.utc)
    expired = db.scalars(sa.select(Booking).where(Booking.status == BookingStatus.PENDING,
        Booking.hold_expires_at <= now).with_for_update()).all()
    for booking in expired:
        release_pending_points(db, booking)
        booking.status = BookingStatus.CANCELLED
        for assignment in booking.seat_assignments:
            assignment.active = False
    if expired:
        # Sessions run with autoflush off: without this the seat/availability queries that follow
        # in the same request still see the expired holds as taken.
        db.flush()

def screening_out(db: Session, screening: Screening) -> ScreeningOut:
    expire_holds(db)
    taken = db.scalar(sa.select(sa.func.count(BookingSeat.id)).join(Booking).where(
        BookingSeat.screening_id == screening.id, BookingSeat.active.is_(True),
        Booking.status.in_(ACTIVE_STATUSES))) or 0
    total = db.scalar(sa.select(sa.func.count(Seat.id)).where(Seat.auditorium_id == screening.auditorium_id)) or 0
    return ScreeningOut(id=screening.id, movie_id=screening.movie_id, auditorium_id=screening.auditorium_id,
        starts_at=screening.starts_at, ends_at=screening.ends_at, base_price=screening.base_price,
        premium_surcharge=screening.premium_surcharge,
        format_type=screening.format_type,
        movie_title=screening.movie.title, duration_minutes=screening.movie.duration_minutes,
        cinema_name=screening.auditorium.cinema_name, auditorium_name=screening.auditorium.name,
        hall_type=screening.auditorium.hall_type,
        city=screening.auditorium.city, timezone=screening.auditorium.timezone,
        available_seats=max(total-taken, 0))

def auditorium_out(auditorium: Auditorium) -> AuditoriumOut:
    return AuditoriumOut(id=auditorium.id, name=auditorium.name, cinema_name=auditorium.cinema_name,
        city=auditorium.city, address=auditorium.address, timezone=auditorium.timezone,
        formats=auditorium.formats or ["2D"], hall_type=auditorium.hall_type,
        active=auditorium.active,
        seat_count=len(auditorium.seats), source_name=auditorium.source_name,
        external_cinema_id=auditorium.external_cinema_id, external_hall_id=auditorium.external_hall_id,
        source_url=auditorium.source_url, latitude=auditorium.latitude, longitude=auditorium.longitude,
        last_synced_at=auditorium.last_synced_at)

def booking_out(item: Booking) -> BookingOut:
    now = datetime.now(timezone.utc)
    hold_seconds_remaining = None if not item.hold_expires_at else max(0, ceil((item.hold_expires_at - now).total_seconds()))
    return BookingOut(id=item.id, customer_id=item.customer_id, screening_id=item.screening_id,
        status=item.status, seat_count=item.seat_count, total_price=item.total_price,
        subtotal_price=item.subtotal_price, promotion_code=item.promotion_code,
        promotion_discount=item.promotion_discount, points_redeemed=item.points_redeemed,
        points_discount_amount=item.points_discount_amount, points_earned=item.points_earned,
        hold_expires_at=item.hold_expires_at, hold_seconds_remaining=hold_seconds_remaining, created_at=item.created_at,
        ends_at=item.screening.ends_at,
        ticket_code=item.ticket_code, checked_in_at=item.checked_in_at,
        movie_title=item.screening.movie.title, starts_at=item.screening.starts_at,
        cinema_name=item.screening.auditorium.cinema_name,
        auditorium_name=item.screening.auditorium.name,
        seats=[f"{x.seat.row_label}{x.seat.seat_number}" for x in item.seat_assignments])

def new_ticket_code(db: Session) -> str:
    """Generate a short, readable, collision-resistant code for an e-ticket."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(10):
        candidate = f"PRD-{''.join(choice(alphabet) for _ in range(8))}"
        exists = db.scalar(sa.select(sa.exists().where(Booking.ticket_code == candidate)))
        if not exists:
            return candidate
    raise HTTPException(503, "Could not issue a ticket code. Please retry payment verification")

def calculate_promotion_discount(db: Session, code: str, subtotal: Decimal, *, lock: bool = False) -> tuple[Promotion, Decimal]:
    normalized = code.strip().upper()
    query = sa.select(Promotion).where(Promotion.code == normalized)
    if lock:
        query = query.with_for_update()
    promotion = db.scalar(query)
    now = datetime.now(timezone.utc)
    if not promotion or not promotion.active:
        raise HTTPException(422, "This promo code is not available")
    if promotion.starts_at and promotion.starts_at > now:
        raise HTTPException(422, "This promo code has not started yet")
    if promotion.ends_at and promotion.ends_at <= now:
        raise HTTPException(422, "This promo code has expired")
    if promotion.usage_limit is not None and promotion.usage_count >= promotion.usage_limit:
        raise HTTPException(422, "This promo code has reached its usage limit")
    if subtotal < promotion.min_order_amount:
        raise HTTPException(422, f"This promo code requires an order of at least {promotion.min_order_amount:,.0f} UZS")
    discount = (subtotal * Decimal(promotion.percent_off) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    if promotion.max_discount_amount is not None:
        discount = min(discount, promotion.max_discount_amount)
    return promotion, discount

def owned_pending_booking(booking_id: int, db: Session, user: User, lock: bool = False) -> Booking:
    q=sa.select(Booking).where(Booking.id==booking_id)
    if lock: q=q.with_for_update()
    item=db.scalar(q)
    if not item: raise HTTPException(404,"Booking not found")
    if item.customer_id!=user.id: raise HTTPException(403,"This booking belongs to another customer")
    if item.status!=BookingStatus.PENDING: raise HTTPException(409,"This seat hold is no longer pending")
    if not item.hold_expires_at or item.hold_expires_at<=datetime.now(timezone.utc):
        release_pending_points(db, item)
        item.status=BookingStatus.CANCELLED
        for seat in item.seat_assignments: seat.active=False
        db.commit()
        raise HTTPException(410,"Your seat hold expired. Please choose seats again")
    return item
