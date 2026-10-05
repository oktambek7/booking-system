from datetime import date, datetime, time, timedelta, timezone
from math import asin, ceil, cos, radians, sin, sqrt
from secrets import choice, token_urlsafe
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlalchemy as sa
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from .database import get_db
from .models import (Auditorium, Booking, BookingSeat, BookingStatus, EmailOtpChallenge, Movie,
                     PasswordResetChallenge, Payment, PaymentEmailChallenge, Role, Screening, Seat, User)
from .schemas import (AuditoriumIn, AuditoriumOut, AuditoriumUpdate, NearbyAuditoriumOut, BookingIn, BookingOut, BookingStatusIn,
                      CatalogSyncOut, CinemaDirectorySyncOut, EmailChallengeOut, EmailCodeVerify, EmailResend, Login, MovieIn, MovieOut, OtpVerifyIn, PasswordResetConfirm, PasswordResetRequest, PaymentStartIn,
                      PaymentStartOut, PaymentVerifyOut, ScreeningIn, ScreeningOut,
                      ScreeningSeatsOut, SeatOut, Token, UserCreate, OperatorBookingOut,
                      OperatorDashboardOut, OperatorMetricsOut, OperatorScreeningOut,
                      TicketCheckInIn, TicketCheckInOut)
from .security import current_user, hash_password, make_token, require_roles, verify_password
from .config import settings
from .otp import code_hash, code_matches, new_code
from .tmdb import TMDBUnavailable, sync_catalog
from .cinematica import sync_active_cinematica_halls
from .mail import (EmailDeliveryError, email_code_hash, email_code_matches, send_email_code,
                   send_password_reset_email, send_payment_verification_email)
from .notifications import deliver_due_notifications, schedule_booking_notifications

router = APIRouter(prefix="/api")
admin = Depends(require_roles(Role.ADMIN))
ACTIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
HOLD_MINUTES = 10
PAYMENT_CODE_MINUTES = 5
PAYMENT_CODE_MAX_ATTEMPTS = 5
PAYMENT_RESEND_LIMIT = 3
EMAIL_RESEND_COOLDOWN_SECONDS = 120
PASSWORD_RESET_CODE_MINUTES = 10
PASSWORD_RESET_MAX_ATTEMPTS = 5
PASSWORD_RESET_REQUEST_LIMIT = 3
def _resend_available_at(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + timedelta(seconds=EMAIL_RESEND_COOLDOWN_SECONDS)

def _enforce_resend_cooldown(created_at: datetime | None, label: str) -> None:
    if not created_at:
        return
    available_at = _resend_available_at(created_at)
    remaining = max(0, int((available_at - datetime.now(timezone.utc)).total_seconds() + 0.999))
    if remaining:
        raise HTTPException(429, f"Wait {remaining} seconds before requesting another {label} code")

def _expire_holds(db: Session):
    now = datetime.now(timezone.utc)
    db.execute(update(Booking).where(Booking.status == BookingStatus.PENDING,
                                    Booking.hold_expires_at <= now).values(status=BookingStatus.CANCELLED))
    db.execute(update(BookingSeat).where(BookingSeat.active.is_(True), BookingSeat.booking_id.in_(
        sa.select(Booking.id).where(Booking.status == BookingStatus.CANCELLED))).values(active=False))

def _screening_out(db: Session, screening: Screening) -> ScreeningOut:
    _expire_holds(db)
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

def _auditorium_out(auditorium: Auditorium) -> AuditoriumOut:
    return AuditoriumOut(id=auditorium.id, name=auditorium.name, cinema_name=auditorium.cinema_name,
        city=auditorium.city, address=auditorium.address, timezone=auditorium.timezone,
        formats=auditorium.formats or ["2D"], hall_type=auditorium.hall_type,
        active=auditorium.active,
        seat_count=len(auditorium.seats), source_name=auditorium.source_name,
        external_cinema_id=auditorium.external_cinema_id, external_hall_id=auditorium.external_hall_id,
        source_url=auditorium.source_url, latitude=auditorium.latitude, longitude=auditorium.longitude,
        last_synced_at=auditorium.last_synced_at)

def _distance_km(lat: float, lng: float, destination_lat: float, destination_lng: float) -> float:
    """Haversine distance. Only verified, stored hall coordinates reach here."""
    radius = 6371.0088
    latitude_delta = radians(destination_lat - lat)
    longitude_delta = radians(destination_lng - lng)
    a = sin(latitude_delta / 2) ** 2 + cos(radians(lat)) * cos(radians(destination_lat)) * sin(longitude_delta / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 2)

def _booking_out(item: Booking) -> BookingOut:
    now = datetime.now(timezone.utc)
    hold_seconds_remaining = None if not item.hold_expires_at else max(0, ceil((item.hold_expires_at - now).total_seconds()))
    return BookingOut(id=item.id, customer_id=item.customer_id, screening_id=item.screening_id,
        status=item.status, seat_count=item.seat_count, total_price=item.total_price,
        hold_expires_at=item.hold_expires_at, hold_seconds_remaining=hold_seconds_remaining, created_at=item.created_at,
        ends_at=item.screening.ends_at,
        ticket_code=item.ticket_code, checked_in_at=item.checked_in_at,
        movie_title=item.screening.movie.title, starts_at=item.screening.starts_at,
        cinema_name=item.screening.auditorium.cinema_name,
        auditorium_name=item.screening.auditorium.name,
        seats=[f"{x.seat.row_label}{x.seat.seat_number}" for x in item.seat_assignments])

def _operator_booking_out(item: Booking) -> OperatorBookingOut:
    return OperatorBookingOut(**_booking_out(item).model_dump(),
        customer_nickname=item.customer.nickname, customer_email=item.customer.email)

def _new_ticket_code(db: Session) -> str:
    """Generate a short, readable, collision-resistant code for an e-ticket."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(10):
        candidate = f"PRD-{''.join(choice(alphabet) for _ in range(8))}"
        exists = db.scalar(sa.select(sa.exists().where(Booking.ticket_code == candidate)))
        if not exists:
            return candidate
    raise HTTPException(503, "Could not issue a ticket code. Please retry payment verification")

@router.post("/auth/register", status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    nickname=data.nickname.strip().lower()
    email = str(data.email).lower()
    existing = db.scalar(sa.select(User).where(sa.or_(
        User.email == email, sa.func.lower(User.nickname) == nickname
    )))
    if existing:
        if existing.email == email and existing.active and not existing.email_verified:
            latest = db.scalar(sa.select(EmailOtpChallenge).where(EmailOtpChallenge.user_id == existing.id)
                .order_by(EmailOtpChallenge.created_at.desc()))
            now = datetime.now(timezone.utc)
            return EmailChallengeOut(
                email=existing.email,
                expires_at=latest.expires_at if latest and latest.expires_at > now else now + timedelta(minutes=10),
                resend_available_at=_resend_available_at(latest.created_at) if latest else now,
                demo_mode=False,
                demo_code=None,
            )
        if existing.email == email:
            raise HTTPException(409, "This email is already registered. Sign in or reset the password")
        raise HTTPException(409, "This nickname is already in use")
    user = User(name=nickname, nickname=nickname, email=email,
                password_hash=hash_password(data.password), role=Role.CUSTOMER)
    db.add(user)
    try:
        db.flush()
        recent = db.scalar(sa.select(sa.func.count(EmailOtpChallenge.id)).where(
            EmailOtpChallenge.user_id == user.id,
            EmailOtpChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
        if recent >= 3:
            raise HTTPException(429, "Too many verification emails. Try again in 10 minutes")
        code = new_code()
        challenge = EmailOtpChallenge(user_id=user.id, code_hash=email_code_hash(user.id, code),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
        is_demo = send_email_code(user.email, code)
        db.add(challenge)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This email or nickname is already registered")
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return EmailChallengeOut(email=user.email, expires_at=challenge.expires_at,
        resend_available_at=_resend_available_at(), demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/email/resend", response_model=EmailChallengeOut)
def resend_email_code(data: EmailResend, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    user = db.scalar(sa.select(User).where(User.email == email, User.active.is_(True)))
    if not user or user.email_verified:
        raise HTTPException(404, "Account awaiting verification was not found")
    latest = db.scalar(sa.select(EmailOtpChallenge).where(EmailOtpChallenge.user_id == user.id)
        .order_by(EmailOtpChallenge.created_at.desc()))
    _enforce_resend_cooldown(latest.created_at if latest else None, "email verification")
    recent = db.scalar(sa.select(sa.func.count(EmailOtpChallenge.id)).where(
        EmailOtpChallenge.user_id == user.id,
        EmailOtpChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
    if recent >= 3:
        raise HTTPException(429, "Too many verification emails. Try again in 10 minutes")
    code = new_code()
    challenge = EmailOtpChallenge(user_id=user.id, code_hash=email_code_hash(user.id, code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    try:
        is_demo = send_email_code(user.email, code)
        db.add(challenge)
        db.commit()
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return EmailChallengeOut(email=user.email, expires_at=challenge.expires_at,
        resend_available_at=_resend_available_at(), demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/email/verify")
def verify_email(data: EmailCodeVerify, db: Session = Depends(get_db)):
    user = db.scalar(sa.select(User).where(User.email == str(data.email).lower()).with_for_update())
    if not user or not user.active:
        raise HTTPException(404, "Account awaiting verification was not found")
    if user.email_verified:
        return {"access_token": make_token(user), "token_type": "bearer"}
    challenge = db.scalar(sa.select(EmailOtpChallenge).where(
        EmailOtpChallenge.user_id == user.id, EmailOtpChallenge.consumed_at.is_(None)
    ).order_by(EmailOtpChallenge.created_at.desc()).with_for_update())
    now = datetime.now(timezone.utc)
    if not challenge or challenge.expires_at <= now:
        raise HTTPException(410, "Verification code expired. Request another email")
    if challenge.attempts >= 5:
        raise HTTPException(429, "Too many incorrect codes. Request a new email")
    if not email_code_matches(user.id, data.code, challenge.code_hash):
        challenge.attempts += 1
        db.commit()
        raise HTTPException(422, "Incorrect verification code")
    challenge.consumed_at = now
    user.email_verified = True
    db.commit()
    return {"access_token": make_token(user), "token_type": "bearer",
        "user": {"id": user.id, "name": user.nickname, "nickname": user.nickname,
                 "email": user.email, "role": user.role.value}}

@router.post("/auth/login", response_model=Token)
def login(data: Login, db: Session = Depends(get_db)):
    user = db.scalar(sa.select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash) or not user.active:
        raise HTTPException(401, "Email or password is incorrect")
    if not user.email_verified:
        raise HTTPException(403, "Verify your email before signing in")
    return Token(access_token=make_token(user))

@router.post("/auth/password-reset/request", response_model=EmailChallengeOut)
def request_password_reset(data: PasswordResetRequest, db: Session = Depends(get_db)):
    """Start a reset without revealing whether an address owns an account."""
    email = str(data.email).lower()
    now = datetime.now(timezone.utc)
    generic = EmailChallengeOut(email=email, expires_at=now + timedelta(minutes=PASSWORD_RESET_CODE_MINUTES),
                                resend_available_at=_resend_available_at(now), demo_mode=False, demo_code=None)
    # Possession of a reset code proves ownership of the mailbox as well.  Let
    # people who left registration before email verification recover their
    # account instead of leaving them unable to sign in or reset their password.
    user = db.scalar(sa.select(User).where(User.email == email, User.active.is_(True)))
    if not user:
        return generic
    latest = db.scalar(sa.select(PasswordResetChallenge).where(PasswordResetChallenge.user_id == user.id)
        .order_by(PasswordResetChallenge.created_at.desc()))
    _enforce_resend_cooldown(latest.created_at if latest else None, "password reset")
    recent = db.scalar(sa.select(sa.func.count(PasswordResetChallenge.id)).where(
        PasswordResetChallenge.user_id == user.id,
        PasswordResetChallenge.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10))) or 0
    if recent >= PASSWORD_RESET_REQUEST_LIMIT:
        return generic
    code = new_code()
    challenge = PasswordResetChallenge(user_id=user.id, code_hash=email_code_hash(user.id, code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_CODE_MINUTES))
    try:
        is_demo = send_password_reset_email(user.email, code)
        db.add(challenge)
        db.commit()
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    return EmailChallengeOut(email=email, expires_at=challenge.expires_at,
                             resend_available_at=_resend_available_at(), demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/password-reset/confirm")
def confirm_password_reset(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    user = db.scalar(sa.select(User).where(User.email == str(data.email).lower(), User.active.is_(True)).with_for_update())
    if not user:
        raise HTTPException(422, "The code or email is not valid")
    challenge = db.scalar(sa.select(PasswordResetChallenge).where(
        PasswordResetChallenge.user_id == user.id, PasswordResetChallenge.consumed_at.is_(None)
    ).order_by(PasswordResetChallenge.created_at.desc()).with_for_update())
    now = datetime.now(timezone.utc)
    if not challenge or challenge.expires_at <= now:
        raise HTTPException(410, "This reset code has expired. Request a new code")
    if challenge.attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many incorrect codes. Request a new code")
    if not email_code_matches(user.id, data.code, challenge.code_hash):
        challenge.attempts += 1
        db.commit()
        raise HTTPException(422, "The code or email is not valid")
    challenge.consumed_at = now
    user.password_hash = hash_password(data.password)
    user.email_verified = True
    db.commit()
    return {"message": "Password reset complete"}

@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.nickname, "nickname": user.nickname,
            "email": user.email, "role": user.role.value}

@router.get("/movies", response_model=list[MovieOut])
def movies(category: str | None = Query(default=None, pattern=r"^(now_playing|upcoming)$"),
           db: Session = Depends(get_db)):
    q=sa.select(Movie).where(Movie.active.is_(True))
    if category: q=q.where(Movie.catalog_status==category)
    return db.scalars(q.order_by(Movie.release_date, Movie.title)).all()

@router.post("/catalog/sync", response_model=CatalogSyncOut)
def sync_movie_catalog(db: Session = Depends(get_db), _: User = admin):
    try:
        current, upcoming = sync_catalog(db)
    except TMDBUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return CatalogSyncOut(imported_now_playing=current, imported_upcoming=upcoming)

@router.post("/admin/catalog-sync", response_model=CinemaDirectorySyncOut)
def sync_cinematica_catalog(db: Session = Depends(get_db), _: User = admin):
    return sync_active_cinematica_halls(db)

@router.get("/admin/catalog-sync/status")
def catalog_sync_status(db: Session = Depends(get_db), _: User = admin):
    latest = db.scalar(sa.select(sa.func.max(Auditorium.last_synced_at)).where(Auditorium.source_name == "cinematica"))
    halls = db.scalar(sa.select(sa.func.count(Auditorium.id)).where(Auditorium.source_name == "cinematica")) or 0
    return {"source": "cinematica", "halls": halls, "last_synced_at": latest}

@router.get("/admin/cinemas", response_model=list[AuditoriumOut])
def admin_cinemas(db: Session = Depends(get_db), _: User = admin):
    """All halls, including disabled halls, for the operator workspace."""
    rows = db.scalars(sa.select(Auditorium).order_by(Auditorium.cinema_name, Auditorium.name)).all()
    return [_auditorium_out(row) for row in rows]

@router.get("/admin/dashboard", response_model=OperatorDashboardOut)
def operator_dashboard(day: date = Query(alias="date"), db: Session = Depends(get_db), _: User = admin):
    """A date-scoped operator view. All metrics come from Parda's owned data."""
    _expire_holds(db)
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
        base = _screening_out(db, screening)
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

@router.get("/movies/{movie_id}", response_model=MovieOut)
def movie_details(movie_id: int, db: Session = Depends(get_db)):
    movie=db.get(Movie,movie_id)
    if not movie or not movie.active: raise HTTPException(404,"Movie not found")
    return movie

@router.post("/movies", response_model=MovieOut, status_code=201)
def create_movie(data: MovieIn, db: Session = Depends(get_db), _: User = admin):
    movie = Movie(**data.model_dump())
    db.add(movie); db.commit(); db.refresh(movie)
    return movie

@router.patch("/movies/{movie_id}", response_model=MovieOut)
def update_movie(movie_id: int, data: MovieIn, db: Session = Depends(get_db), _: User = admin):
    movie = db.get(Movie, movie_id)
    if not movie: raise HTTPException(404, "Movie not found")
    for key, value in data.model_dump().items(): setattr(movie, key, value)
    db.commit(); db.refresh(movie)
    return movie

@router.delete("/movies/{movie_id}", status_code=204)
def archive_movie(movie_id: int, db: Session = Depends(get_db), _: User = admin):
    movie = db.get(Movie, movie_id)
    if not movie: raise HTTPException(404, "Movie not found")
    movie.active = False; db.commit()

@router.get("/cinemas/nearby", response_model=list[NearbyAuditoriumOut])
def nearby_cinemas(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                   city: str | None = None, db: Session = Depends(get_db)):
    q = sa.select(Auditorium).where(Auditorium.active.is_(True), Auditorium.latitude.is_not(None), Auditorium.longitude.is_not(None))
    if city:
        q = q.where(Auditorium.city.ilike(city.strip()))
    rows = []
    for auditorium in db.scalars(q).all():
        value = _auditorium_out(auditorium).model_dump()
        value["distance_km"] = _distance_km(lat, lng, float(auditorium.latitude), float(auditorium.longitude))
        rows.append(NearbyAuditoriumOut(**value))
    return sorted(rows, key=lambda item: (item.distance_km, item.cinema_name.casefold(), item.name.casefold()))

@router.get("/cinemas", response_model=list[AuditoriumOut])
def cinemas(city: str | None = None, db: Session = Depends(get_db)):
    q = sa.select(Auditorium).where(Auditorium.active.is_(True))
    if city:
        q = q.where(Auditorium.city.ilike(city.strip()))
    return [_auditorium_out(a) for a in db.scalars(q.order_by(Auditorium.cinema_name, Auditorium.name)).all()]

@router.post("/cinemas", response_model=AuditoriumOut, status_code=201)
def create_cinema(data: AuditoriumIn, db: Session = Depends(get_db), _: User = admin):
    try: ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError: raise HTTPException(422, "Unknown timezone")
    auditorium = Auditorium(name=data.name.strip(), cinema_name=data.cinema_name.strip(), city=data.city,
                            address=data.address, timezone=data.timezone, formats=list(dict.fromkeys(data.formats)),
                            hall_type=data.hall_type)
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    auditorium.seats=[Seat(row_label=alphabet[row], seat_number=n,
                            seat_type="premium" if row < 2 else "standard")
                       for row in range(data.row_count) for n in range(1,data.seats_per_row+1)]
    db.add(auditorium); db.commit(); db.refresh(auditorium)
    return _auditorium_out(auditorium)

@router.patch("/cinemas/{auditorium_id}", response_model=AuditoriumOut)
def update_cinema(auditorium_id: int, data: AuditoriumUpdate, db: Session = Depends(get_db), _: User = admin):
    auditorium = db.get(Auditorium, auditorium_id)
    if not auditorium:
        raise HTTPException(404, "Cinema hall not found")
    values = data.model_dump(exclude_unset=True)
    if ("latitude" in values) != ("longitude" in values):
        raise HTTPException(422, "Set latitude and longitude together")
    for key, value in values.items():
        setattr(auditorium, key, list(dict.fromkeys(value)) if key == "formats" and value else value)
    db.commit(); db.refresh(auditorium)
    return _auditorium_out(auditorium)

@router.get("/screenings", response_model=list[ScreeningOut])
def screenings(day: date = Query(alias="date"), movie_id: int | None = None,
               hall_type: str | None = Query(default=None, pattern=r"^(standard|vip)$"),
               city: str | None = None, db: Session = Depends(get_db)):
    _expire_holds(db)
    db.commit()
    rows=[]
    q=sa.select(Screening).join(Movie).join(Auditorium).where(Screening.status=="scheduled", Movie.active.is_(True), Auditorium.active.is_(True))
    if movie_id is not None: q=q.where(Screening.movie_id==movie_id)
    if hall_type is not None: q=q.where(Auditorium.hall_type==hall_type)
    if city: q=q.where(Auditorium.city.ilike(city))
    candidates=db.scalars(q.order_by(Screening.starts_at)).all()
    for screening in candidates:
        tz=ZoneInfo(screening.auditorium.timezone)
        local=screening.starts_at.astimezone(tz)
        if local.date()==day and screening.starts_at>datetime.now(timezone.utc):
            item=_screening_out(db,screening)
            if item.available_seats>0:
                rows.append(item)
    db.commit()
    return rows

@router.post("/screenings", response_model=ScreeningOut, status_code=201)
def create_screening(data: ScreeningIn, db: Session = Depends(get_db), _: User = admin):
    movie, room=db.get(Movie,data.movie_id),db.get(Auditorium,data.auditorium_id)
    if not movie or not movie.active or not room or not room.active:
        raise HTTPException(404,"Active movie or cinema hall not found")
    if not movie.duration_minutes: raise HTTPException(422,"A screening requires a known movie duration")
    if data.format_type not in (room.formats or ["2D"]): raise HTTPException(422,"This hall does not support the selected format")
    if data.starts_at.tzinfo is None or data.starts_at.utcoffset() is None:
        raise HTTPException(422,"Screening time must include a timezone offset")
    start=data.starts_at.astimezone(timezone.utc)
    if start<=datetime.now(timezone.utc): raise HTTPException(422,"Screening must start in the future")
    end=start+timedelta(minutes=movie.duration_minutes)
    clash=db.scalar(sa.select(sa.exists().where(Screening.auditorium_id==room.id,
        Screening.status=="scheduled",Screening.starts_at<end,Screening.ends_at>start)))
    if clash: raise HTTPException(409,"This cinema hall already has a screening at that time")
    item=Screening(movie_id=movie.id,auditorium_id=room.id,starts_at=start,ends_at=end,
                   base_price=data.base_price,premium_surcharge=data.premium_surcharge,format_type=data.format_type)
    db.add(item)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"This cinema hall was just scheduled for that time")
    db.refresh(item)
    return _screening_out(db,item)

@router.get("/screenings/{screening_id}/seats",response_model=ScreeningSeatsOut)
def screening_seats(screening_id:int,db:Session=Depends(get_db)):
    _expire_holds(db)
    screening=db.get(Screening,screening_id)
    if not screening or screening.status!="scheduled": raise HTTPException(404,"Screening not found")
    if screening.starts_at<=datetime.now(timezone.utc): raise HTTPException(410,"This screening has already started")
    occupied=set(db.scalars(sa.select(BookingSeat.seat_id).join(Booking).where(
        BookingSeat.screening_id==screening.id,BookingSeat.active.is_(True),Booking.status.in_(ACTIVE_STATUSES))).all())
    seats=db.scalars(sa.select(Seat).where(Seat.auditorium_id==screening.auditorium_id).order_by(Seat.row_label,Seat.seat_number)).all()
    result=_screening_out(db,screening);db.commit()
    return ScreeningSeatsOut(screening=result,seats=[SeatOut(id=s.id,row_label=s.row_label,
        seat_number=s.seat_number,seat_type=s.seat_type,
        price=screening.base_price+(screening.premium_surcharge if s.seat_type=="premium" else 0),
        available=s.id not in occupied) for s in seats])

@router.post("/bookings",response_model=BookingOut,status_code=201)
def create_booking(data:BookingIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if len(data.seat_ids)!=len(set(data.seat_ids)):
        raise HTTPException(422,"A seat can only be selected once")
    screening=db.get(Screening,data.screening_id)
    if not screening or screening.status!="scheduled": raise HTTPException(404,"Screening not found")
    if screening.starts_at<=datetime.now(timezone.utc): raise HTTPException(410,"This screening has already started")
    _expire_holds(db)
    seats=db.scalars(sa.select(Seat).where(Seat.id.in_(data.seat_ids),Seat.auditorium_id==screening.auditorium_id)
        .order_by(Seat.id).with_for_update()).all()
    if len(seats)!=len(data.seat_ids):
        db.rollback(); raise HTTPException(422,"One or more seats do not belong to this screening's hall")
    taken=set(db.scalars(sa.select(BookingSeat.seat_id).join(Booking).where(
        BookingSeat.screening_id==screening.id,BookingSeat.seat_id.in_(data.seat_ids),
        BookingSeat.active.is_(True),Booking.status.in_(ACTIVE_STATUSES))).all())
    if taken:
        db.rollback(); raise HTTPException(409,"One or more selected seats were just taken. Please choose again")
    booking=Booking(customer_id=user.id,screening_id=screening.id,status=BookingStatus.PENDING,
        seat_count=len(seats),total_price=sum((screening.base_price+(screening.premium_surcharge if s.seat_type=="premium" else 0) for s in seats)),
        hold_expires_at=datetime.now(timezone.utc)+timedelta(minutes=HOLD_MINUTES))
    booking.seat_assignments=[BookingSeat(screening_id=screening.id,seat_id=s.id,active=True) for s in seats]
    db.add(booking)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"A seat was booked at the same time. Please choose again")
    db.refresh(booking)
    return _booking_out(booking)

@router.post("/bookings/{booking_id}/confirm",response_model=BookingOut)
def confirm_booking(booking_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    raise HTTPException(409,"Complete the demo payment email verification step to confirm a booking")

def _owned_pending_booking(booking_id: int, db: Session, user: User, lock: bool = False) -> Booking:
    q=sa.select(Booking).where(Booking.id==booking_id)
    if lock: q=q.with_for_update()
    item=db.scalar(q)
    if not item: raise HTTPException(404,"Booking not found")
    if item.customer_id!=user.id: raise HTTPException(403,"This booking belongs to another customer")
    if item.status!=BookingStatus.PENDING: raise HTTPException(409,"This seat hold is no longer pending")
    if not item.hold_expires_at or item.hold_expires_at<=datetime.now(timezone.utc):
        item.status=BookingStatus.CANCELLED
        for seat in item.seat_assignments: seat.active=False
        db.commit()
        raise HTTPException(410,"Your seat hold expired. Please choose seats again")
    return item

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
        expires_at=expires_at, resend_available_at=_resend_available_at(), demo_mode=demo_mode)

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
    item = _owned_pending_booking(data.booking_id, db, user, lock=True)
    if not user.email_verified:
        raise HTTPException(403, "Verify your account email before paying")
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
    booking = _owned_pending_booking(payment.booking_id, db, user, lock=True)
    if payment.status != "awaiting_verification":
        raise HTTPException(409, "This payment attempt can no longer be verified")
    latest = db.scalar(sa.select(PaymentEmailChallenge).where(PaymentEmailChallenge.payment_id == payment.id)
        .order_by(PaymentEmailChallenge.created_at.desc()))
    _enforce_resend_cooldown(latest.created_at if latest else None, "payment verification")
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
    booking=_owned_pending_booking(payment.booking_id,db,user,lock=True)
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
    payment.status="succeeded_demo"
    booking.status=BookingStatus.CONFIRMED;booking.hold_expires_at=None
    booking.ticket_code = booking.ticket_code or _new_ticket_code(db)
    schedule_booking_notifications(db, booking, now=now)
    db.commit();db.refresh(booking)
    background_tasks.add_task(deliver_due_notifications)
    return PaymentVerifyOut(payment_id=payment.id,reference=payment.reference,status=payment.status,booking=_booking_out(booking))

@router.get("/bookings",response_model=list[BookingOut])
def booking_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    _expire_holds(db)
    q=sa.select(Booking).order_by(Booking.created_at.desc())
    if user.role!=Role.ADMIN: q=q.where(Booking.customer_id==user.id,Booking.archived_by_customer.is_(False))
    items=db.scalars(q).all();result=[_booking_out(x) for x in items];db.commit()
    return result

@router.delete("/bookings/history")
def clear_booking_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if user.role==Role.ADMIN:
        raise HTTPException(403,"Customer history can only be cleared from a customer account")
    _expire_holds(db)
    items=db.scalars(sa.select(Booking).where(Booking.customer_id==user.id,
        Booking.archived_by_customer.is_(False),
        Booking.status.in_((BookingStatus.CANCELLED,BookingStatus.COMPLETED)))).all()
    for item in items:
        item.archived_by_customer=True
    db.commit()
    return {"archived_count":len(items)}

@router.post("/admin/tickets/check-in", response_model=TicketCheckInOut)
def check_in_ticket(data: TicketCheckInIn, db: Session = Depends(get_db), _: User = admin):
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
    db.commit()
    db.refresh(item)
    return TicketCheckInOut(booking=_booking_out(item), checked_in_at=item.checked_in_at)

@router.patch("/bookings/{booking_id}/status",response_model=BookingOut)
def update_booking_status(booking_id:int,data:BookingStatusIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    item=db.get(Booking,booking_id)
    if not item: raise HTTPException(404,"Booking not found")
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
            Payment.status=="succeeded_demo")))
        if not paid: raise HTTPException(409,"Booking requires a verified demo payment before confirmation")
        item.ticket_code = item.ticket_code or _new_ticket_code(db)
    if data.status==BookingStatus.COMPLETED and datetime.now(timezone.utc)<item.screening.ends_at:
        raise HTTPException(422,"A screening can only be marked completed after it ends")
    if data.status==BookingStatus.CANCELLED and item.checked_in_at:
        raise HTTPException(409,"A checked-in ticket cannot be cancelled")
    item.status=data.status
    if data.status==BookingStatus.CANCELLED:
        for assignment in item.seat_assignments: assignment.active=False
        if user.role==Role.CUSTOMER and item.screening.ends_at <= datetime.now(timezone.utc):
            item.archived_by_customer=True
    if data.status!=BookingStatus.PENDING: item.hold_expires_at=None
    db.commit();db.refresh(item)
    return _booking_out(item)
