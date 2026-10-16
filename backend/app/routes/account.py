from datetime import date
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from ..database import get_db
from ..models import (Auditorium, Booking, Movie,
                     Screening, User, WaitlistEntry, MovieWatchlist, BookingNotification, WaitlistNotification, MovieWatchlistNotification)
from ..schemas import (WatchlistMovieOut, CustomerNotificationOut,
                      LoyaltyOut)
from ..security import current_user
from ..cinematica import _source_movie
from ..services import POINT_EARN_RATE_UZS, POINT_VALUE_UZS

router = APIRouter()

@router.get("/loyalty", response_model=LoyaltyOut)
def loyalty_balance(user: User = Depends(current_user)):
    return LoyaltyOut(points=user.parda_points, reserved_points=user.reserved_points,
        available_points=max(0, user.parda_points - user.reserved_points),
        point_value_uzs=POINT_VALUE_UZS, earn_rate_uzs=POINT_EARN_RATE_UZS)

def _watchlist_out(item: MovieWatchlist) -> WatchlistMovieOut:
    return WatchlistMovieOut(movie_id=item.movie.cinematica_id or item.movie_id, title=item.movie.title,
        poster_url=item.movie.poster_url, age_rating=item.movie.age_rating,
        catalog_status=item.movie.catalog_status, release_date=item.movie.release_date,
        alert_sent_at=item.alert_sent_at, created_at=item.created_at)

@router.get("/watchlist", response_model=list[WatchlistMovieOut])
def movie_watchlist(db: Session = Depends(get_db), user: User = Depends(current_user)):
    items = db.scalars(sa.select(MovieWatchlist).where(MovieWatchlist.user_id == user.id)
        .order_by(MovieWatchlist.created_at.desc())).all()
    return [_watchlist_out(item) for item in items]

def _watchlist_catalog_movie(movie_id: int, db: Session) -> Movie:
    """Resolve Cinematica's public ID to Phantora's durable movie record."""
    movie = db.scalar(sa.select(Movie).where(Movie.cinematica_id == movie_id))
    if movie:
        return movie
    source = _source_movie(movie_id)
    movie = Movie(cinematica_id=movie_id, title=source["title"],
        synopsis="Saved from the live Cinematica catalogue.", duration_minutes=120,
        genre="Cinema", age_rating=source["age_rating"], language=source["language"],
        poster_url=source["poster_url"] or "", release_date=date.fromisoformat(source["release_date"])
        if source["release_date"] else None, catalog_status=source["catalog_status"], active=True)
    db.add(movie)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        movie = db.scalar(sa.select(Movie).where(Movie.cinematica_id == movie_id))
        if not movie:
            raise
    return movie

@router.put("/watchlist/{movie_id}", response_model=WatchlistMovieOut)
def save_movie(movie_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    movie = _watchlist_catalog_movie(movie_id, db)
    item = db.scalar(sa.select(MovieWatchlist).where(MovieWatchlist.user_id == user.id,
        MovieWatchlist.movie_id == movie.id).with_for_update())
    if not item:
        item = MovieWatchlist(user_id=user.id, movie_id=movie.id)
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            item = db.scalar(sa.select(MovieWatchlist).where(MovieWatchlist.user_id == user.id,
                MovieWatchlist.movie_id == movie.id))
    db.refresh(item)
    return _watchlist_out(item)

@router.delete("/watchlist/{movie_id}")
def remove_saved_movie(movie_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.scalar(sa.select(MovieWatchlist).join(Movie).where(MovieWatchlist.user_id == user.id,
        (Movie.cinematica_id == movie_id) | ((Movie.cinematica_id.is_(None)) & (Movie.id == movie_id))).with_for_update())
    if not item:
        raise HTTPException(404, "Saved movie not found")
    db.delete(item)
    db.commit()
    return {"removed": True}

@router.get("/notifications", response_model=list[CustomerNotificationOut])
def customer_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Return durable customer-facing delivery events without exposing email data."""
    items: list[CustomerNotificationOut] = []
    booking_rows = db.execute(sa.select(BookingNotification, Booking, Screening, Movie, Auditorium)
        .join(Booking, BookingNotification.booking_id == Booking.id)
        .join(Screening, Booking.screening_id == Screening.id)
        .join(Movie, Screening.movie_id == Movie.id)
        .join(Auditorium, Screening.auditorium_id == Auditorium.id)
        .where(Booking.customer_id == user.id)).all()
    for notice, _, screening, movie, auditorium in booking_rows:
        items.append(CustomerNotificationOut(id=f"booking-{notice.id}", kind=notice.event_type,
            state="sent" if notice.sent_at else "retrying" if notice.attempts else "scheduled",
            movie_title=movie.title, cinema_name=f"{auditorium.cinema_name} · {auditorium.name}",
            starts_at=screening.starts_at, due_at=notice.due_at, created_at=notice.created_at))
    waitlist_rows = db.execute(sa.select(WaitlistNotification, WaitlistEntry, Screening, Movie, Auditorium)
        .join(WaitlistEntry, WaitlistNotification.waitlist_entry_id == WaitlistEntry.id)
        .join(Screening, WaitlistEntry.screening_id == Screening.id)
        .join(Movie, Screening.movie_id == Movie.id)
        .join(Auditorium, Screening.auditorium_id == Auditorium.id)
        .where(WaitlistEntry.user_id == user.id)).all()
    for notice, _, screening, movie, auditorium in waitlist_rows:
        items.append(CustomerNotificationOut(id=f"waitlist-{notice.id}", kind="waitlist_available",
            state="sent" if notice.sent_at else "retrying" if notice.attempts else "scheduled",
            movie_title=movie.title, cinema_name=f"{auditorium.cinema_name} · {auditorium.name}",
            starts_at=screening.starts_at, due_at=notice.due_at, created_at=notice.created_at))
    saved_rows = db.execute(sa.select(MovieWatchlistNotification, MovieWatchlist, Screening, Movie, Auditorium)
        .join(MovieWatchlist, MovieWatchlistNotification.watchlist_id == MovieWatchlist.id)
        .join(Screening, MovieWatchlistNotification.screening_id == Screening.id)
        .join(Movie, MovieWatchlist.movie_id == Movie.id)
        .join(Auditorium, Screening.auditorium_id == Auditorium.id)
        .where(MovieWatchlist.user_id == user.id)).all()
    for notice, _, screening, movie, auditorium in saved_rows:
        items.append(CustomerNotificationOut(id=f"saved-film-{notice.id}", kind="saved_movie_showtime",
            state="sent" if notice.sent_at else "retrying" if notice.attempts else "scheduled",
            movie_title=movie.title, cinema_name=f"{auditorium.cinema_name} · {auditorium.name}",
            starts_at=screening.starts_at, due_at=notice.due_at, created_at=notice.created_at))
    return sorted(items, key=lambda item: (item.created_at, item.due_at), reverse=True)[:50]

@router.delete("/notifications")
def clear_customer_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Remove delivered notices while retaining undelivered ones and watchlist alerts."""
    booking_ids = sa.select(Booking.id).where(Booking.customer_id == user.id)
    waitlist_ids = sa.select(WaitlistEntry.id).where(WaitlistEntry.user_id == user.id)
    watchlist_ids = sa.select(MovieWatchlist.id).where(MovieWatchlist.user_id == user.id)
    removed = 0
    for statement in (
        sa.delete(BookingNotification).where(
            BookingNotification.booking_id.in_(booking_ids),
            BookingNotification.sent_at.is_not(None),
        ),
        sa.delete(WaitlistNotification).where(
            WaitlistNotification.waitlist_entry_id.in_(waitlist_ids),
            WaitlistNotification.sent_at.is_not(None),
        ),
        sa.delete(MovieWatchlistNotification).where(
            MovieWatchlistNotification.watchlist_id.in_(watchlist_ids),
            MovieWatchlistNotification.sent_at.is_not(None),
        ),
    ):
        result = db.execute(statement)
        removed += result.rowcount or 0
    db.commit()
    return {"cleared_count": removed}
