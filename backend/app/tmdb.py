from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
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
            today = datetime.now(ZoneInfo(settings.business_timezone)).date().isoformat()
            for stale in db.scalars(select(Movie).where(Movie.catalog_status == "upcoming")):
                stale.active = False
            max_pages = max(1, min(settings.tmdb_max_pages, 20))
            for category in ("now_playing", "upcoming"):
                params = {"region": settings.tmdb_region, "language": "en-US", "page": 1,
                          "include_adult": "false"}
                if category == "upcoming":
                    path = "/discover/movie"
                    params.update({"primary_release_date.gte": today, "with_release_type": "2|3",
                                   "sort_by": "popularity.desc"})
                else:
                    path = f"/movie/{category}"
                first = client.get(path, params=params)
                first.raise_for_status()
                payload = first.json()
                page_count = min(max_pages, max(1, int(payload.get("total_pages", 1))))
                listing_rows = list(payload.get("results", []))
                for page in range(2, page_count + 1):
                    response = client.get(path, params={**params, "page": page})
                    response.raise_for_status()
                    listing_rows.extend(response.json().get("results", []))
                listings = []
                for item in listing_rows:
                    tmdb_id = item.get("id")
                    if not tmdb_id or tmdb_id in seen_tmdb_ids:
                        continue
                    seen_tmdb_ids.add(tmdb_id)
                    listings.append((tmdb_id, item))

                def fetch_detail(entry: tuple[int, dict]) -> tuple[int, dict]:
                    tmdb_id, _ = entry
                    response = client.get(f"/movie/{tmdb_id}", params={
                        "language": "en-US", "append_to_response": "credits,videos,release_dates"})
                    response.raise_for_status()
                    return tmdb_id, response.json()

                with ThreadPoolExecutor(max_workers=4) as pool:
                    details = dict(pool.map(fetch_detail, listings))
                for tmdb_id, item in listings:
                    detail = details[tmdb_id]
                    movie = db.scalar(select(Movie).where(Movie.tmdb_id == int(detail["id"])))
                    if movie is None:
                        movie = Movie(tmdb_id=int(detail["id"]), title=detail.get("original_title") or detail.get("title") or item.get("title") or "Untitled")
                        db.add(movie)
                    release = _uz_release(detail, item.get("release_date"))
                    rating = _uz_rating(detail)
                    cast = [person.get("name", "") for person in detail.get("credits", {}).get("cast", [])[:8]
                            if person.get("name")]
                    trailer = next((video.get("key") for video in detail.get("videos", {}).get("results", [])
                                    if video.get("site") == "YouTube" and video.get("type") == "Trailer"
                                    and video.get("key")), None)
                    movie.title = detail.get("original_title") or detail.get("title") or item.get("original_title") or item.get("title") or movie.title
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
