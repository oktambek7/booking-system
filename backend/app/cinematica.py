"""Read-only adapter for Cinematica's public movie and repertory endpoints.

This adapter is used only for discovery and schedule previews. It never hands a
customer into an external checkout or treats the source's inventory as Parda's.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from threading import Lock
import time

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Auditorium, Booking, BookingSeat, BookingStatus, CatalogScreeningLink, Movie, Screening, Seat

router = APIRouter(prefix="/api/cinematica", tags=["Cinematica catalog"])
BASE = "https://cinematica.uz/api/v1"
_cache: dict[str, tuple[float, dict]] = {}
_lock = Lock()


def _get(path: str) -> dict:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(path)
        if cached and cached[0] > now:
            return cached[1]
    try:
        response = httpx.get(f"{BASE}/{path.lstrip('/')}", timeout=8.0,
                             headers={"Accept": "application/json", "User-Agent": "PardaCinema/1.0"})
        response.raise_for_status()
        payload = response.json()
        if payload.get("result") != 0 or not isinstance(payload.get("list"), list):
            raise ValueError("Unexpected catalog response")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Cinematica's live catalog is temporarily unavailable") from exc
    with _lock:
        _cache[path] = (now + 300, payload)
    return payload


def _detail(movie: dict, label: str) -> str:
    for item in movie.get("details") or []:
        if str(item.get("title", "")).casefold() == label.casefold():
            return str(item.get("value") or "")
    return ""


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _movie_out(movie: dict, category: str) -> dict:
    title = str(movie.get("name") or "Untitled")
    poster = movie.get("file_poster_vertical") or movie.get("file_poster")
    audio = _detail(movie, "Язык") or _detail(movie, "Language") or ""
    if not audio:
        name = title.casefold()
        audio = "Uzbek" if any(value in name for value in ("o'zbek", "узбек", "uzbek")) else "English" if "eng" in name else "Russian" if "рус" in name else "Not listed"
    elif "узбек" in audio.casefold():
        audio = "Uzbek"
    elif "англ" in audio.casefold():
        audio = "English"
    elif "рус" in audio.casefold():
        audio = "Russian"
    fmt = "IMAX" if "imax" in title.casefold() else "3D" if "3d" in title.casefold() else "2D"
    return {
        "id": int(movie["id"]),
        "title": title,
        "age_rating": str(movie.get("age_restriction") or "N/R"),
        "language": audio,
        "poster_url": f"https://cinematica.uz{poster}" if poster and poster.startswith("/") else poster,
        "release_date": _iso_date(movie.get("date_start")),
        "catalog_status": category,
        "format_type": fmt,
        "cinematica_url": f"https://cinematica.uz/movies/{int(movie['id'])}",
    }


def _format_type(item: dict, title: str = "") -> str:
    value = " ".join(str(item.get(key) or "") for key in ("hall", "format", "name")) + " " + title
    value = value.casefold()
    return "IMAX" if "imax" in value else "3D" if "3d" in value else "2D"


def _show_out(item: dict) -> dict | None:
    if item.get("is_disabled") or item.get("disable_sales"):
        return None
    try:
        day = datetime.strptime(item["date"], "%d.%m.%y").date().isoformat()
        hour, minute = (int(part) for part in item["time"].split(":", 1))
        repertory_id = int(item.get("id") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if not repertory_id:
        return None
    name = str(item.get("hall") or "")
    return {
        "id": repertory_id,
        "date": day,
        "time": f"{hour:02d}:{minute:02d}",
        "cinema_name": str(item.get("cinema") or "Cinematica"),
        "hall_name": name,
        "hall_type": "vip" if any(word in name.casefold() for word in ("vip", "lounge")) else "standard",
        "format_type": _format_type(item),
        "price": item.get("price"),
    }


def _source_movie(movie_id: int) -> dict:
    for route, category in (("movies/today", "now_playing"), ("movies/soon", "upcoming")):
        for movie in _get(route)["list"]:
            if int(movie.get("id") or 0) == movie_id:
                return _movie_out(movie, category)
    raise HTTPException(404, "Movie is no longer available in the live catalog")


def _source_show(movie_id: int, repertory_id: int) -> tuple[dict, dict]:
    payload = _get(f"repertory/movie/{movie_id}/grouped")
    for item in payload["list"]:
        parsed = _show_out(item)
        if parsed and parsed["id"] == repertory_id:
            return parsed, item
    raise HTTPException(404, "This showtime is no longer available")


def _ticketing_out(db: Session, screening: Screening) -> dict:
    taken = db.scalar(sa.select(sa.func.count(BookingSeat.id)).join(Booking).where(
        BookingSeat.screening_id == screening.id, BookingSeat.active.is_(True),
        Booking.status.in_((BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)))) or 0
    total = db.scalar(sa.select(sa.func.count(Seat.id)).where(Seat.auditorium_id == screening.auditorium_id)) or 0
    return {
        "id": screening.id, "movie_id": screening.movie_id, "auditorium_id": screening.auditorium_id,
        "starts_at": screening.starts_at, "ends_at": screening.ends_at, "base_price": screening.base_price,
        "premium_surcharge": screening.premium_surcharge, "format_type": screening.format_type,
        "movie_title": screening.movie.title, "duration_minutes": screening.movie.duration_minutes,
        "cinema_name": screening.auditorium.cinema_name, "auditorium_name": screening.auditorium.name,
        "hall_type": screening.auditorium.hall_type, "city": screening.auditorium.city,
        "timezone": screening.auditorium.timezone, "available_seats": max(total - taken, 0),
    }


@router.get("/movies")
def movies(category: str = Query(default="now_playing", pattern=r"^(now_playing|upcoming)$")):
    route = "movies/today" if category == "now_playing" else "movies/soon"
    payload = _get(route)
    return [_movie_out(movie, category) for movie in payload["list"]
            if movie.get("id") is not None and not movie.get("is_disabled")]


@router.get("/movies/{movie_id}/screenings")
def movie_screenings(movie_id: int):
    if movie_id <= 0:
        raise HTTPException(422, "Invalid movie id")
    payload = _get(f"repertory/movie/{movie_id}/grouped")
    result = [parsed for item in payload["list"] if (parsed := _show_out(item))]
    return sorted(result, key=lambda item: (item["date"], item["time"], item["cinema_name"]))


@router.post("/movies/{movie_id}/screenings/{repertory_id}/ticketing")
def resolve_ticketing_screening(movie_id: int, repertory_id: int, db: Session = Depends(get_db)):
    """Create or return Parda's seat inventory for one live catalog showtime.

    The source schedule is fetched again on the server, so a browser cannot
    invent a film, price, hall, or showtime.  The unique link makes resolving
    a showtime idempotent under concurrent clicks.
    """
    show, raw = _source_show(movie_id, repertory_id)
    local_start = datetime.fromisoformat(f"{show['date']}T{show['time']}:00+05:00")
    starts_at = local_start.astimezone(timezone.utc)
    if starts_at <= datetime.now(timezone.utc):
        raise HTTPException(410, "This showtime has already started")
    existing = db.get(CatalogScreeningLink, repertory_id)
    if existing:
        return _ticketing_out(db, existing.screening)

    source_movie = _source_movie(movie_id)
    fmt = _format_type(raw, source_movie["title"])
    try:
        amount = Decimal(str(show["price"])).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(422, "This showtime does not have a valid ticket price")
    movie = db.scalar(sa.select(Movie).where(Movie.title == source_movie["title"], Movie.poster_url == (source_movie["poster_url"] or "")).limit(1))
    if not movie:
        movie = Movie(title=source_movie["title"], synopsis="Catalog showtime imported for Parda ticketing.",
                      duration_minutes=120, genre="Cinema", age_rating=source_movie["age_rating"],
                      language=source_movie["language"], poster_url=source_movie["poster_url"] or "",
                      release_date=datetime.fromisoformat(source_movie["release_date"]).date() if source_movie["release_date"] else None,
                      catalog_status=source_movie["catalog_status"], active=True)
        db.add(movie)
        db.flush()
    auditorium = db.scalar(sa.select(Auditorium).where(Auditorium.cinema_name == show["cinema_name"],
        Auditorium.name == show["hall_name"], Auditorium.hall_type == show["hall_type"]).limit(1))
    if not auditorium:
        rows, per_row = (5, 8) if show["hall_type"] == "vip" else (8, 12)
        auditorium = Auditorium(name=show["hall_name"], cinema_name=show["cinema_name"], city="Tashkent",
            timezone="Asia/Tashkent", formats=[fmt], hall_type=show["hall_type"])
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        auditorium.seats = [Seat(row_label=alphabet[row], seat_number=number,
            seat_type="premium" if row < 2 else "standard")
            for row in range(rows) for number in range(1, per_row + 1)]
        db.add(auditorium)
        db.flush()
    screening = Screening(movie_id=movie.id, auditorium_id=auditorium.id, starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=movie.duration_minutes or 120), base_price=amount,
        premium_surcharge=Decimal("0"), format_type=fmt)
    db.add(screening)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This cinema hall already has a screening at that time")
    db.add(CatalogScreeningLink(source_repertory_id=repertory_id, screening_id=screening.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        resolved = db.get(CatalogScreeningLink, repertory_id)
        if resolved:
            return _ticketing_out(db, resolved.screening)
        raise HTTPException(409, "This showtime is being prepared. Please try again")
    db.refresh(screening)
    return _ticketing_out(db, screening)
