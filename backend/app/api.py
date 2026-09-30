from datetime import date, datetime, timedelta, timezone
from secrets import token_urlsafe
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlalchemy as sa
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query
from .database import get_db
from .models import (Auditorium, Booking, BookingSeat, BookingStatus, EmailOtpChallenge, Movie, OtpChallenge,
                     Payment, Role, Screening, Seat, User)
from .schemas import (AuditoriumIn, AuditoriumOut, BookingIn, BookingOut, BookingStatusIn,
                      CatalogSyncOut, EmailChallengeOut, EmailCodeVerify, EmailResend, Login, MovieIn, MovieOut, OtpVerifyIn, PaymentStartIn,
                      PaymentStartOut, PaymentVerifyOut, ScreeningIn, ScreeningOut,
                      ScreeningSeatsOut, SeatOut, Token, UserCreate)
from .security import current_user, hash_password, make_token, require_roles, verify_password
from .config import settings
from .otp import SmsDeliveryError, code_hash, code_matches, new_code, send_code
from .tmdb import TMDBUnavailable, sync_catalog
from .mail import EmailDeliveryError, email_code_hash, email_code_matches, send_email_code

router = APIRouter(prefix="/api")
admin = Depends(require_roles(Role.ADMIN))
ACTIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
HOLD_MINUTES = 10

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

def _booking_out(item: Booking) -> BookingOut:
    return BookingOut(id=item.id, customer_id=item.customer_id, screening_id=item.screening_id,
        status=item.status, seat_count=item.seat_count, total_price=item.total_price,
        hold_expires_at=item.hold_expires_at, created_at=item.created_at,
        movie_title=item.screening.movie.title, starts_at=item.screening.starts_at,
        cinema_name=item.screening.auditorium.cinema_name,
        auditorium_name=item.screening.auditorium.name,
        seats=[f"{x.seat.row_label}{x.seat.seat_number}" for x in item.seat_assignments])

@router.post("/auth/register", status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    nickname=data.nickname.strip().lower()
    user = User(name=nickname, nickname=nickname, email=str(data.email).lower(),
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
        demo_mode=is_demo, demo_code=code if is_demo else None)

@router.post("/auth/email/resend", response_model=EmailChallengeOut)
def resend_email_code(data: EmailResend, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    user = db.scalar(sa.select(User).where(User.email == email, User.active.is_(True)))
    if not user or user.email_verified:
        raise HTTPException(404, "Account awaiting verification was not found")
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
        demo_mode=is_demo, demo_code=code if is_demo else None)

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

@router.get("/cinemas", response_model=list[AuditoriumOut])
def cinemas(db: Session = Depends(get_db)):
    return [AuditoriumOut(id=a.id, name=a.name, cinema_name=a.cinema_name, city=a.city,
        address=a.address, timezone=a.timezone, formats=a.formats or ["2D"],
        hall_type=a.hall_type, seat_count=len(a.seats))
        for a in db.scalars(sa.select(Auditorium).where(Auditorium.active.is_(True)).order_by(Auditorium.cinema_name)).all()]

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
    return AuditoriumOut(id=auditorium.id,name=auditorium.name,cinema_name=auditorium.cinema_name,
        city=auditorium.city,address=auditorium.address,timezone=auditorium.timezone,
        formats=auditorium.formats,hall_type=auditorium.hall_type,seat_count=len(auditorium.seats))

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
            rows.append(_screening_out(db,screening))
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
    raise HTTPException(409,"Complete the SMS verification step to confirm a booking")

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

def _payment_start_out(payment: Payment, phone: str, demo_code: str | None) -> PaymentStartOut:
    return PaymentStartOut(payment_id=payment.id,reference=payment.reference,method=payment.method,
        phone_masked=f"+{phone[1:4]} *** *** {phone[-4:]}",amount=payment.amount,
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=5),demo_mode=settings.sms_mode=="mock",demo_code=demo_code)

@router.post("/bookings/{booking_id}/payment",response_model=PaymentStartOut,status_code=201)
def start_payment(booking_id:int,data:PaymentStartIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if settings.app_environment.lower() == "production":
        raise HTTPException(503, "Card checkout is unavailable until a payment provider is connected")
    item=_owned_pending_booking(booking_id,db,user)
    phone=data.phone
    recent=db.scalar(sa.select(sa.func.count(OtpChallenge.id)).where(OtpChallenge.user_id==user.id,
        OtpChallenge.phone==phone,OtpChallenge.created_at>=datetime.now(timezone.utc)-timedelta(minutes=10))) or 0
    if recent>=3: raise HTTPException(429,"Too many verification messages. Try again in 10 minutes")
    open_payment=db.scalar(sa.select(Payment).where(Payment.booking_id==item.id,Payment.status=="awaiting_verification"))
    if open_payment: raise HTTPException(409,"A verification is already in progress. Use resend or wait for it to expire")
    payment=Payment(booking_id=item.id,reference=token_urlsafe(12),method=data.method.value,
                    phone_last4=phone[-4:],amount=item.total_price,status="awaiting_verification",
                    provider="mock" if settings.sms_mode=="mock" else "eskiz")
    db.add(payment);db.flush()
    code=new_code()
    challenge=OtpChallenge(payment_id=payment.id,user_id=user.id,phone=phone,code_hash=code_hash(payment.id,code),
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
    db.add(challenge)
    try:
        is_demo=send_code(phone,code)
        db.commit();db.refresh(payment)
    except SmsDeliveryError as exc:
        db.rollback();raise HTTPException(503,str(exc)) from exc
    except IntegrityError:
        db.rollback();raise HTTPException(409,"A verification is already in progress")
    return _payment_start_out(payment,phone,code if is_demo else None)

@router.post("/payments/{payment_id}/verify",response_model=PaymentVerifyOut)
def verify_payment(payment_id:int,data:OtpVerifyIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    payment=db.scalar(sa.select(Payment).where(Payment.id==payment_id).with_for_update())
    if not payment: raise HTTPException(404,"Payment attempt not found")
    booking=_owned_pending_booking(payment.booking_id,db,user,lock=True)
    challenge=db.scalar(sa.select(OtpChallenge).where(OtpChallenge.payment_id==payment.id,
        OtpChallenge.user_id==user.id,OtpChallenge.consumed_at.is_(None)).order_by(OtpChallenge.created_at.desc()).with_for_update())
    now=datetime.now(timezone.utc)
    if not challenge or challenge.expires_at<=now or payment.status!="awaiting_verification":
        payment.status="expired";db.commit();raise HTTPException(410,"Code expired. Start verification again")
    if challenge.attempts>=5: raise HTTPException(429,"Too many incorrect codes. Start a new verification")
    if not code_matches(payment.id,data.code,challenge.code_hash):
        challenge.attempts+=1
        if challenge.attempts>=5:
            challenge.consumed_at=now;payment.status="verification_failed"
        db.commit()
        if challenge.attempts>=5:
            raise HTTPException(429,"Too many incorrect codes. Start a new verification attempt")
        raise HTTPException(422,"Incorrect code. Check the 4 digits and try again")
    challenge.consumed_at=now
    payment.status="succeeded_demo"
    booking.status=BookingStatus.CONFIRMED;booking.hold_expires_at=None
    user.phone=challenge.phone;user.phone_verified=True
    db.commit();db.refresh(booking)
    return PaymentVerifyOut(payment_id=payment.id,reference=payment.reference,status=payment.status,booking=_booking_out(booking))

@router.get("/bookings",response_model=list[BookingOut])
def booking_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    _expire_holds(db)
    q=sa.select(Booking).order_by(Booking.created_at.desc())
    if user.role!=Role.ADMIN: q=q.where(Booking.customer_id==user.id)
    items=db.scalars(q).all();result=[_booking_out(x) for x in items];db.commit()
    return result

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
        if not paid: raise HTTPException(409,"Booking requires a verified SMS payment attempt before confirmation")
    if data.status==BookingStatus.COMPLETED and datetime.now(timezone.utc)<item.screening.ends_at:
        raise HTTPException(422,"A screening can only be marked completed after it ends")
    if data.status==BookingStatus.CANCELLED and user.role==Role.CUSTOMER and item.screening.starts_at<=datetime.now(timezone.utc):
        raise HTTPException(422,"Bookings can only be cancelled before the screening starts")
    item.status=data.status
    if data.status==BookingStatus.CANCELLED:
        for assignment in item.seat_assignments: assignment.active=False
    if data.status!=BookingStatus.PENDING: item.hold_expires_at=None
    db.commit();db.refresh(item)
    return _booking_out(item)
