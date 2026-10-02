"""Read-only adapter for Cinematica's public movie and repertory endpoints.

This adapter is used only for discovery and schedule previews. It never hands a
customer into an external checkout or treats the source's inventory as Parda's.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import logging
from threading import Lock
import time

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Auditorium, Booking, BookingSeat, BookingStatus, CatalogScreeningLink, Movie, Role, Screening, Seat, User
from .schemas import CinemaDirectorySyncOut
from .security import require_roles
from .ticketon import show_for_title as ticketon_show_for_title, shows_for_title as ticketon_shows_for_title

router = APIRouter(prefix="/api/cinematica", tags=["Cinematica catalog"])
admin = Depends(require_roles(Role.ADMIN))
BASE = "https://cinematica.uz/api/v1"
# The upstream catalogue is a convenience feed.  A temporary upstream timeout
# must not make a customer-facing programme disappear after its short fresh
# cache lifetime.  Keep a bounded stale copy as a read-only fallback.
_FRESH_CACHE_SECONDS = 5 * 60
_STALE_CACHE_SECONDS = 24 * 60 * 60
_cache: dict[str, tuple[float, float, dict]] = {}
_lock = Lock()
logger = logging.getLogger(__name__)
ACTIVE_BOOKING_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)


def _get(path: str) -> dict:
    now = time.monotonic()
    stale_payload: dict | None = None
    with _lock:
        cached = _cache.get(path)
        if cached:
            fresh_until, stale_until, payload = cached
            if fresh_until > now:
                return payload
            if stale_until > now:
                stale_payload = payload
    try:
        response = httpx.get(f"{BASE}/{path.lstrip('/')}", timeout=8.0,
                             headers={"Accept": "application/json", "User-Agent": "PardaCinema/1.0"})
        response.raise_for_status()
        payload = response.json()
        if payload.get("result") != 0 or not isinstance(payload.get("list"), list):
            raise ValueError("Unexpected catalog response")
    except (httpx.HTTPError, ValueError) as exc:
        if stale_payload is not None:
            logger.warning("Serving stale Cinematica catalogue after an upstream failure for %s: %s", path, exc)
            return stale_payload
        raise HTTPException(502, "Cinematica's live catalog is temporarily unavailable") from exc
    with _lock:
        _cache[path] = (now + _FRESH_CACHE_SECONDS, now + _STALE_CACHE_SECONDS, payload)
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
    try:
        cinema_id = int(item.get("cinema_id") or item.get("c_id") or 0)
        hall_id = int(item.get("hall_id") or 0)
    except (TypeError, ValueError):
        return None
    if not cinema_id or not hall_id:
        return None
    name = str(item.get("hall") or "")
    cinema_name = str(item.get("cinema") or "").strip()
    if not cinema_name or not name:
        return None
    return {
        "id": repertory_id,
        "date": day,
        "time": f"{hour:02d}:{minute:02d}",
        "cinema_name": cinema_name,
        "cinema_id": cinema_id,
        "hall_id": hall_id,
        "hall_name": name,
        "hall_type": "vip" if any(word in name.casefold() for word in ("vip", "lounge")) else "standard",
        "format_type": _format_type(item),
        "price": item.get("price"),
    }


def _hall_type(name: str) -> str:
    return "vip" if any(word in name.casefold() for word in ("vip", "lounge")) else "standard"


def _catalog_hall(db: Session, show: dict, *, source_url: str | None = None,
                  fmt: str | None = None, create: bool = False) -> Auditorium | None:
    """Find a hall by source identity and optionally retain a verified directory row.

    No address or coordinates are inferred here: upstream does not publish
    them in the feed Parda is allowed to read.
    """
    room = db.scalar(sa.select(Auditorium).where(
        Auditorium.source_name == "cinematica", Auditorium.external_hall_id == show["hall_id"]
    ).limit(1))
    if not room:
        room = db.scalar(sa.select(Auditorium).where(
            Auditorium.source_name.is_(None), Auditorium.cinema_name == show["cinema_name"],
            Auditorium.name == show["hall_name"], Auditorium.hall_type == show["hall_type"]
        ).limit(1))
    if not room and not create:
        return None
    if not room:
        rows, per_row = (5, 8) if show["hall_type"] == "vip" else (8, 12)
        room = Auditorium(name=show["hall_name"], cinema_name=show["cinema_name"], city="Tashkent",
            timezone="Asia/Tashkent", formats=[fmt or show["format_type"]], hall_type=show["hall_type"],
            source_name="cinematica", external_cinema_id=show["cinema_id"],
            external_hall_id=show["hall_id"], source_url=source_url)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        room.seats = [Seat(row_label=alphabet[row], seat_number=number,
            seat_type="premium" if row < 2 else "standard")
            for row in range(rows) for number in range(1, per_row + 1)]
        db.add(room)
        # Sessions use autoflush=False. Flush this new source identity now so
        # later showtimes in the same import see it instead of inserting the
        # same `(source_name, external_hall_id)` a second time.
        db.flush()
    else:
        room.name = show["hall_name"]
        room.cinema_name = show["cinema_name"]
        room.hall_type = _hall_type(show["hall_name"])
        room.source_name = "cinematica"
        room.external_cinema_id = show["cinema_id"]
        room.external_hall_id = show["hall_id"]
        if source_url:
            room.source_url = source_url
        if fmt and fmt not in (room.formats or []):
            room.formats = list(dict.fromkeys([*(room.formats or []), fmt]))
    room.last_synced_at = datetime.now(timezone.utc)
    return room


def _ticketon_catalog_hall(db: Session, show: dict, *, create: bool = False) -> Auditorium | None:
    """Retain a Ticketon venue/hall using its published source identity.

    The session page supplies the venue address. Coordinates are optional and
    come only from the checked venue map list maintained by the adapter.
    """
    external_hall_id = int(show["hall_id"])
    room = db.scalar(sa.select(Auditorium).where(
        Auditorium.source_name == "ticketon", Auditorium.external_hall_id == external_hall_id
    ).limit(1))
    if not room and not create:
        return None
    if not room:
        rows, per_row = (5, 8) if show["hall_type"] == "vip" else (8, 12)
        room = Auditorium(name=show["hall_name"], cinema_name=show["cinema_name"], city="Tashkent",
            address=show.get("address") or "", timezone="Asia/Tashkent", formats=[show["format_type"]],
            hall_type=show["hall_type"], source_name="ticketon", external_cinema_id=show["cinema_id"],
            external_hall_id=external_hall_id, source_url=show["source_url"],
            latitude=show.get("latitude"), longitude=show.get("longitude"))
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        room.seats = [Seat(row_label=alphabet[row], seat_number=number,
            seat_type="premium" if row < 2 else "standard")
            for row in range(rows) for number in range(1, per_row + 1)]
        db.add(room)
        # Sessions use autoflush=False. Flush this new source identity now so
        # later showtimes in the same import see it instead of inserting the
        # same `(source_name, external_hall_id)` a second time.
        db.flush()
    else:
        room.name = show["hall_name"]
        room.cinema_name = show["cinema_name"]
        room.address = show.get("address") or room.address
        room.hall_type = show["hall_type"]
        room.source_url = show["source_url"]
        room.external_cinema_id = show["cinema_id"]
        if show["format_type"] not in (room.formats or []):
            room.formats = list(dict.fromkeys([*(room.formats or []), show["format_type"]]))
        if show.get("latitude") is not None and show.get("longitude") is not None:
            room.latitude, room.longitude = show["latitude"], show["longitude"]
    room.last_synced_at = datetime.now(timezone.utc)
    return room


def sync_active_cinematica_halls(db: Session) -> dict:
    """Import the source hall directory from current public repertory.

    The operation is idempotent by `(source_name, external_hall_id)` and keeps
    source references for auditing. It stores no guessed venue location data.
    """
    now = datetime.now(timezone.utc)
    seen_halls: set[int] = set()
    active_showtimes = skipped = failures = 0
    try:
        source_movies = _get("movies/today")["list"]
    except HTTPException:
        raise
    for raw_movie in source_movies:
        if raw_movie.get("is_disabled") or not raw_movie.get("id"):
            continue
        movie_id = int(raw_movie["id"])
        try:
            movie = _movie_out(raw_movie, "now_playing")
            items = _get(f"repertory/movie/{movie_id}/grouped")["list"]
        except (HTTPException, ValueError, TypeError):
            failures += 1
            continue
        for item in items:
            show = _show_out(item)
            if not show:
                skipped += 1
                continue
            room = _catalog_hall(db, show, source_url=movie["cinematica_url"],
                                 fmt=_format_type(item, movie["title"]), create=True)
            if room:
                seen_halls.add(show["hall_id"])
            # Keep verified source hall identity even after its last daily
            # session starts. Only future sessions count as active and are
            # exposed by the public showtime endpoint.
            if _showtime_starts_at(show) <= now:
                skipped += 1
                continue
            active_showtimes += 1
    db.commit()
    return {"cinemas": len({room.cinema_name for room in db.scalars(sa.select(Auditorium).where(
                Auditorium.source_name == "cinematica", Auditorium.active.is_(True))).all()}),
            "halls": len(seen_halls), "active_showtimes": active_showtimes, "skipped": skipped,
            "upstream_failures": failures, "synced_at": now}


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


def _available_seats(db: Session, screening: Screening, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    active_booking = sa.or_(
        Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        sa.and_(Booking.status == BookingStatus.PENDING, Booking.hold_expires_at > now),
    )
    taken = db.scalar(sa.select(sa.func.count(BookingSeat.id)).join(Booking).where(
        BookingSeat.screening_id == screening.id, BookingSeat.active.is_(True),
        active_booking)) or 0
    total = db.scalar(sa.select(sa.func.count(Seat.id)).where(Seat.auditorium_id == screening.auditorium_id)) or 0
    return max(total - taken, 0)


def _ticketing_out(db: Session, screening: Screening) -> dict:
    return {
        "id": screening.id, "movie_id": screening.movie_id, "auditorium_id": screening.auditorium_id,
        "starts_at": screening.starts_at, "ends_at": screening.ends_at, "base_price": screening.base_price,
        "premium_surcharge": screening.premium_surcharge, "format_type": screening.format_type,
        "movie_title": screening.movie.title, "duration_minutes": screening.movie.duration_minutes,
        "cinema_name": screening.auditorium.cinema_name, "auditorium_name": screening.auditorium.name,
        "hall_type": screening.auditorium.hall_type, "city": screening.auditorium.city,
        "timezone": screening.auditorium.timezone, "available_seats": _available_seats(db, screening),
    }


def _showtime_starts_at(show: dict) -> datetime:
    return datetime.fromisoformat(f"{show['date']}T{show['time']}:00+05:00").astimezone(timezone.utc)


def _showtime_is_available(db: Session, show: dict, now: datetime | None = None) -> bool:
    """Keep unavailable Parda inventory and conflicting legacy sessions out of the public programme."""
    now = now or datetime.now(timezone.utc)
    starts_at = _showtime_starts_at(show)
    if starts_at <= now:
        return False
    linked = db.get(CatalogScreeningLink, show["id"])
    if linked:
        screening = linked.screening
        return (screening.status == "scheduled" and screening.starts_at > now
                and _available_seats(db, screening, now) > 0)
    auditorium = _catalog_hall(db, show, create=False)
    if not auditorium:
        return True
    # A previous Parda screening in the same imported hall would violate the
    # exclusion constraint. Do not present a slot that cannot be opened.
    ends_at = starts_at + timedelta(minutes=120)
    clash = db.scalar(sa.select(Screening.id).where(
        Screening.auditorium_id == auditorium.id,
        Screening.starts_at < ends_at, Screening.ends_at > starts_at).limit(1))
    return clash is None


def _ticketon_showtime_is_available(db: Session, show: dict, now: datetime | None = None) -> bool:
    """Avoid exposing a source time whose owned Parda seat map is already full."""
    now = now or datetime.now(timezone.utc)
    if _showtime_starts_at(show) <= now:
        return False
    linked = db.get(CatalogScreeningLink, show["id"])
    if linked:
        return (linked.screening.status == "scheduled" and linked.screening.starts_at > now
                and _available_seats(db, linked.screening, now) > 0)
    return True


@router.get("/movies")
def movies(category: str = Query(default="now_playing", pattern=r"^(now_playing|upcoming)$")):
    route = "movies/today" if category == "now_playing" else "movies/soon"
    payload = _get(route)
    return [_movie_out(movie, category) for movie in payload["list"]
            if movie.get("id") is not None and not movie.get("is_disabled")]


@router.get("/movies/{movie_id}/screenings")
def movie_screenings(movie_id: int, db: Session = Depends(get_db)):
    if movie_id <= 0:
        raise HTTPException(422, "Invalid movie id")
    payload = _get(f"repertory/movie/{movie_id}/grouped")
    now = datetime.now(timezone.utc)
    source_movie = _source_movie(movie_id)
    result = []
    for item in payload["list"]:
        parsed = _show_out(item)
        if not parsed:
            continue
        fmt = _format_type(item, source_movie["title"])
        # Film detail is a natural refresh point: retain every source hall
        # referenced by this movie, including halls whose last daily session
        # has already started. Past sessions themselves are never returned.
        room = _catalog_hall(db, parsed, source_url=source_movie["cinematica_url"], fmt=fmt, create=True)
        if not _showtime_is_available(db, parsed, now):
            continue
        parsed["format_type"] = fmt
        parsed["audio_language"] = source_movie["language"]
        parsed["source_url"] = source_movie["cinematica_url"]
        if room:
            parsed["address"] = room.address or None
            parsed["latitude"] = room.latitude
            parsed["longitude"] = room.longitude
        result.append(parsed)
    # Ticketon exposes a separate, public sale programme for specific movies.
    # It is merged by the film title only after the adapter has verified the
    # exact public event URL and an on-sale, future session.
    for parsed in ticketon_shows_for_title(source_movie["title"]):
        room = _ticketon_catalog_hall(db, parsed, create=True)
        if not _ticketon_showtime_is_available(db, parsed, now):
            continue
        if room:
            parsed["address"] = room.address or None
            parsed["latitude"] = room.latitude
            parsed["longitude"] = room.longitude
        result.append(parsed)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Another request imported the same source hall. The response can
        # still safely use the source showtimes; the next refresh enriches it.
    return sorted(result, key=lambda item: (item["date"], item["time"], item["cinema_name"]))


@router.post("/sync", response_model=CinemaDirectorySyncOut)
def sync_cinema_directory(db: Session = Depends(get_db), _: User = admin):
    return sync_active_cinematica_halls(db)


@router.post("/movies/{movie_id}/screenings/{repertory_id}/ticketing")
def resolve_ticketing_screening(movie_id: int, repertory_id: int, db: Session = Depends(get_db)):
    """Create or return Parda's seat inventory for one live catalog showtime.

    The source schedule is fetched again on the server, so a browser cannot
    invent a film, price, hall, or showtime.  The unique link makes resolving
    a showtime idempotent under concurrent clicks.
    """
    show, raw = _source_show(movie_id, repertory_id)
    starts_at = _showtime_starts_at(show)
    if not _showtime_is_available(db, show):
        raise HTTPException(410, "This showtime is no longer available")
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
    auditorium = _catalog_hall(db, show, source_url=source_movie["cinematica_url"], fmt=fmt, create=True)
    assert auditorium is not None
    db.flush()
    screening = Screening(movie_id=movie.id, auditorium_id=auditorium.id, starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=movie.duration_minutes or 120), base_price=amount,
        premium_surcharge=Decimal("0"), format_type=fmt)
    db.add(screening)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        resolved = db.get(CatalogScreeningLink, repertory_id)
        if resolved and _available_seats(db, resolved.screening) > 0:
            return _ticketing_out(db, resolved.screening)
        raise HTTPException(409, "This showtime was just taken off sale. Please choose another time")
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


@router.post("/movies/{movie_id}/ticketon/{session_id}/ticketing")
def resolve_ticketon_ticketing_screening(movie_id: int, session_id: int, db: Session = Depends(get_db)):
    """Create Parda's owned seat map for one currently on-sale Ticketon time.

    The adapter re-reads the public source on every resolve. A client may not
    choose a price, hall, venue, or time, and a negative source ID keeps its
    link disjoint from the existing Cinematica repertory links.
    """
    if session_id <= 0:
        raise HTTPException(422, "Invalid Ticketon session id")
    source_movie = _source_movie(movie_id)
    source_id = -session_id
    show = ticketon_show_for_title(source_movie["title"], source_id)
    if not show or not _ticketon_showtime_is_available(db, show):
        raise HTTPException(410, "This showtime is no longer available")
    existing = db.get(CatalogScreeningLink, source_id)
    if existing:
        return _ticketing_out(db, existing.screening)
    try:
        amount = Decimal(str(show["price"])).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(422, "This showtime does not have a valid ticket price")
    movie = db.scalar(sa.select(Movie).where(Movie.title == source_movie["title"],
        Movie.poster_url == (source_movie["poster_url"] or "")).limit(1))
    if not movie:
        movie = Movie(title=source_movie["title"], synopsis="Catalog showtime imported for Parda ticketing.",
            duration_minutes=120, genre="Cinema", age_rating=source_movie["age_rating"],
            language=source_movie["language"], poster_url=source_movie["poster_url"] or "",
            release_date=datetime.fromisoformat(source_movie["release_date"]).date() if source_movie["release_date"] else None,
            catalog_status=source_movie["catalog_status"], active=True)
        db.add(movie)
        db.flush()
    auditorium = _ticketon_catalog_hall(db, show, create=True)
    assert auditorium is not None
    starts_at = _showtime_starts_at(show)
    db.flush()
    screening = Screening(movie_id=movie.id, auditorium_id=auditorium.id, starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=movie.duration_minutes or 120), base_price=amount,
        premium_surcharge=Decimal("0"), format_type=show["format_type"])
    db.add(screening)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        resolved = db.get(CatalogScreeningLink, source_id)
        if resolved and _available_seats(db, resolved.screening) > 0:
            return _ticketing_out(db, resolved.screening)
        raise HTTPException(409, "This showtime was just taken off sale. Please choose another time")
    db.add(CatalogScreeningLink(source_repertory_id=source_id, screening_id=screening.id, source_name="ticketon"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        resolved = db.get(CatalogScreeningLink, source_id)
        if resolved:
            return _ticketing_out(db, resolved.screening)
        raise HTTPException(409, "This showtime is being prepared. Please try again")
    db.refresh(screening)
    return _ticketing_out(db, screening)
