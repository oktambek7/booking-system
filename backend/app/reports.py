"""CSV reports for operators: a booking list and a money report, by screening date.

Two things matter beyond the numbers. Spreadsheet programs run text that starts with = + - @ as a formula, and
names here (nicknames, film titles) come from customers and imports, so every text cell is neutralised
(OWASP "CSV injection"). And reports are streamed row by row from their own database session, so a big range cannot
exhaust memory; the date range is capped.
"""
import csv
import io
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import sqlalchemy as sa
from .config import settings
from .database import SessionLocal
from .models import Auditorium, Booking, BookingSeat, Movie, Payment, Screening, Seat, User

MAX_RANGE_DAYS = 366
BOM = "﻿"                    # lets Excel read Uzbek and Russian text as UTF-8
PAID_STATUSES = ("succeeded_demo", "refunded_demo", "partially_refunded_demo")
_DANGEROUS_START = ("=", "+", "-", "@", "\t", "\r")

def safe_cell(value) -> str:
    """Text for a CSV cell that a spreadsheet will not treat as a formula."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_DANGEROUS_START) else text

def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The UTC instants covering [start, end] inclusive in the business time zone."""
    zone = ZoneInfo(settings.business_timezone)
    return (datetime.combine(start, time.min, tzinfo=zone).astimezone(timezone.utc),
            datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc))

def validate_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("The end date is before the start date")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ValueError(f"Choose a range of at most {MAX_RANGE_DAYS} days")

def _local(value: datetime | None) -> str:
    return value.astimezone(ZoneInfo(settings.business_timezone)).strftime("%Y-%m-%d %H:%M") if value else ""

def _writer(buffer: io.StringIO):
    return csv.writer(buffer, lineterminator="\r\n")

def _drain(buffer: io.StringIO) -> str:
    chunk = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return chunk

BOOKING_COLUMNS = ["booking_id", "screening_start", "cinema", "hall", "movie", "status", "customer_nickname", "customer_email",
                   "seats", "seat_count", "subtotal_uzs", "promo_code", "promo_discount_uzs", "points_redeemed", "total_uzs",
                   "refund_percent", "refund_uzs", "ticket_code", "checked_in_at", "booked_at"]

def bookings_csv(start: date, end: date) -> Iterator[str]:
    """One row per booking whose screening starts in the range, oldest screening first."""
    begin, finish = day_bounds(start, end)
    seat_list = (sa.select(sa.func.string_agg(Seat.row_label + sa.cast(Seat.seat_number, sa.String), sa.literal(", ")))
                 .select_from(BookingSeat.__table__.join(Seat.__table__, Seat.id == BookingSeat.seat_id))
                 .where(BookingSeat.booking_id == Booking.id).correlate(Booking).scalar_subquery())
    query = (sa.select(Booking, Screening, Movie, Auditorium, User, seat_list.label("seats"))
             .join(Screening, Booking.screening_id == Screening.id).join(Movie, Screening.movie_id == Movie.id)
             .join(Auditorium, Screening.auditorium_id == Auditorium.id).join(User, Booking.customer_id == User.id)
             .where(Screening.starts_at >= begin, Screening.starts_at < finish).order_by(Screening.starts_at, Booking.id))
    buffer = io.StringIO()
    writer = _writer(buffer)
    buffer.write(BOM)
    writer.writerow(BOOKING_COLUMNS)
    yield _drain(buffer)
    with SessionLocal() as db:
        for count, (b, screening, movie, hall, user, seats) in enumerate(db.execute(query).yield_per(500), start=1):
            writer.writerow([b.id, _local(screening.starts_at), safe_cell(hall.cinema_name), safe_cell(hall.name), safe_cell(movie.title),
                             b.status.value, safe_cell(user.nickname), safe_cell(user.email), safe_cell(seats), b.seat_count,
                             b.subtotal_price, safe_cell(b.promotion_code), b.promotion_discount, b.points_redeemed, b.total_price,
                             "" if b.refund_percent is None else b.refund_percent, b.refund_amount, safe_cell(b.ticket_code),
                             _local(b.checked_in_at), _local(b.created_at)])
            if count % 200 == 0:
                yield _drain(buffer)
    yield _drain(buffer)

REVENUE_COLUMNS = ["date", "cinema", "hall", "movie", "paid_tickets", "seats", "paid_uzs", "refunded_uzs", "net_uzs"]

def revenue_csv(start: date, end: date) -> Iterator[str]:
    """Money actually paid, refunded and kept, per screening day, hall and film (cancelled and refunded tickets included)."""
    begin, finish = day_bounds(start, end)
    day = sa.func.date(sa.func.timezone(settings.business_timezone, Screening.starts_at))
    query = (sa.select(day.label("day"), Auditorium.cinema_name, Auditorium.name, Movie.title,
                       sa.func.count(sa.distinct(Booking.id)), sa.func.sum(Booking.seat_count), sa.func.sum(Payment.amount),
                       sa.func.sum(Booking.refund_amount), sa.func.sum(Payment.amount - Booking.refund_amount))
             .select_from(Payment).join(Booking, Payment.booking_id == Booking.id).join(Screening, Booking.screening_id == Screening.id)
             .join(Movie, Screening.movie_id == Movie.id).join(Auditorium, Screening.auditorium_id == Auditorium.id)
             .where(Payment.status.in_(PAID_STATUSES), Screening.starts_at >= begin, Screening.starts_at < finish)
             .group_by(day, Auditorium.cinema_name, Auditorium.name, Movie.title).order_by(day, Auditorium.cinema_name, Auditorium.name, Movie.title))
    buffer = io.StringIO()
    writer = _writer(buffer)
    buffer.write(BOM)
    writer.writerow(REVENUE_COLUMNS)
    with SessionLocal() as db:
        for row in db.execute(query):
            writer.writerow([row[0].isoformat(), safe_cell(row[1]), safe_cell(row[2]), safe_cell(row[3]), row[4], row[5], row[6], row[7], row[8]])
    yield _drain(buffer)
