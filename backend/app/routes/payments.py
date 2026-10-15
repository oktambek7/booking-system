from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo
import sqlalchemy as sa
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..database import get_db
from ..models import (Booking, BookingStatus, Payment, PaymentEmailChallenge, PromotionRedemption, User)
from ..schemas import (OtpVerifyIn, PaymentStartIn,
                      PaymentStartOut, PaymentVerifyOut)
from ..security import current_user
from ..config import settings
from ..otp import code_hash, code_matches, new_code
from ..mail import (EmailDeliveryError, send_payment_verification_email)
from ..notifications import (deliver_due_notifications, schedule_booking_notifications)
from ..services import (
    POINT_EARN_RATE_UZS, booking_out, calculate_promotion_discount, enforce_resend_cooldown, lock_user,
    new_ticket_code, owned_pending_booking, resend_available_at)

router = APIRouter()

PAYMENT_CODE_MINUTES = 5

PAYMENT_CODE_MAX_ATTEMPTS = 5

PAYMENT_RESEND_LIMIT = 3

def _masked_email(address: str) -> str:
    local, domain = address.split("@", 1)
    return f"{local[:1]}***@{domain}"

def _validate_demo_card(data: PaymentStartIn) -> str:
    """Validate checkout shape without persisting card data or contacting a bank."""
    digits = "".join(char for char in data.card_number if char.isdigit())
    if not 12 <= len(digits) <= 19:
        raise HTTPException(422, "Enter a card number with 12 to 19 digits")
    name = " ".join(data.cardholder_name.split())
    if len(name) < 2 or len(name) > 80 or not all(char.isalpha() or char in " -.'" for char in name):
        raise HTTPException(422, "Enter the cardholder name using letters, spaces, apostrophes, or hyphens")
    try:
        month, year = (int(part.strip()) for part in data.expiry_date.split("/"))
    except ValueError as exc:
        raise HTTPException(422, "Use MM / YY for the expiry date") from exc
    if not 1 <= month <= 12:
        raise HTTPException(422, "Enter an expiry month from 01 to 12")
    current = datetime.now(timezone.utc)
    expiry_year = 2000 + year
    if (expiry_year, month) < (current.year, current.month):
        raise HTTPException(422, "This card expiry date has passed")
    if expiry_year > current.year + 30:
        raise HTTPException(422, "Enter a realistic card expiry date")
    if data.method.value in ("visa", "mastercard"):
        if not data.cvv or not data.cvv.isdigit() or len(data.cvv) not in (3, 4):
            raise HTTPException(422, "Enter a 3 or 4 digit CVV")
    elif data.cvv:
        raise HTTPException(422, "Uzcard and Humo demo cards do not use CVV")
    return digits[-4:]

def _payment_start_out(payment: Payment, email: str, expires_at: datetime, demo_mode: bool) -> PaymentStartOut:
    return PaymentStartOut(payment_id=payment.id, reference=payment.reference, method=payment.method,
        card_last4=payment.card_last4, email_masked=_masked_email(email), amount=payment.amount,
        expires_at=expires_at, resend_available_at=resend_available_at(), demo_mode=demo_mode)

def _send_payment_code(payment: Payment, booking: Booking, user: User, db: Session) -> PaymentStartOut:
    code = new_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=PAYMENT_CODE_MINUTES)
    challenge = PaymentEmailChallenge(payment_id=payment.id, user_id=user.id,
        code_hash=code_hash(payment.id, code), expires_at=expires_at)
    db.add(challenge)
    try:
        demo_mode = send_payment_verification_email(user.email, code,
            movie=booking.screening.movie.title,
            cinema=f"{booking.screening.auditorium.cinema_name} · {booking.screening.auditorium.name}",
            starts_at=booking.screening.starts_at.astimezone(ZoneInfo(settings.business_timezone)).strftime("%d %b %Y, %H:%M"),
            seats=", ".join(f"{seat.seat.row_label}{seat.seat.seat_number}" for seat in booking.seat_assignments),
            amount=f"{booking.total_price:,.0f} UZS")
        db.commit()
        db.refresh(payment)
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return _payment_start_out(payment, user.email, expires_at, demo_mode)

@router.post("/payments/create", response_model=PaymentStartOut, status_code=201)
def start_payment(data: PaymentStartIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    card_last4 = _validate_demo_card(data)
    item = owned_pending_booking(data.booking_id, db, user, lock=True)
    if not user.email_verified:
        raise HTTPException(403, "Verify your account email before paying")
    if item.promotion_code:
        promotion, discount = calculate_promotion_discount(db, item.promotion_code, item.subtotal_price, lock=True)
        if discount != item.promotion_discount:
            raise HTTPException(409, "The promotion changed. Reapply it before paying")
    if item.points_redeemed:
        wallet = lock_user(db, user.id)
        if wallet.reserved_points < item.points_redeemed or wallet.parda_points < item.points_redeemed:
            raise HTTPException(409, "Your Parda Pass balance changed. Reapply your points")
    completed = db.scalar(sa.select(sa.exists().where(Payment.booking_id == item.id,
        Payment.status == "succeeded_demo")))
    if completed:
        raise HTTPException(409, "This booking has already been paid")
    open_payment = db.scalar(sa.select(Payment).where(Payment.booking_id == item.id,
        Payment.status == "awaiting_verification").with_for_update())
    if open_payment:
        raise HTTPException(409, "A payment verification is already in progress. Resend its email code or wait for it to expire")
    recent = db.scalar(sa.select(sa.func.count(PaymentEmailChallenge.id)).where(
        PaymentEmailChallenge.user_id == user.id,
        PaymentEmailChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
    if recent >= PAYMENT_RESEND_LIMIT:
        raise HTTPException(429, "Too many payment verification emails. Try again in 10 minutes")
    payment = Payment(booking_id=item.id, reference=token_urlsafe(12), method=data.method.value,
        card_last4=card_last4, amount=item.total_price, status="awaiting_verification", provider="demo")
    db.add(payment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A payment verification is already in progress")
    return _send_payment_code(payment, item, user, db)

@router.post("/payments/{payment_id}/resend", response_model=PaymentStartOut)
def resend_payment_code(payment_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    payment = db.scalar(sa.select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment:
        raise HTTPException(404, "Payment attempt not found")
    booking = owned_pending_booking(payment.booking_id, db, user, lock=True)
    if payment.status != "awaiting_verification":
        raise HTTPException(409, "This payment attempt can no longer be verified")
    latest = db.scalar(sa.select(PaymentEmailChallenge).where(PaymentEmailChallenge.payment_id == payment.id)
        .order_by(PaymentEmailChallenge.created_at.desc()))
    enforce_resend_cooldown(latest.created_at if latest else None, "payment verification")
    recent = db.scalar(sa.select(sa.func.count(PaymentEmailChallenge.id)).where(
        PaymentEmailChallenge.payment_id == payment.id,
        PaymentEmailChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
    if recent >= PAYMENT_RESEND_LIMIT:
        raise HTTPException(429, "Too many verification emails. Start a new payment attempt later")
    db.execute(update(PaymentEmailChallenge).where(PaymentEmailChallenge.payment_id == payment.id,
        PaymentEmailChallenge.consumed_at.is_(None)).values(consumed_at=datetime.now(timezone.utc)))
    return _send_payment_code(payment, booking, user, db)

@router.post("/payments/{payment_id}/verify",response_model=PaymentVerifyOut)
def verify_payment(payment_id:int,data:OtpVerifyIn,background_tasks:BackgroundTasks,db:Session=Depends(get_db),user:User=Depends(current_user)):
    payment=db.scalar(sa.select(Payment).where(Payment.id==payment_id).with_for_update())
    if not payment: raise HTTPException(404,"Payment attempt not found")
    booking=owned_pending_booking(payment.booking_id,db,user,lock=True)
    challenge=db.scalar(sa.select(PaymentEmailChallenge).where(PaymentEmailChallenge.payment_id==payment.id,
        PaymentEmailChallenge.user_id==user.id,PaymentEmailChallenge.consumed_at.is_(None)).order_by(PaymentEmailChallenge.created_at.desc()).with_for_update())
    now=datetime.now(timezone.utc)
    if not challenge or challenge.expires_at<=now or payment.status!="awaiting_verification":
        payment.status="expired";db.commit();raise HTTPException(410,"Code expired. Start verification again")
    if challenge.attempts>=PAYMENT_CODE_MAX_ATTEMPTS: raise HTTPException(429,"Too many incorrect codes. Start a new verification")
    if not code_matches(payment.id,data.code,challenge.code_hash):
        challenge.attempts+=1
        if challenge.attempts>=PAYMENT_CODE_MAX_ATTEMPTS:
            challenge.consumed_at=now;payment.status="verification_failed"
        db.commit()
        if challenge.attempts>=PAYMENT_CODE_MAX_ATTEMPTS:
            raise HTTPException(429,"Too many incorrect codes. Start a new verification attempt")
        raise HTTPException(422,"Incorrect code. Check the 4 digits and try again")
    challenge.consumed_at=now
    wallet = lock_user(db, user.id)
    if booking.promotion_code:
        try:
            promotion, discount = calculate_promotion_discount(db, booking.promotion_code, booking.subtotal_price, lock=True)
        except HTTPException as exc:
            payment.status = "promotion_unavailable"
            db.commit()
            raise HTTPException(409, "The promotion is no longer available. Reapply checkout pricing") from exc
        if discount != booking.promotion_discount:
            payment.status = "promotion_unavailable"
            db.commit()
            raise HTTPException(409, "The promotion changed. Reapply checkout pricing")
        promotion.usage_count += 1
        db.add(PromotionRedemption(promotion_id=promotion.id, booking_id=booking.id,
            customer_id=user.id, discount_amount=booking.promotion_discount))
    if booking.points_redeemed:
        if wallet.reserved_points < booking.points_redeemed or wallet.parda_points < booking.points_redeemed:
            payment.status = "loyalty_unavailable"
            db.commit()
            raise HTTPException(409, "Your Parda Pass balance changed. Reapply checkout pricing")
        wallet.reserved_points -= booking.points_redeemed
        wallet.parda_points -= booking.points_redeemed
    booking.points_earned = int((booking.total_price / Decimal(POINT_EARN_RATE_UZS)).to_integral_value(rounding=ROUND_DOWN))
    wallet.parda_points += booking.points_earned
    payment.status="succeeded_demo"
    booking.status=BookingStatus.CONFIRMED;booking.hold_expires_at=None
    booking.ticket_code = booking.ticket_code or new_ticket_code(db)
    schedule_booking_notifications(db, booking, now=now)
    db.commit();db.refresh(booking)
    background_tasks.add_task(deliver_due_notifications)
    return PaymentVerifyOut(payment_id=payment.id,reference=payment.reference,status=payment.status,booking=booking_out(booking))
