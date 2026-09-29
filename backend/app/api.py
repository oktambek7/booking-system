from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import Availability, Booking, BookingStatus, Provider, ProviderService, Role, Service, User
from .schemas import (AvailabilityIn, BookingIn, BookingOut, Login, ProviderIn, ProviderOut,
                      ServiceIn, ServiceOut, SlotOut, StatusIn, Token, UserCreate)
from .security import current_user, hash_password, make_token, require_roles, verify_password

router = APIRouter(prefix="/api")
admin = Depends(require_roles(Role.ADMIN))

@router.post("/auth/register", status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    user = User(name=data.name.strip(), email=data.email.lower(), password_hash=hash_password(data.password), role=Role.CUSTOMER)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email is already registered")
    return {"id": user.id, "name": user.name, "email": user.email}

@router.post("/auth/login", response_model=Token)
def login(data: Login, db: Session = Depends(get_db)):
    user = db.scalar(sa.select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash) or not user.active:
        raise HTTPException(401, "Incorrect email or password")
    return Token(access_token=make_token(user))

@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role.value}

@router.get("/services", response_model=list[ServiceOut])
def services(db: Session = Depends(get_db)):
    return db.scalars(sa.select(Service).where(Service.active.is_(True)).order_by(Service.name)).all()

@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(data: ServiceIn, db: Session = Depends(get_db), _: User = admin):
    item = Service(**data.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A service with this name already exists")
    db.refresh(item)
    return item

@router.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(service_id: int, data: ServiceIn, db: Session = Depends(get_db), _: User = admin):
    item = db.get(Service, service_id)
    if not item:
        raise HTTPException(404, "Service not found")
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A service with this name already exists")
    db.refresh(item)
    return item

@router.delete("/services/{service_id}", status_code=204)
def archive_service(service_id: int, db: Session = Depends(get_db), _: User = admin):
    item = db.get(Service, service_id)
    if not item:
        raise HTTPException(404, "Service not found")
    item.active = False
    db.commit()

@router.get("/providers", response_model=list[ProviderOut])
def providers(service_id: int | None = None, db: Session = Depends(get_db)):
    q = sa.select(Provider).where(Provider.active.is_(True)).order_by(Provider.name)
    if service_id:
        q = q.join(ProviderService).where(ProviderService.service_id == service_id)
    return [ProviderOut(id=p.id, name=p.name, bio=p.bio, active=p.active,
                        service_ids=[x.service_id for x in p.services]) for p in db.scalars(q).unique().all()]

@router.post("/providers", response_model=ProviderOut, status_code=201)
def create_provider(data: ProviderIn, db: Session = Depends(get_db), _: User = admin):
    items = db.scalars(sa.select(Service).where(Service.id.in_(data.service_ids), Service.active.is_(True))).all()
    if len({x.id for x in items}) != len(set(data.service_ids)):
        raise HTTPException(422, "One or more service IDs are invalid or inactive")
    p = Provider(name=data.name.strip(), bio=data.bio)
    p.services = [ProviderService(service_id=x) for x in data.service_ids]
    db.add(p); db.commit(); db.refresh(p)
    return ProviderOut(id=p.id, name=p.name, bio=p.bio, active=p.active, service_ids=data.service_ids)

@router.post("/providers/{provider_id}/availability", status_code=201)
def add_availability(provider_id: int, data: AvailabilityIn, db: Session = Depends(get_db), _: User = admin):
    if not db.get(Provider, provider_id):
        raise HTTPException(404, "Provider not found")
    if data.starts_at >= data.ends_at:
        raise HTTPException(422, "Availability end must be after start")
    try:
        ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Unknown timezone")
    row = Availability(provider_id=provider_id, **data.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Availability conflicts with an existing rule")
    return {"id": row.id, **data.model_dump()}

@router.get("/availability", response_model=list[SlotOut])
def availability(service_id: int, provider_id: int, day: date = Query(alias="date"), db: Session = Depends(get_db)):
    service = db.get(Service, service_id)
    provider = db.get(Provider, provider_id)
    if not service or not service.active or not provider or not provider.active:
        raise HTTPException(404, "Active service or provider not found")
    if not db.get(ProviderService, (provider_id, service_id)):
        raise HTTPException(422, "Provider does not offer this service")
    rules = db.scalars(sa.select(Availability).where(Availability.provider_id == provider_id, Availability.weekday == day.weekday())).all()
    now = datetime.now(timezone.utc)
    slots = []
    for rule in rules:
        tz = ZoneInfo(rule.timezone)
        cursor = datetime.combine(day, rule.starts_at, tzinfo=tz)
        finish = datetime.combine(day, rule.ends_at, tzinfo=tz)
        while cursor + timedelta(minutes=service.duration_minutes) <= finish:
            end = cursor + timedelta(minutes=service.duration_minutes)
            start_utc, end_utc = cursor.astimezone(timezone.utc), end.astimezone(timezone.utc)
            if start_utc > now:
                occupied = db.scalar(sa.select(sa.exists().where(
                    Booking.provider_id == provider_id,
                    Booking.status != BookingStatus.CANCELLED,
                    Booking.starts_at < end_utc, Booking.ends_at > start_utc)))
                if not occupied:
                    slots.append(SlotOut(starts_at=cursor, ends_at=end))
            cursor += timedelta(minutes=15)
    return slots

@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(data: BookingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    service, provider = db.get(Service, data.service_id), db.get(Provider, data.provider_id)
    if not service or not service.active or not provider or not provider.active:
        raise HTTPException(404, "Active service or provider not found")
    if not db.get(ProviderService, (provider.id, service.id)):
        raise HTTPException(422, "Provider does not offer this service")
    start = data.starts_at
    if start.tzinfo is None or start.utcoffset() is None:
        raise HTTPException(422, "starts_at must include a timezone offset")
    start = start.astimezone(timezone.utc)
    end = start + timedelta(minutes=service.duration_minutes)
    if start <= datetime.now(timezone.utc):
        raise HTTPException(422, "Booking must be in the future")
    local = start.astimezone(ZoneInfo("UTC"))
    # Availability matching is evaluated in each rule's own timezone.
    rules = db.scalars(sa.select(Availability).where(Availability.provider_id == provider.id)).all()
    if not any(start.astimezone(ZoneInfo(r.timezone)).weekday() == r.weekday and
               datetime.combine(start.astimezone(ZoneInfo(r.timezone)).date(), r.starts_at, tzinfo=ZoneInfo(r.timezone)) <= start.astimezone(ZoneInfo(r.timezone)) and
               start.astimezone(ZoneInfo(r.timezone)) + timedelta(minutes=service.duration_minutes) <= datetime.combine(start.astimezone(ZoneInfo(r.timezone)).date(), r.ends_at, tzinfo=ZoneInfo(r.timezone)) for r in rules):
        raise HTTPException(422, "Requested time is outside provider availability")
    item = Booking(customer_id=user.id, provider_id=provider.id, service_id=service.id,
                   starts_at=start, ends_at=end, price_at_booking=service.price, status=BookingStatus.PENDING)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "exclusion" in str(exc).lower() or "bookings_no_overlap" in str(exc).lower():
            raise HTTPException(409, "This time was just booked. Please choose another slot")
        raise HTTPException(409, "Booking conflicts with an existing record")
    db.refresh(item)
    return item

@router.get("/bookings", response_model=list[BookingOut])
def booking_history(db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = sa.select(Booking).order_by(Booking.starts_at.desc())
    if user.role == Role.CUSTOMER:
        q = q.where(Booking.customer_id == user.id)
    elif user.role == Role.PROVIDER:
        p = db.scalar(sa.select(Provider).where(Provider.user_id == user.id))
        q = q.where(Booking.provider_id == (p.id if p else -1))
    return db.scalars(q).all()

@router.patch("/bookings/{booking_id}/status", response_model=BookingOut)
def update_booking_status(booking_id: int, data: StatusIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(Booking, booking_id)
    if not item:
        raise HTTPException(404, "Booking not found")
    if user.role == Role.CUSTOMER:
        if item.customer_id != user.id or data.status != BookingStatus.CANCELLED:
            raise HTTPException(403, "Customers may only cancel their own booking")
    elif user.role == Role.PROVIDER:
        p = db.scalar(sa.select(Provider).where(Provider.user_id == user.id))
        if not p or item.provider_id != p.id or data.status not in (BookingStatus.CONFIRMED, BookingStatus.CANCELLED, BookingStatus.COMPLETED):
            raise HTTPException(403, "Not permitted to make this status change")
    allowed = {
        BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
        BookingStatus.CONFIRMED: {BookingStatus.CANCELLED, BookingStatus.COMPLETED},
        BookingStatus.CANCELLED: set(), BookingStatus.COMPLETED: set(),
    }
    if data.status not in allowed[item.status]:
        raise HTTPException(422, f"Cannot change {item.status.value} to {data.status.value}")
    item.status = data.status
    db.commit(); db.refresh(item)
    return item
