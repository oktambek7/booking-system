"""A customer's right to a copy of their data, and to leave.

Export returns everything the system holds about the signed-in customer and nothing about anyone else, and none of
the secrets (password hash, code and token hashes). Deletion anonymizes the account instead of removing the row:
bookings, payments and refunds are financial records that must be kept, so the account becomes a tombstone
(`deleted-user-<id>@deleted.invalid`, no name, avatar or password) while every personal side record is erased.
"""
import secrets
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.orm import Session
from .audit import record
from .models import (AuditLog, Booking, BookingNotification, BookingSeat, BookingStatus, EmailOtpChallenge, Movie,
                     MovieWatchlist, PasswordResetChallenge, Payment, PaymentEmailChallenge, RefreshToken, Refund,
                     Screening, TelegramLink, TelegramLinkToken, User, WaitlistEntry)
from .security import hash_password
from .services import lock_user, release_pending_points

EXPORT_VERSION = 1

def tombstone_email(user_id: int) -> str:
    return f"deleted-user-{user_id}@deleted.invalid"

def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value

def export_account(db: Session, user: User) -> dict:
    bookings = db.scalars(sa.select(Booking).where(Booking.customer_id == user.id).order_by(Booking.id)).all()
    booking_ids = [b.id for b in bookings]
    seats = {}
    for assignment in db.scalars(sa.select(BookingSeat).where(BookingSeat.booking_id.in_(booking_ids))).all() if booking_ids else []:
        seats.setdefault(assignment.booking_id, []).append(f"{assignment.seat.row_label}{assignment.seat.seat_number}")
    payments = db.scalars(sa.select(Payment).where(Payment.booking_id.in_(booking_ids)).order_by(Payment.id)).all() if booking_ids else []
    refunds = db.scalars(sa.select(Refund).where(Refund.booking_id.in_(booking_ids)).order_by(Refund.id)).all() if booking_ids else []
    notices = db.scalars(sa.select(BookingNotification).where(BookingNotification.booking_id.in_(booking_ids))
                         .order_by(BookingNotification.id)).all() if booking_ids else []
    saved = db.execute(sa.select(MovieWatchlist, Movie).join(Movie, MovieWatchlist.movie_id == Movie.id)
                       .where(MovieWatchlist.user_id == user.id)).all()
    waitlist = db.scalars(sa.select(WaitlistEntry).where(WaitlistEntry.user_id == user.id)).all()
    sessions = db.scalars(sa.select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None),
                                                         RefreshToken.rotated_at.is_(None)).order_by(RefreshToken.id)).all()
    audit = db.scalars(sa.select(AuditLog).where(AuditLog.actor_id == user.id).order_by(AuditLog.id)).all()
    linked = db.scalar(sa.select(sa.exists().where(TelegramLink.user_id == user.id, TelegramLink.enabled.is_(True))))
    return {
        "export_version": EXPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account": {"id": user.id, "email": user.email, "nickname": user.nickname, "name": user.name, "role": user.role.value,
                    "email_verified": user.email_verified, "created_at": _iso(user.created_at), "has_profile_picture": bool(user.avatar_data)},
        "loyalty": {"points": user.parda_points, "reserved_points": user.reserved_points},
        "bookings": [{"id": b.id, "status": b.status.value, "movie": b.screening.movie.title,
                      "cinema": f"{b.screening.auditorium.cinema_name} · {b.screening.auditorium.name}",
                      "starts_at": _iso(b.screening.starts_at), "seats": sorted(seats.get(b.id, [])), "seat_count": b.seat_count,
                      "subtotal": str(b.subtotal_price), "promotion_code": b.promotion_code, "promotion_discount": str(b.promotion_discount),
                      "points_redeemed": b.points_redeemed, "points_earned": b.points_earned, "total_price": str(b.total_price),
                      "ticket_code": b.ticket_code, "checked_in_at": _iso(b.checked_in_at), "refund_amount": str(b.refund_amount),
                      "refund_percent": b.refund_percent, "created_at": _iso(b.created_at)} for b in bookings],
        "payments": [{"reference": p.reference, "booking_id": p.booking_id, "method": p.method, "card_last4": p.card_last4,
                      "amount": str(p.amount), "status": p.status, "created_at": _iso(p.created_at)} for p in payments],
        "refunds": [{"booking_id": r.booking_id, "amount": str(r.amount), "percent": r.percent, "points_restored": r.points_restored,
                     "points_clawed_back": r.points_clawed_back, "initiated_by": r.initiated_by, "created_at": _iso(r.created_at)} for r in refunds],
        "notifications": [{"booking_id": n.booking_id, "type": n.event_type, "due_at": _iso(n.due_at), "sent_at": _iso(n.sent_at)} for n in notices],
        "saved_movies": [{"movie": movie.title, "saved_at": _iso(watch.created_at), "alert_sent_at": _iso(watch.alert_sent_at)} for watch, movie in saved],
        "waitlist": [{"screening_id": w.screening_id, "seat_count": w.seat_count, "status": w.status, "created_at": _iso(w.created_at)} for w in waitlist],
        "telegram": {"linked": bool(linked)},
        "active_sessions": [{"signed_in_at": _iso(s.family_created_at), "last_refreshed_at": _iso(s.created_at), "ip": s.ip,
                             "browser": s.user_agent} for s in sessions],
        "activity_log": [{"at": _iso(a.created_at), "action": a.action, "target": f"{a.target_type}:{a.target_id}" if a.target_type else None,
                          "details": a.details, "ip": a.ip} for a in audit],
    }

class DeletionBlocked(Exception):
    """The account cannot be deleted right now; the message says why and what to do."""

def delete_account(db: Session, user: User, password_ok: bool) -> str:
    """Anonymize the account and erase its personal records. Returns the e-mail address it had (for the goodbye message).
    The caller commits and revokes nothing else: sessions and the access token die with the account here."""
    if not password_ok:
        raise PermissionError("Password is incorrect")
    locked = lock_user(db, user.id)
    if locked is None or not locked.active:
        raise DeletionBlocked("This account is already closed")
    if locked.role.value == "admin":
        raise DeletionBlocked("Operator accounts cannot be deleted here. Ask another operator to remove the role first")
    now = datetime.now(timezone.utc)
    upcoming = db.scalar(sa.select(sa.func.count(Booking.id)).join(Screening, Booking.screening_id == Screening.id).where(
        Booking.customer_id == locked.id, Booking.status == BookingStatus.CONFIRMED, Booking.checked_in_at.is_(None),
        Screening.ends_at > now)) or 0
    if upcoming:
        raise DeletionBlocked(f"You have {upcoming} upcoming paid ticket(s). Cancel them (for a refund) or use them, then delete your account")
    for booking in db.scalars(sa.select(Booking).where(Booking.customer_id == locked.id, Booking.status == BookingStatus.PENDING)
                              .with_for_update()).all():
        release_pending_points(db, booking)
        booking.status = BookingStatus.CANCELLED
        booking.hold_expires_at = None
        for assignment in booking.seat_assignments:
            assignment.active = False
    former_email = locked.email
    record(db, locked, "account.deleted", "user", locked.id)
    db.flush()          # autoflush is off: the entry must exist before the anonymising update below
    for model in (RefreshToken, TelegramLink, TelegramLinkToken, MovieWatchlist, WaitlistEntry, EmailOtpChallenge,
                  PasswordResetChallenge, PaymentEmailChallenge):
        db.execute(sa.delete(model).where(model.user_id == locked.id))
    marker = tombstone_email(locked.id)
    db.execute(sa.update(AuditLog).where(AuditLog.actor_id == locked.id).values(actor_email=marker, ip=None))
    locked.email, locked.name, locked.nickname = marker, f"deleted-user-{locked.id}", f"deleted-user-{locked.id}"
    locked.password_hash = hash_password(secrets.token_urlsafe(32))
    locked.avatar_data, locked.phone = None, None
    locked.active, locked.email_verified, locked.phone_verified = False, False, False
    locked.parda_points = locked.reserved_points = 0
    locked.token_version = (locked.token_version or 0) + 1
    return former_email
