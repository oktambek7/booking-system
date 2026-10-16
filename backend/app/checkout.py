"""What happens to a booking when its payment succeeds, shared by every checkout, and the hosted-checkout flow.

`finalize_payment` is the single place that turns a paid booking into a confirmed ticket: promotion redemption,
Phantora Points, ticket code, notifications. The demo checkout calls it after the e-mailed code is verified; the
provider checkout calls it from `handle_webhook` once a signed callback proves the money arrived.
"""
import logging
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from secrets import token_urlsafe
from typing import Mapping

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record
from .models import Booking, BookingStatus, Payment, PaymentEvent, Promotion, PromotionRedemption, Refund, User
from .notifications import schedule_booking_notifications
from .payment_providers import PAID, PAID_OR_REFUNDED, PaymentProvider, ProviderError, WebhookEvent
from .services import POINT_EARN_RATE_UZS, calculate_promotion_discount, lock_user, new_ticket_code

logger = logging.getLogger("parda.payments")

class FinalizeError(Exception):
    """The booking cannot be confirmed as priced. `payment_status` is what to record on the payment attempt."""
    def __init__(self, payment_status: str, message: str):
        super().__init__(message)
        self.payment_status, self.message = payment_status, message

def ensure_payable(db: Session, booking: Booking, user: User) -> None:
    """Checks that must hold before any checkout starts. Raises HTTPException."""
    if not user.email_verified:
        raise HTTPException(403, "Verify your account email before paying")
    if booking.promotion_code:
        _, discount = calculate_promotion_discount(db, booking.promotion_code, booking.subtotal_price, lock=True)
        if discount != booking.promotion_discount:
            raise HTTPException(409, "The promotion changed. Reapply it before paying")
    if booking.points_redeemed:
        wallet = lock_user(db, user.id)
        if wallet.reserved_points < booking.points_redeemed or wallet.parda_points < booking.points_redeemed:
            raise HTTPException(409, "Your Phantora Pass balance changed. Reapply your points")
    if db.scalar(sa.select(sa.exists().where(Payment.booking_id == booking.id, Payment.status.in_(PAID)))):
        raise HTTPException(409, "This booking has already been paid")

def finalize_payment(db: Session, payment: Payment, booking: Booking, now: datetime, *, paid_status: str,
                     revalidate: bool) -> None:
    """Confirm `booking` against a payment that succeeded. The caller commits.

    revalidate=True (demo): the promotion and points must still be valid as priced, else FinalizeError.
    revalidate=False (provider): the customer has already paid the price shown at checkout, so that price is
    honoured even if the promotion has since lapsed or hit its limit.
    """
    wallet = lock_user(db, booking.customer_id)
    promotion = None
    if booking.promotion_code:
        if revalidate:
            try:
                promotion, discount = calculate_promotion_discount(db, booking.promotion_code, booking.subtotal_price, lock=True)
            except HTTPException as exc:
                raise FinalizeError("promotion_unavailable", "The promotion is no longer available. Reapply checkout pricing") from exc
            if discount != booking.promotion_discount:
                raise FinalizeError("promotion_unavailable", "The promotion changed. Reapply checkout pricing")
        else:
            promotion = db.scalar(sa.select(Promotion).where(Promotion.code == booking.promotion_code.strip().upper()).with_for_update())
    if revalidate and booking.points_redeemed and (wallet.reserved_points < booking.points_redeemed
                                                   or wallet.parda_points < booking.points_redeemed):
        raise FinalizeError("loyalty_unavailable", "Your Phantora Pass balance changed. Reapply checkout pricing")
    # Everything that can fail has been checked; from here on the booking is confirmed.
    if promotion is not None:
        promotion.usage_count += 1
        db.add(PromotionRedemption(promotion_id=promotion.id, booking_id=booking.id,
            customer_id=booking.customer_id, discount_amount=booking.promotion_discount))
    if booking.points_redeemed:
        wallet.reserved_points = max(0, wallet.reserved_points - booking.points_redeemed)
        wallet.parda_points = max(0, wallet.parda_points - booking.points_redeemed)
    booking.points_earned = int((booking.total_price / Decimal(POINT_EARN_RATE_UZS)).to_integral_value(rounding=ROUND_DOWN))
    wallet.parda_points += booking.points_earned
    payment.status = paid_status
    booking.status = BookingStatus.CONFIRMED
    booking.hold_expires_at = None
    booking.ticket_code = booking.ticket_code or new_ticket_code(db)
    schedule_booking_notifications(db, booking, now=now)

def start_checkout(db: Session, provider: PaymentProvider, booking: Booking, idempotency_key: str | None) -> Payment:
    """Create the payment attempt and the provider's hosted checkout for it. The caller commits."""
    payment = Payment(booking_id=booking.id, reference=token_urlsafe(12), method=provider.name, card_last4="",
                      amount=booking.total_price, status="awaiting_provider", provider=provider.name,
                      idempotency_key=idempotency_key)
    try:
        checkout = provider.create_checkout(payment, booking)
    except ProviderError as exc:
        raise HTTPException(502, "The payment provider is unavailable. Try again in a moment") from exc
    payment.provider_reference = checkout.provider_reference
    db.add(payment)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A payment is already in progress for this booking") from exc
    return payment

def _refund_paid_but_unfulfilled(db: Session, provider: PaymentProvider, payment: Payment, booking: Booking) -> str:
    """Money arrived for a booking that can no longer be confirmed (cancelled or expired). Give it back."""
    payment.status = "paid_unfulfilled"
    record(db, None, "payment.paid_unfulfilled", "payment", payment.id, booking_id=booking.id,
           booking_status=booking.status.value, amount=payment.amount)
    try:
        reference = provider.refund(payment, payment.amount, f"auto-{payment.id}")
    except ProviderError:
        logger.error("payment %s was paid for a %s booking and the automatic refund failed; refund it manually",
                     payment.id, booking.status.value)
        return "paid_unfulfilled"
    payment.status = "refunded"
    db.add(Refund(payment_id=payment.id, booking_id=booking.id, amount=payment.amount, percent=100, status="succeeded",
                  initiated_by="system", provider_reference=reference))
    record(db, None, "payment.auto_refunded", "payment", payment.id, booking_id=booking.id, amount=payment.amount)
    return "refunded_unfulfilled"

def _apply_event(db: Session, provider: PaymentProvider, event: WebhookEvent, payment: Payment, now: datetime) -> str:
    if event.kind == "failed":
        if payment.status == "awaiting_provider":
            payment.status = "failed"
            return "failed"
        return "ignored"
    if payment.status in PAID_OR_REFUNDED or payment.status == "paid_unfulfilled":
        return "already_applied"
    if event.amount is None or event.amount != payment.amount:
        payment.status = "amount_mismatch"
        record(db, None, "payment.amount_mismatch", "payment", payment.id, expected=payment.amount, reported=event.amount)
        logger.error("payment %s: provider reported %s, expected %s", payment.id, event.amount, payment.amount)
        return "amount_mismatch"
    booking = db.scalar(sa.select(Booking).where(Booking.id == payment.booking_id).with_for_update())
    # A pending booking whose hold has just lapsed (not yet swept) still owns its seats, so honour the payment.
    if booking.status != BookingStatus.PENDING:
        return _refund_paid_but_unfulfilled(db, provider, payment, booking)
    finalize_payment(db, payment, booking, now, paid_status="succeeded", revalidate=False)
    return "applied"

def handle_webhook(db: Session, provider: PaymentProvider, headers: Mapping[str, str], body: bytes,
                   now: datetime | None = None) -> str:
    """Authenticate and apply one provider callback; returns what happened. Raises WebhookRejected.

    The event row, the payment lock and every effect share one transaction: a redelivery that races the first
    delivery waits on the payment lock and then collides with the unique (provider, event_id), and a failure
    midway leaves no trace, so the provider's retry starts clean.
    """
    now = now or datetime.now(timezone.utc)
    event = provider.parse_webhook(headers, body, now)
    payment = db.scalar(sa.select(Payment).where(Payment.provider == provider.name,
        Payment.provider_reference == event.provider_reference).with_for_update())
    row = PaymentEvent(provider=provider.name, event_id=event.event_id, payment_id=payment.id if payment else None,
                       kind=event.kind, outcome="pending")
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return "duplicate"
    if payment is None:
        logger.warning("%s webhook %s names an unknown payment", provider.name, event.event_id)
        outcome = "unknown_payment"
    else:
        outcome = _apply_event(db, provider, event, payment, now)
    row.outcome = outcome
    db.commit()
    return outcome
