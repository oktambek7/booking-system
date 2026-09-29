from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlalchemy as sa
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query
from .database import get_db
from .models import (Auditorium, Booking, BookingSeat, BookingStatus, Movie, Role,
                     Screening, Seat, User)
from .schemas import (AuditoriumIn, AuditoriumOut, BookingIn, BookingOut, BookingStatusIn,
                      Login, MovieIn, MovieOut, ScreeningIn, ScreeningOut,
                      ScreeningSeatsOut, SeatOut, Token, UserCreate)
from .security import current_user, hash_password, make_token, require_roles, verify_password

router = APIRouter(prefix="/api")
admin = Depends(require_roles(Role.ADMIN))
ACTIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
HOLD_MINUTES = 10

def _expire_holds(db: Session):
    now = datetime.now(timezone.utc)
    db.execute(update(Booking).where(Booking.status == BookingStatus.PENDING,
                                    Booking.hold_expires_at <= now).values(status=BookingStatus.CANCELLED))
    db.execute(update(BookingSeat).where(BookingSeat.active.is_(True), BookingSeat.booking_id.in_(
        sa.select(Booking.id).where(Booking.status == BookingStatus.CANCELLED))))

def _screening_out(db: Session, screening: Screening) -> ScreeningOut:
    _expire_holds(db)
    taken = db.scalar(sa.select(sa.func.count(BookingSeat.id)).join(Booking).where(
        BookingSeat.screening_id == screening.id, BookingSeat.active.is_(True),
        Booking.status.in_(ACTIVE_STATUSES))) or 0
    total = db.scalar(sa.select(sa.func.count(Seat.id)).where(Seat.auditorium_id == screening.auditorium_id)) or 0
    return ScreeningOut(id=screening.id, movie_id=screening.movie_id, auditorium_id=screening.auditorium_id,
        starts_at=screening.starts_at, ends_at=screening.ends_at, base_price=screening.base_price,
        premium_surcharge=screening.premium_surcharge,
        movie_title=screening.movie.title, duration_minutes=screening.movie.duration_minutes,
        cinema_name=screening.auditorium.cinema_name, auditorium_name=screening.auditorium.name,
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
    user = User(name=data.name.strip(), email=data.email.lower(), password_hash=hash_password(data.password), role=Role.CUSTOMER)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This email is already registered")
    return {"id": user.id, "name": user.name, "email": user.email}

@router.post("/auth/login", response_model=Token)
def login(data: Login, db: Session = Depends(get_db)):
    user = db.scalar(sa.select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash) or not user.active:
        raise HTTPException(401, "Email or password is incorrect")
    return Token(access_token=make_token(user))

@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role.value}

@router.get("/movies", response_model=list[MovieOut])
def movies(db: Session = Depends(get_db)):
    return db.scalars(sa.select(Movie).where(Movie.active.is_(True)).order_by(Movie.title)).all()

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
        address=a.address, timezone=a.timezone, seat_count=len(a.seats))
        for a in db.scalars(sa.select(Auditorium).where(Auditorium.active.is_(True)).order_by(Auditorium.cinema_name)).all()]

@router.post("/cinemas", response_model=AuditoriumOut, status_code=201)
def create_cinema(data: AuditoriumIn, db: Session = Depends(get_db), _: User = admin):
    try: ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError: raise HTTPException(422, "Unknown timezone")
    auditorium = Auditorium(name=data.name.strip(), cinema_name=data.cinema_name.strip(), city=data.city,
                            address=data.address, timezone=data.timezone)
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    auditorium.seats=[Seat(row_label=alphabet[row], seat_number=n,
                            seat_type="premium" if row < 2 else "standard")
                       for row in range(data.row_count) for n in range(1,data.seats_per_row+1)]
    db.add(auditorium); db.commit(); db.refresh(auditorium)
    return AuditoriumOut(id=auditorium.id,name=auditorium.name,cinema_name=auditorium.cinema_name,
        city=auditorium.city,address=auditorium.address,timezone=auditorium.timezone,seat_count=len(auditorium.seats))

@router.get("/screenings", response_model=list[ScreeningOut])
def screenings(day: date = Query(alias="date"), movie_id: int | None = None,
               city: str | None = None, db: Session = Depends(get_db)):
    _expire_holds(db)
    db.commit()
    rows=[]
    q=sa.select(Screening).join(Movie).join(Auditorium).where(Screening.status=="scheduled", Movie.active.is_(True), Auditorium.active.is_(True))
    if movie_id is not None: q=q.where(Screening.movie_id==movie_id)
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
    if data.starts_at.tzinfo is None or data.starts_at.utcoffset() is None:
        raise HTTPException(422,"Screening time must include a timezone offset")
    start=data.starts_at.astimezone(timezone.utc)
    if start<=datetime.now(timezone.utc): raise HTTPException(422,"Screening must start in the future")
    end=start+timedelta(minutes=movie.duration_minutes)
    clash=db.scalar(sa.select(sa.exists().where(Screening.auditorium_id==room.id,
        Screening.status=="scheduled",Screening.starts_at<end,Screening.ends_at>start)))
    if clash: raise HTTPException(409,"This cinema hall already has a screening at that time")
    item=Screening(movie_id=movie.id,auditorium_id=room.id,starts_at=start,ends_at=end,
                   base_price=data.base_price,premium_surcharge=data.premium_surcharge)
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
    _expire_holds(db)
    item=db.get(Booking,booking_id)
    if not item: raise HTTPException(404,"Booking not found")
    if item.customer_id!=user.id and user.role!=Role.ADMIN: raise HTTPException(403,"This booking belongs to another customer")
    if item.status!=BookingStatus.PENDING: raise HTTPException(409,"This seat hold is no longer pending")
    if not item.hold_expires_at or item.hold_expires_at<=datetime.now(timezone.utc):
        raise HTTPException(410,"Your seat hold expired. Please book again")
    item.status=BookingStatus.CONFIRMED;item.hold_expires_at=None
    db.commit();db.refresh(item)
    return _booking_out(item)

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
    item.status=data.status
    if data.status==BookingStatus.CANCELLED:
        for assignment in item.seat_assignments: assignment.active=False
    if data.status!=BookingStatus.PENDING: item.hold_expires_at=None
    db.commit();db.refresh(item)
    return _booking_out(item)
