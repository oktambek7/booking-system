from datetime import datetime, timedelta, timezone
from math import ceil
from decimal import Decimal, ROUND_DOWN
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..database import get_db
from ..models import (Booking, BookingSeat, BookingStatus, Payment, Role, Screening, Seat, User, WaitlistEntry)
from ..schemas import (CancellationQuoteOut, RefundPolicyStep, BookingIn, BookingOut, BookingStatusIn,
                      BookingPriceIn)
from ..security import current_user
from ..config import settings
from ..notifications import (deliver_due_waitlist_notifications,
                            queue_waitlist_notifications)
from ..services import (
    ACTIVE_STATUSES, POINT_VALUE_UZS, booking_out, calculate_promotion_discount, expire_holds,
    lock_user, new_ticket_code, owned_pending_booking, release_pending_points)
from ..audit import record
from ..payment_providers import OPEN, PAID
from ..refunds import CUSTOMER, OPERATOR, issue_refund, paid_payment, policy, quote_refund

router = APIRouter()

HOLD_MINUTES = 10

def _enforce_hold_limits(db: Session, user_id: int, screening_id: int, new_seats: int) -> None:
    """Stop one customer from tying up many seats with unpaid holds.

    Callers hold the customer's row lock, so concurrent requests are admitted one at a time
    and cannot all pass this check together."""
    now = datetime.now(timezone.utc)
    holds = db.execute(sa.select(Booking.screening_id, Booking.seat_count, Booking.hold_expires_at).where(
        Booking.customer_id == user_id, Booking.status == BookingStatus.PENDING,
        Booking.hold_expires_at > now)).all()
    if len(holds) >= settings.max_pending_holds_per_user:
        minutes = max(1, ceil((min(h.hold_expires_at for h in holds) - now).total_seconds() / 60))
        raise HTTPException(409, f"You already have {len(holds)} seat holds in progress. Pay for or cancel one first, "
                                 f"or wait about {minutes} min for the oldest to expire")
    held_here = sum(h.seat_count for h in holds if h.screening_id == screening_id)
    if held_here + new_seats > settings.max_pending_seats_per_screening:
        raise HTTPException(409, f"You can hold at most {settings.max_pending_seats_per_screening} unpaid seats for one "
                                 f"screening ({held_here} already held). Pay for or cancel a hold first")

def _quote_booking(db: Session, booking: Booking, customer: User, promo_code: str | None, points_to_redeem: int) -> None:
    """Persist a pending quote while reserving, never spending, loyalty points."""
    subtotal = booking.subtotal_price or booking.total_price
    normalized = (promo_code or "").strip().upper() or None
    promotion_discount = Decimal(0)
    if normalized:
        _, promotion_discount = calculate_promotion_discount(db, normalized, subtotal, lock=True)
    available_points = customer.parda_points - customer.reserved_points + booking.points_redeemed
    max_points = int(((subtotal - promotion_discount) / Decimal(2 * POINT_VALUE_UZS)).to_integral_value(rounding=ROUND_DOWN))
    if points_to_redeem > max_points:
        raise HTTPException(422, f"You can use up to {max_points} Parda Points on this booking")
    if points_to_redeem > available_points:
        raise HTTPException(422, "You do not have enough available Parda Points")
    customer.reserved_points = max(0, customer.reserved_points - booking.points_redeemed) + points_to_redeem
    booking.subtotal_price = subtotal
    booking.promotion_code = normalized
    booking.promotion_discount = promotion_discount
    booking.points_redeemed = points_to_redeem
    booking.points_discount_amount = Decimal(points_to_redeem * POINT_VALUE_UZS)
    booking.total_price = max(Decimal(0), subtotal - promotion_discount - booking.points_discount_amount)

@router.post("/bookings",response_model=BookingOut,status_code=201)
def create_booking(data:BookingIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if len(data.seat_ids)!=len(set(data.seat_ids)):
        raise HTTPException(422,"A seat can only be selected once")
    screening=db.get(Screening,data.screening_id)
    if not screening or screening.status!="scheduled": raise HTTPException(404,"Screening not found")
    if screening.starts_at<=datetime.now(timezone.utc): raise HTTPException(410,"This screening has already started")
    expire_holds(db)
    lock_user(db, user.id)   # admit one customer's holds at a time so the limits below cannot be raced
    _enforce_hold_limits(db, user.id, screening.id, len(data.seat_ids))
    seats=db.scalars(sa.select(Seat).where(Seat.id.in_(data.seat_ids),Seat.auditorium_id==screening.auditorium_id)
        .order_by(Seat.id).with_for_update()).all()
    if len(seats)!=len(data.seat_ids):
        db.rollback(); raise HTTPException(422,"One or more seats do not belong to this screening's hall")
    taken=set(db.scalars(sa.select(BookingSeat.seat_id).join(Booking).where(
        BookingSeat.screening_id==screening.id,BookingSeat.seat_id.in_(data.seat_ids),
        BookingSeat.active.is_(True),Booking.status.in_(ACTIVE_STATUSES))).all())
    if taken:
        db.rollback(); raise HTTPException(409,"One or more selected seats were just taken. Please choose again")
    # A user who obtains a seat should no longer receive a stale availability alert.
    db.execute(sa.delete(WaitlistEntry).where(WaitlistEntry.screening_id == screening.id,
                                               WaitlistEntry.user_id == user.id))
    subtotal=sum((screening.base_price+(screening.premium_surcharge if s.seat_type=="premium" else 0) for s in seats))
    booking=Booking(customer_id=user.id,screening_id=screening.id,status=BookingStatus.PENDING,
        seat_count=len(seats),total_price=subtotal,subtotal_price=subtotal,
        hold_expires_at=datetime.now(timezone.utc)+timedelta(minutes=HOLD_MINUTES))
    booking.seat_assignments=[BookingSeat(screening_id=screening.id,seat_id=s.id,active=True) for s in seats]
    db.add(booking)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"A seat was booked at the same time. Please choose again")
    db.refresh(booking)
    return booking_out(booking)

@router.post("/bookings/{booking_id}/pricing", response_model=BookingOut)
def price_booking(booking_id: int, data: BookingPriceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    booking = owned_pending_booking(booking_id, db, user, lock=True)
    open_payment = db.scalar(sa.select(Payment.id).where(Payment.booking_id == booking.id,
        Payment.status.in_(OPEN)))
    if open_payment:
        raise HTTPException(409, "A payment verification is already in progress for this booking")
    customer = lock_user(db, user.id)
    _quote_booking(db, booking, customer, data.promo_code, data.points_to_redeem)
    db.commit()
    db.refresh(booking)
    return booking_out(booking)

@router.post("/bookings/{booking_id}/confirm",response_model=BookingOut)
def confirm_booking(booking_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    raise HTTPException(409,"Complete the demo payment email verification step to confirm a booking")

@router.get("/bookings",response_model=list[BookingOut])
def booking_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    expire_holds(db)
    q=sa.select(Booking).order_by(Booking.created_at.desc())
    if user.role!=Role.ADMIN: q=q.where(Booking.customer_id==user.id,Booking.archived_by_customer.is_(False))
    items=db.scalars(q).all();result=[booking_out(x) for x in items];db.commit()
    return result

@router.delete("/bookings/history")
def clear_booking_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role==Role.ADMIN:
        raise HTTPException(403,"Customer history can only be cleared from a customer account")
    expire_holds(db)
    items=db.scalars(sa.select(Booking).where(Booking.customer_id==user.id,
        Booking.archived_by_customer.is_(False),
        Booking.status.in_((BookingStatus.CANCELLED,BookingStatus.COMPLETED)))).all()
    for item in items:
        item.archived_by_customer=True
    db.commit()
    return {"archived_count":len(items)}

@router.get("/refund-policy", response_model=list[RefundPolicyStep])
def refund_policy():
    """The cancellation policy for paid tickets, as published to customers."""
    return policy()

@router.get("/bookings/{booking_id}/cancellation-quote", response_model=CancellationQuoteOut)
def cancellation_quote(booking_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Preview what cancelling would refund, before the customer confirms."""
    item = db.get(Booking, booking_id)
    if not item or (user.role != Role.ADMIN and item.customer_id != user.id):
        raise HTTPException(404, "Booking not found")
    paid = item.status == BookingStatus.CONFIRMED and paid_payment(db, item.id) is not None
    quote = quote_refund(item, datetime.now(timezone.utc), OPERATOR if user.role == Role.ADMIN else CUSTOMER)
    return CancellationQuoteOut(booking_id=item.id, status=item.status, paid=paid,
        refund_percent=quote.percent if paid else 0, refund_amount=quote.amount if paid else 0,
        points_restored=quote.points_restored if paid else 0, points_clawed_back=quote.points_clawed_back if paid else 0,
        hours_until_start=round(quote.hours_until_start, 2), policy=policy())

@router.patch("/bookings/{booking_id}/status",response_model=BookingOut)
def update_booking_status(booking_id:int,data:BookingStatusIn,background_tasks:BackgroundTasks,db:Session=Depends(get_db),user:User=Depends(current_user)):
    item=db.scalar(sa.select(Booking).where(Booking.id==booking_id).with_for_update())
    if not item: raise HTTPException(404,"Booking not found")
    previous_status=item.status
    if user.role==Role.CUSTOMER:
        if item.customer_id!=user.id or data.status!=BookingStatus.CANCELLED:
            raise HTTPException(403,"You can only cancel your own booking")
    allowed={BookingStatus.PENDING:{BookingStatus.CONFIRMED,BookingStatus.CANCELLED},
             BookingStatus.CONFIRMED:{BookingStatus.CANCELLED,BookingStatus.COMPLETED},
             BookingStatus.CANCELLED:set(),BookingStatus.COMPLETED:set()}
    if data.status not in allowed[item.status]:
        raise HTTPException(422,f"Cannot change {item.status.value} to {data.status.value}")
    if data.status==BookingStatus.CONFIRMED:
        paid=db.scalar(sa.select(sa.exists().where(Payment.booking_id==item.id,
            Payment.status.in_(PAID))))
        if not paid: raise HTTPException(409,"Booking requires a verified payment before confirmation")
        item.ticket_code = item.ticket_code or new_ticket_code(db)
    if data.status==BookingStatus.COMPLETED and datetime.now(timezone.utc)<item.screening.ends_at:
        raise HTTPException(422,"A screening can only be marked completed after it ends")
    if data.status==BookingStatus.CANCELLED and item.checked_in_at:
        raise HTTPException(409,"A checked-in ticket cannot be cancelled")
    item.status=data.status
    if user.role==Role.ADMIN:
        record(db, user, "booking.status_changed", "booking", item.id, from_status=previous_status.value, to_status=data.status.value)
    if data.status==BookingStatus.CANCELLED:
        if previous_status == BookingStatus.PENDING:
            release_pending_points(db, item)
        if previous_status == BookingStatus.CONFIRMED:
            issue_refund(db, item, user, OPERATOR if user.role==Role.ADMIN else CUSTOMER)
        for assignment in item.seat_assignments: assignment.active=False
        if user.role==Role.CUSTOMER and item.screening.ends_at <= datetime.now(timezone.utc):
            item.archived_by_customer=True
    if data.status!=BookingStatus.PENDING: item.hold_expires_at=None
    db.commit();db.refresh(item)
    if data.status == BookingStatus.CANCELLED:
        background_tasks.add_task(queue_waitlist_notifications)
        background_tasks.add_task(deliver_due_waitlist_notifications)
    return booking_out(item)
