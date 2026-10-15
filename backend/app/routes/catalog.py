from datetime import date, datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Query
from ..database import get_db
from ..models import (Auditorium, Booking, BookingSeat, Movie,
                     Role, Screening, Seat, User, WaitlistEntry)
from ..schemas import (AuditoriumIn, AuditoriumOut, AuditoriumUpdate, NearbyAuditoriumOut, MovieIn, MovieOut, ScreeningIn, ScreeningOut,
                      ScreeningSeatsOut, SeatOut, WaitlistIn, WaitlistOut)
from ..security import current_user, require_roles
from ..services import ACTIVE_STATUSES, auditorium_out, expire_holds, screening_out

router = APIRouter()
admin = Depends(require_roles(Role.ADMIN))

def _distance_km(lat: float, lng: float, destination_lat: float, destination_lng: float) -> float:
    """Haversine distance. Only verified, stored hall coordinates reach here."""
    radius = 6371.0088
    latitude_delta = radians(destination_lat - lat)
    longitude_delta = radians(destination_lng - lng)
    a = sin(latitude_delta / 2) ** 2 + cos(radians(lat)) * cos(radians(destination_lat)) * sin(longitude_delta / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 2)

@router.get("/movies", response_model=list[MovieOut])
def movies(category: str | None = Query(default=None, pattern=r"^(now_playing|upcoming)$"),
           db: Session = Depends(get_db)):
    q=sa.select(Movie).where(Movie.active.is_(True))
    if category: q=q.where(Movie.catalog_status==category)
    return db.scalars(q.order_by(Movie.release_date, Movie.title)).all()

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
        value = auditorium_out(auditorium).model_dump()
        value["distance_km"] = _distance_km(lat, lng, float(auditorium.latitude), float(auditorium.longitude))
        rows.append(NearbyAuditoriumOut(**value))
    return sorted(rows, key=lambda item: (item.distance_km, item.cinema_name.casefold(), item.name.casefold()))

@router.get("/cinemas", response_model=list[AuditoriumOut])
def cinemas(city: str | None = None, db: Session = Depends(get_db)):
    q = sa.select(Auditorium).where(Auditorium.active.is_(True))
    if city:
        q = q.where(Auditorium.city.ilike(city.strip()))
    return [auditorium_out(a) for a in db.scalars(q.order_by(Auditorium.cinema_name, Auditorium.name)).all()]

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
    return auditorium_out(auditorium)

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
    return auditorium_out(auditorium)

@router.get("/screenings", response_model=list[ScreeningOut])
def screenings(day: date = Query(alias="date"), movie_id: int | None = None,
               hall_type: str | None = Query(default=None, pattern=r"^(standard|vip)$"),
               city: str | None = None, db: Session = Depends(get_db)):
    expire_holds(db)
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
            item=screening_out(db,screening)
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
    return screening_out(db,item)

@router.get("/screenings/{screening_id}/seats",response_model=ScreeningSeatsOut)
def screening_seats(screening_id:int,db:Session=Depends(get_db)):
    expire_holds(db)
    screening=db.get(Screening,screening_id)
    if not screening or screening.status!="scheduled": raise HTTPException(404,"Screening not found")
    if screening.starts_at<=datetime.now(timezone.utc): raise HTTPException(410,"This screening has already started")
    occupied=set(db.scalars(sa.select(BookingSeat.seat_id).join(Booking).where(
        BookingSeat.screening_id==screening.id,BookingSeat.active.is_(True),Booking.status.in_(ACTIVE_STATUSES))).all())
    seats=db.scalars(sa.select(Seat).where(Seat.auditorium_id==screening.auditorium_id).order_by(Seat.row_label,Seat.seat_number)).all()
    result=screening_out(db,screening);db.commit()
    return ScreeningSeatsOut(screening=result,seats=[SeatOut(id=s.id,row_label=s.row_label,
        seat_number=s.seat_number,seat_type=s.seat_type,
        price=screening.base_price+(screening.premium_surcharge if s.seat_type=="premium" else 0),
        available=s.id not in occupied) for s in seats])

@router.post("/screenings/{screening_id}/waitlist", response_model=WaitlistOut)
def join_waitlist(screening_id: int, data: WaitlistIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Join one screening's waitlist only after it is full; entries are one per customer."""
    expire_holds(db)
    screening = db.get(Screening, screening_id)
    if not screening or screening.status != "scheduled":
        raise HTTPException(404, "Screening not found")
    if screening.starts_at <= datetime.now(timezone.utc):
        raise HTTPException(410, "This screening has already started")
    available = screening_out(db, screening).available_seats
    if available:
        db.commit()
        raise HTTPException(409, "Seats are available now. Choose seats directly instead")
    entry = db.scalar(sa.select(WaitlistEntry).where(
        WaitlistEntry.screening_id == screening.id, WaitlistEntry.user_id == user.id).with_for_update())
    if entry:
        entry.seat_count = data.seat_count
    else:
        entry = WaitlistEntry(screening_id=screening.id, user_id=user.id, seat_count=data.seat_count)
        db.add(entry)
    db.commit()
    db.refresh(entry)
    return WaitlistOut(screening_id=entry.screening_id, seat_count=entry.seat_count,
                       status=entry.status, created_at=entry.created_at)

@router.delete("/screenings/{screening_id}/waitlist")
def leave_waitlist(screening_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    entry = db.scalar(sa.select(WaitlistEntry).where(
        WaitlistEntry.screening_id == screening_id, WaitlistEntry.user_id == user.id).with_for_update())
    if not entry:
        raise HTTPException(404, "Waitlist entry not found")
    db.delete(entry)
    db.commit()
    return {"removed": True}
