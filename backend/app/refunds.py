"""Cancellation policy and refunds.

A customer who cancels a paid ticket gets back a share of the price that depends on how far away the
screening is (REFUND_FULL_HOURS / REFUND_PARTIAL_HOURS / REFUND_PARTIAL_PERCENT); an operator cancelling a
ticket always refunds in full. The Phantora Points used on the booking are returned in the same proportion and
the points the booking earned are taken back in the same proportion (never below zero).

Refunds are written to a ledger with one row per payment (a unique index makes a second refund impossible),
in the same transaction as the cancellation.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
import sqlalchemy as sa
from sqlalchemy.orm import Session
from .audit import record
from .config import settings
from fastapi import HTTPException
from .models import Booking, BookingNotification, Payment, Refund, User
from .payment_providers import DEMO, PAID, ProviderError, get_provider
from .services import lock_user

REFUND_EVENT = "refund"
CUSTOMER, OPERATOR = "customer", "operator"

@dataclass(frozen=True)
class RefundQuote:
    percent: int
    amount: Decimal
    points_restored: int
    points_clawed_back: int
    hours_until_start: float

def policy() -> list[dict]:
    """The policy as data, strictest last, for display."""
    return [{"hours_before_start": settings.refund_full_hours, "percent": 100},
            {"hours_before_start": settings.refund_partial_hours, "percent": settings.refund_partial_percent},
            {"hours_before_start": 0, "percent": 0}]

def refund_percent(starts_at: datetime, now: datetime, initiated_by: str) -> int:
    if initiated_by == OPERATOR:
        return 100
    hours = (starts_at - now).total_seconds() / 3600
    if hours >= settings.refund_full_hours:
        return 100
    if hours >= settings.refund_partial_hours:
        return settings.refund_partial_percent
    return 0

def _share(value: Decimal | int, percent: int) -> Decimal:
    return (Decimal(value) * percent / 100).quantize(Decimal(1), rounding=ROUND_DOWN)

def quote_refund(booking: Booking, now: datetime, initiated_by: str) -> RefundQuote:
    percent = refund_percent(booking.screening.starts_at, now, initiated_by)
    return RefundQuote(percent=percent, amount=_share(booking.total_price, percent),
                       points_restored=int(_share(booking.points_redeemed, percent)),
                       points_clawed_back=int(_share(booking.points_earned, percent)),
                       hours_until_start=(booking.screening.starts_at - now).total_seconds() / 3600)

def paid_payment(db: Session, booking_id: int) -> Payment | None:
    return db.scalar(sa.select(Payment).where(Payment.booking_id == booking_id, Payment.status.in_(PAID)))

def issue_refund(db: Session, booking: Booking, actor: User, initiated_by: str) -> RefundQuote | None:
    """Refund a booking that is being cancelled after payment. The caller commits. Returns None if nothing was paid."""
    payment = paid_payment(db, booking.id)
    if payment is None:
        return None
    now = datetime.now(timezone.utc)
    quote = quote_refund(booking, now, initiated_by)
    booking.refund_percent = quote.percent
    if quote.percent == 0:
        return quote
    demo = payment.provider == DEMO or payment.provider_reference is None
    provider_reference = None
    if not demo:
        # The money goes back first: if the provider refuses, the caller rolls the whole cancellation back and
        # the customer keeps a valid ticket. The idempotency key makes a retry refund once, not twice.
        provider = get_provider(payment.provider)
        try:
            if provider is None:
                raise ProviderError(f"payments from {payment.provider} cannot be refunded by this server")
            provider_reference = provider.refund(payment, quote.amount, f"refund-{payment.id}")
        except ProviderError as exc:
            raise HTTPException(502, "The payment provider could not process the refund. Nothing was cancelled; try again shortly") from exc
    customer = lock_user(db, booking.customer_id)
    customer.parda_points = max(0, customer.parda_points + quote.points_restored - quote.points_clawed_back)
    booking.refund_amount = quote.amount
    booking.refunded_at = now
    suffix = "_demo" if demo else ""
    payment.status = ("refunded" if quote.percent == 100 else "partially_refunded") + suffix
    db.add(Refund(payment_id=payment.id, booking_id=booking.id, amount=quote.amount, percent=quote.percent,
                  points_restored=quote.points_restored, points_clawed_back=quote.points_clawed_back,
                  status="succeeded" + suffix, initiated_by=initiated_by, provider_reference=provider_reference))
    db.add(BookingNotification(booking_id=booking.id, event_type=REFUND_EVENT, due_at=now))
    record(db, actor, "booking.refunded", "booking", booking.id, amount=quote.amount, percent=quote.percent,
           initiated_by=initiated_by, points_restored=quote.points_restored, points_clawed_back=quote.points_clawed_back)
    return quote
