from datetime import date
from decimal import Decimal
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .models import Movie

BASE = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p"

class TMDBUnavailable(Exception):
    pass

def image_url(path: str | None, size: str = "w500") -> str:
    return f"{IMAGE}/{size}/{path.lstrip('/')}" if path else ""

def sync_catalog(db: Session) -> tuple[int, int]:
    if not settings.tmdb_read_token:
        raise TMDBUnavailable("TMDB_READ_TOKEN is not configured")
    headers = {"Authorization": f"Bearer {settings.tmdb_read_token}", "accept": "application/json"}
    seen_tmdb_ids: set[int] = set()
    counts = {"now_playing": 0, "upcoming": 0}
    try:
        with httpx.Client(base_url=BASE, headers=headers, timeout=httpx.Timeout(12.0)) as client:
            for category in ("now_playing", "upcoming"):
                params = {"language": "en-US", "page": 1, "include_adult": "false"}
                if category == "now_playing":
                    params["region"] = settings.tmdb_region
                listing = client.get(f"/movie/{category}", params=params)
                listing.raise_for_status()
                for item in listing.json().get("results", [])[:10]:
                    tmdb_id = item.get("id")
                    if not tmdb_id or tmdb_id in seen_tmdb_ids:
                        continue
                    seen_tmdb_ids.add(tmdb_id)
                    
                    detail_response = client.get(f"/movie/{item['id']}", params={
                        "language": "en-US", "append_to_response": "credits,videos,release_dates"})
                    detail_response.raise_for_status()
                    detail = detail_response.json()
                    movie = db.scalar(select(Movie).where(Movie.tmdb_id == int(detail["id"])))
                    if movie is None:
                        movie = Movie(tmdb_id=int(detail["id"]), title=detail.get("title") or item.get("title") or "Untitled")
                        db.add(movie)
                    release = _uz_release(detail, item.get("release_date"))
                    rating = _uz_rating(detail)
                    cast = [person.get("name", "") for person in detail.get("credits", {}).get("cast", [])[:8]
                            if person.get("name")]
                    trailer = next((video.get("key") for video in detail.get("videos", {}).get("results", [])
                                    if video.get("site") == "YouTube" and video.get("type") == "Trailer"
                                    and video.get("key")), None)
                    movie.title = detail.get("title") or item.get("title") or movie.title
                    movie.synopsis = detail.get("overview") or item.get("overview") or ""
                    movie.duration_minutes = detail.get("runtime") or None
                    movie.genre = " · ".join(g.get("name", "") for g in detail.get("genres", []) if g.get("name")) or "Genre not listed"
                    movie.age_rating = rating
                    movie.language = detail.get("original_language", "") or ""
                    movie.poster_url = image_url(detail.get("poster_path"))
                    movie.backdrop_url = image_url(detail.get("backdrop_path"), "w1280")
                    movie.release_date = release
                    movie.vote_average = Decimal(str(detail.get("vote_average", 0))).quantize(Decimal("0.1"))
                    movie.cast_names = cast
                    movie.trailer_key = trailer
                    movie.catalog_status = category
                    movie.active = True
                    counts[category] += 1
        db.commit()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        db.rollback()
        raise TMDBUnavailable("TMDB catalog request failed; try again later") from exc
    return counts["now_playing"], counts["upcoming"]

def _uz_release(detail: dict, fallback: str | None) -> date | None:
    dates = detail.get("release_dates", {}).get("results", [])
    uz_dates = next((country.get("release_dates", []) for country in dates if country.get("iso_3166_1") == settings.tmdb_region), [])
    release = next((row.get("release_date", "")[:10] for row in uz_dates if row.get("release_date")), fallback)
    try:
        return date.fromisoformat(release) if release else None
    except ValueError:
        return None

def _uz_rating(detail: dict) -> str:
    dates = detail.get("release_dates", {}).get("results", [])
    uz = next((x for x in dates if x.get("iso_3166_1") == settings.tmdb_region), {})
    cert = next((x.get("certification") for x in uz.get("release_dates", []) if x.get("certification")), "")
    return cert[:12] if cert else "N/R"
