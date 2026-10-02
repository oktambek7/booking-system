"""Small read-only adapter for Ticketon's public cinema pages.

The pages are server-rendered and expose on-sale sessions in their public
document.  Parda reads only the date, time, venue, hall, language, format and
lowest published price.  This is intentionally a narrow allow-list: a cinema
never appears simply because a name was guessed from a map result.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
import re
import time
from threading import Lock

import httpx


BASE = "https://ticketon.uz/en/cinema/event"
FRESH_SECONDS = 5 * 60
STALE_SECONDS = 30 * 60

# These two current public event pages collectively include the named Tashkent
# operators. Add a title only after verifying a live public event URL.
TITLE_SLUGS = {
    "digger": "tckt2-digger-uz",
    "диггер": "tckt2-digger-uz",
    "приключения мамонтенка. в поисках мамы": "tckt2-priklyucheniya-mamontenka-v-poiskah-mamy-uz",
    "приключения мамонтёнка. в поисках мамы": "tckt2-priklyucheniya-mamontenka-v-poiskah-mamy-uz",
    "the adventures of the mammoth cub. in search of mom": "tckt2-priklyucheniya-mamontenka-v-poiskah-mamy-uz",
    "пункт назначения: мост №13": "tckt2-punkt-naznacheniya-most-13-uz",
    "destination: bridge no. 13": "tckt2-punkt-naznacheniya-most-13-uz",
    "сердце зверя": "tckt2-serdtse-zverya-uz",
    "heart of the beast": "tckt2-serdtse-zverya-uz",
    "на деревню к дедушке. супермиссия": "tckt2-na-derevnyu-k-dedushke-supermissiya-uz",
    "мой пес гохан": "tckt2-moy-pes-gohan-uz",
    "my dog gokhan": "tckt2-moy-pes-gohan-uz",
}

# Coordinates are saved only where a public map listing identifies the venue.
# Other live venues remain selectable but are deliberately excluded from a
# distance claim until their operator/map coordinates are verified.
VENUE_METADATA = {
    "Next Cinema": {"latitude": 41.297942, "longitude": 69.249454},
    "Magic Cinema": {"latitude": 41.304519, "longitude": 69.245098},
    "Compass Cinema": {"latitude": 41.239040, "longitude": 69.328570},
    "Riviera Cinema": {"latitude": 41.339905, "longitude": 69.254332},
    "Parus Cinema": {"latitude": 41.292054, "longitude": 69.211087},
    "Uzbekistan National Cinema Art Palace": {"latitude": 41.319446, "longitude": 69.259611},
}

DISPLAY_NAMES = {
    "Premier Cinema": "Premier Cinema — Park in Mall",
    "Uzbekistan National Cinema Art Palace": "O‘zbekiston Milliy kino san’ati saroyi",
}
ALLOWED_VENUES = {
    "CinemaPlex", "Next Cinema", "Compass Cinema", "Riviera Cinema",
    "Parus Cinema", "Magic Cinema", "Sergeli Cinema", "Premier Cinema",
    "Uzbekistan National Cinema Art Palace",
}

_CACHE: dict[str, tuple[float, float, list[dict]]] = {}
_LOCK = Lock()

# The state is compact JavaScript rather than JSON. It is part of Ticketon's
# public server-rendered document. The expression stays restrictive so an
# unrelated field cannot be mistaken for a saleable session.
SESSION = re.compile(
    r'time:"(?P<starts>[^"\\]+)",session_period:"(?P<period>[^"\\]+)",'
    r'id:(?P<id>\d+),format:"(?P<format>[^"\\]+)",language:"(?P<language>[^"\\]+)",'
    r'language_short:"(?P<language_short>[^"\\]+)",min_price:"(?P<price>\d+)"'
    r'.{0,1200}?sales_status:"(?P<sales_status>[^"\\]+)"'
    r'.{0,1200}?hall_id:(?P<hall_id>\d+),hall_name:"(?P<hall_name>(?:\\.|[^"\\])*)",'
    r'venue_id:(?P<venue_id>\d+),venue_name:"(?P<venue_name>(?:\\.|[^"\\])*)"'
    r'.{0,1800}?address:"(?P<address>(?:\\.|[^"\\])*)"',
    re.DOTALL,
)


def _clean(value: str) -> str:
    return html.unescape(value.replace(r'\"', '"').replace(r'\\', '\\')).strip()


def _slug_for_title(title: str) -> str | None:
    return TITLE_SLUGS.get(title.casefold().strip())


def _parse(slug: str, body: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    found: dict[int, dict] = {}
    for match in SESSION.finditer(body):
        try:
            starts_at = datetime.fromisoformat(match.group("starts")).astimezone(timezone.utc)
            raw_id = int(match.group("id"))
            hall_id = int(match.group("hall_id"))
            venue_id = int(match.group("venue_id"))
            price = int(match.group("price"))
        except (TypeError, ValueError):
            continue
        venue = _clean(match.group("venue_name"))
        if (match.group("sales_status") != "on_sale" or venue not in ALLOWED_VENUES
                or starts_at <= now or not raw_id or not hall_id or not venue_id):
            continue
        hall = _clean(match.group("hall_name"))
        metadata = VENUE_METADATA.get(venue, {})
        found[raw_id] = {
            # Negative values keep Ticketon's source IDs disjoint from the
            # positive Cinematica repertory primary key already in the DB.
            "id": -raw_id,
            "date": starts_at.date().isoformat(),
            "time": starts_at.strftime("%H:%M"),
            "cinema_name": DISPLAY_NAMES.get(venue, venue),
            "source_cinema_name": venue,
            "cinema_id": venue_id,
            "hall_id": hall_id,
            "hall_name": hall,
            "hall_type": "vip" if "vip" in hall.casefold() else "standard",
            "format_type": _clean(match.group("format")) or "2D",
            "audio_language": _clean(match.group("language")) or _clean(match.group("language_short")),
            "price": price,
            "address": _clean(match.group("address")) or None,
            "latitude": metadata.get("latitude"),
            "longitude": metadata.get("longitude"),
            "source_name": "ticketon",
            "source_url": f"{BASE}/{slug}",
        }
    return sorted(found.values(), key=lambda item: (item["date"], item["time"], item["cinema_name"]))


def shows_for_title(title: str) -> list[dict]:
    """Return future, on-sale sessions for a verified public title mapping."""
    slug = _slug_for_title(title)
    if not slug:
        return []
    now = time.monotonic()
    stale: list[dict] | None = None
    with _LOCK:
        cached = _CACHE.get(slug)
        if cached:
            fresh_until, stale_until, payload = cached
            if fresh_until > now:
                return payload
            if stale_until > now:
                stale = payload
    try:
        response = httpx.get(f"{BASE}/{slug}", timeout=10.0, headers={
            "Accept": "text/html", "User-Agent": "PardaCinema/1.0 (+https://parda.uz)",
        })
        response.raise_for_status()
        sessions = _parse(slug, response.text)
    except httpx.HTTPError:
        if stale is not None:
            return stale
        return []
    with _LOCK:
        _CACHE[slug] = (now + FRESH_SECONDS, now + STALE_SECONDS, sessions)
    return sessions


def show_for_title(title: str, source_id: int) -> dict | None:
    return next((item for item in shows_for_title(title) if item["id"] == source_id), None)
