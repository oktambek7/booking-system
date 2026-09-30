"""Read-only adapter for Cinematica's public movie and repertory endpoints.

This adapter is used only for discovery and schedule previews. It never hands a
customer into an external checkout or treats the source's inventory as Parda's.
"""
from datetime import datetime
from threading import Lock
import time

import httpx
from fastapi import APIRouter, HTTPException, Query

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
    result = []
    for item in payload["list"]:
        if item.get("is_disabled") or item.get("disable_sales"):
            continue
        try:
            day = datetime.strptime(item["date"], "%d.%m.%y").date().isoformat()
            hour, minute = (int(part) for part in item["time"].split(":", 1))
        except (KeyError, TypeError, ValueError):
            continue
        name = str(item.get("hall") or "")
        repertory_id = int(item.get("id") or 0)
        if not repertory_id:
            continue
        result.append({
            "id": repertory_id,
            "date": day,
            "time": f"{hour:02d}:{minute:02d}",
            "cinema_name": str(item.get("cinema") or "Cinematica"),
            "hall_name": name,
            "hall_type": "vip" if any(word in name.casefold() for word in ("vip", "lounge")) else "standard",
            "price": item.get("price"),
        })
    return sorted(result, key=lambda item: (item["date"], item["time"], item["cinema_name"]))
