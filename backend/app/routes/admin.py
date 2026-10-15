from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from .. import ratelimit
from ..database import get_db
from ..models import (AuditLog, Auditorium, Booking, BookingStatus, Promotion, Role, Screening, User)
from ..schemas import (AuditLogPage, AuditoriumOut, CatalogSyncOut, CinemaDirectorySyncOut, OperatorBookingOut,
                      OperatorDashboardOut, OperatorMetricsOut, OperatorScreeningOut,
                      TicketCheckInIn, TicketCheckInOut, PromotionIn, PromotionOut)
from ..security import require_roles
from ..config import settings
from ..tmdb import TMDBUnavailable, sync_catalog
from ..cinematica import sync_active_cinematica_halls
from ..services import ACTIVE_STATUSES, auditorium_out, booking_out, expire_holds, screening_out
from ..audit import record

router = APIRouter()
admin = Depends(require_roles(Role.ADMIN))

def _operator_booking_out(item: Booking) -> OperatorBookingOut:
    return OperatorBookingOut(**booking_out(item).model_dump(),
        customer_nickname=item.customer.nickname, customer_email=item.customer.email)

@router.get("/admin/promotions", response_model=list[PromotionOut])
def list_promotions(db: Session = Depends(get_db), _: User = admin):
    return db.scalars(sa.select(Promotion).order_by(Promotion.created_at.desc())).all()

@router.post("/admin/promotions", response_model=PromotionOut, status_code=201)
def create_promotion(data: PromotionIn, db: Session = Depends(get_db), actor: User = admin):
    if data.ends_at and data.starts_at and data.ends_at <= data.starts_at:
        raise HTTPException(422, "Promotion end time must be after its start time")
    item = Promotion(code=data.code.strip().upper(), label=data.label.strip(), percent_off=data.percent_off,
        min_order_amount=data.min_order_amount, max_discount_amount=data.max_discount_amount,
        usage_limit=data.usage_limit, starts_at=data.starts_at, ends_at=data.ends_at)
    db.add(item)
    try:
        db.flush()
        record(db, actor, "promotion.created", "promotion", item.id, code=item.code, percent_off=item.percent_off,
               usage_limit=item.usage_limit)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A promotion with this code already exists")
    db.refresh(item)
    return item

@router.get("/admin/audit-log", response_model=AuditLogPage)
def audit_log(limit: int = Query(50, ge=1, le=200), before_id: int | None = Query(None, ge=1),
              action: str | None = Query(None, max_length=60), actor_id: int | None = Query(None, ge=1),
              db: Session = Depends(get_db), _: User = admin):
    """Newest first. Pass the previous page's next_before_id as before_id to continue."""
    query = sa.select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if before_id:
        query = query.where(AuditLog.id < before_id)
    if action:
        query = query.where(AuditLog.action == action)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    rows = db.scalars(query).all()
    page = rows[:limit]
    return AuditLogPage(items=page, next_before_id=page[-1].id if len(rows) > limit else None)

@router.get("/admin/diagnostics/client-ip")
def client_ip_diagnostics(request: Request, _: User = admin):
    """Show which proxy header carries the caller's real address, so CLIENT_IP_HEADER can be set correctly.

    Per-address rate limits are only as good as this value: behind a proxy that does not forward
    the customer's address, every customer would share one limit bucket."""
    names = ("x-forwarded-for", "x-real-ip", "x-vercel-forwarded-for", "cf-connecting-ip", "true-client-ip")
    return {"resolved_ip": ratelimit.client_ip(request), "configured_header": settings.client_ip_header or None,
            "socket_peer": request.client.host if request.client else None,
            "headers": {name: request.headers.get(name) for name in names}}

@router.post("/catalog/sync", response_model=CatalogSyncOut)
def sync_movie_catalog(db: Session = Depends(get_db), actor: User = admin):
    try:
        current, upcoming = sync_catalog(db)
    except TMDBUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    record(db, actor, "catalog.tmdb_sync", imported_now_playing=current, imported_upcoming=upcoming)
    db.commit()
    return CatalogSyncOut(imported_now_playing=current, imported_upcoming=upcoming)

@router.post("/admin/catalog-sync", response_model=CinemaDirectorySyncOut)
def sync_cinematica_catalog(db: Session = Depends(get_db), actor: User = admin):
    result = sync_active_cinematica_halls(db)
    record(db, actor, "catalog.cinematica_sync")
    db.commit()
    return result

@router.get("/admin/catalog-sync/status")
def catalog_sync_status(db: Session = Depends(get_db), _: User = admin):
    latest = db.scalar(sa.select(sa.func.max(Auditorium.last_synced_at)).where(Auditorium.source_name == "cinematica"))
    halls = db.scalar(sa.select(sa.func.count(Auditorium.id)).where(Auditorium.source_name == "cinematica")) or 0
    return {"source": "cinematica", "halls": halls, "last_synced_at": latest}

@router.get("/admin/cinemas", response_model=list[AuditoriumOut])
def admin_cinemas(db: Session = Depends(get_db), _: User = admin):
    """All halls, including disabled halls, for the operator workspace."""
    rows = db.scalars(sa.select(Auditorium).order_by(Auditorium.cinema_name, Auditorium.name)).all()
    return [auditorium_out(row) for row in rows]

@router.get("/admin/dashboard", response_model=OperatorDashboardOut)
def operator_dashboard(day: date = Query(alias="date"), db: Session = Depends(get_db), _: User = admin):
    """A date-scoped operator view. All metrics come from Parda's owned data."""
    expire_holds(db)
    try:
        business_zone = ZoneInfo(settings.business_timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(500, "Configured business timezone is invalid")
    local_start = datetime.combine(day, time.min, tzinfo=business_zone)
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    screening_rows = db.scalars(
        sa.select(Screening).where(Screening.starts_at >= utc_start, Screening.starts_at < utc_end)
        .order_by(Screening.starts_at)
    ).all()
    screening_ids = [row.id for row in screening_rows]
    booking_rows = [] if not screening_ids else db.scalars(
        sa.select(Booking).where(Booking.screening_id.in_(screening_ids))
        .order_by(Booking.created_at.desc())
    ).all()
    by_screening: dict[int, list[Booking]] = {screening_id: [] for screening_id in screening_ids}
    for booking in booking_rows:
        by_screening.setdefault(booking.screening_id, []).append(booking)
    now = datetime.now(timezone.utc)
    dashboard_screenings: list[OperatorScreeningOut] = []
    seats_sold = 0
    seats_available = 0
    confirmed_revenue = 0
    for screening in screening_rows:
        base = screening_out(db, screening)
        related = by_screening.get(screening.id, [])
        sold = sum(item.seat_count for item in related if item.status in ACTIVE_STATUSES)
        revenue = sum((item.total_price for item in related if item.status in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)), start=0)
        seats_sold += sold
        seats_available += base.available_seats
        confirmed_revenue += revenue
        dashboard_screenings.append(OperatorScreeningOut(**base.model_dump(), booking_count=len(related),
            seats_sold=sold, confirmed_revenue=revenue))
    metrics = OperatorMetricsOut(date=day, screenings=len(screening_rows),
        upcoming_screenings=sum(1 for row in screening_rows if row.starts_at > now and row.status == "scheduled"),
        bookings=len(booking_rows),
        confirmed_bookings=sum(1 for row in booking_rows if row.status == BookingStatus.CONFIRMED),
        pending_bookings=sum(1 for row in booking_rows if row.status == BookingStatus.PENDING),
        seats_sold=seats_sold, seats_available=seats_available,
        confirmed_revenue=confirmed_revenue)
    db.commit()
    return OperatorDashboardOut(metrics=metrics, screenings=dashboard_screenings,
                                bookings=[_operator_booking_out(item) for item in booking_rows])

@router.post("/admin/tickets/check-in", response_model=TicketCheckInOut)
def check_in_ticket(data: TicketCheckInIn, db: Session = Depends(get_db), actor: User = admin):
    """Admit one paid ticket once, within a bounded screening-entry window."""
    ticket_code = data.ticket_code.strip().upper()
    item = db.scalar(sa.select(Booking).where(Booking.ticket_code == ticket_code).with_for_update())
    if not item:
        raise HTTPException(404, "Ticket code was not found")
    if item.status != BookingStatus.CONFIRMED:
        raise HTTPException(409, "Only confirmed tickets can be checked in")
    if item.checked_in_at:
        raise HTTPException(409, "This ticket was already checked in")
    now = datetime.now(timezone.utc)
    if now < item.screening.starts_at - timedelta(hours=2):
        raise HTTPException(422, "Entry opens two hours before the screening")
    if now > item.screening.ends_at:
        raise HTTPException(410, "This screening has already ended")
    item.checked_in_at = now
    record(db, actor, "ticket.checked_in", "booking", item.id, ticket_code=ticket_code)
    db.commit()
    db.refresh(item)
    return TicketCheckInOut(booking=booking_out(item), checked_in_at=item.checked_in_at)
