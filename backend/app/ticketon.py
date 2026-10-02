"""Read-only adapter for Ticketon's official public cinema-session API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import time
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
EVENT_API = "https://api-gw.ticketon.uz/event/v1/events"
EVENT_PAGE = "https://ticketon.uz/en/cinema/event"
TASHKENT_CITY_ID = 103
FRESH_SECONDS = 5 * 60
STALE_SECONDS = 30 * 60
LOOKAHEAD_DAYS = 7

# Each title below is paired with the public Ticketon event ID published on its
# event page. IDs are used only with Ticketon's documented browser API.
TITLE_EVENTS = {
    "digger": (11549, "tckt2-digger-uz"),
    "диггер": (11549, "tckt2-digger-uz"),
    "приключения мамонтенка. в поисках мамы": (11554, "tckt2-priklyucheniya-mamontenka-v-poiskah-mamy-uz"),
    "приключения мамонтёнка. в поисках мамы": (11554, "tckt2-priklyucheniya-mamontenka-v-poiskah-mamy-uz"),
    "the adventures of the mammoth cub. in search of mom": (11554, "tckt2-priklyucheniya-mamontenka-v-poiskah-mamy-uz"),
    "пункт назначения: мост №13": (11552, "tckt2-punkt-naznacheniya-most-13-uz"),
    "destination: bridge no. 13": (11552, "tckt2-punkt-naznacheniya-most-13-uz"),
    "сердце зверя": (11276, "tckt2-serdtse-zverya-uz"),
    "heart of the beast": (11276, "tckt2-serdtse-zverya-uz"),
    "на деревню к дедушке. супермиссия": (11553, "tckt2-na-derevnyu-k-dedushke-supermissiya-uz"),
    "мой пес гохан": (11550, "tckt2-moy-pes-gohan-uz"),
    "my dog gokhan": (11550, "tckt2-moy-pes-gohan-uz"),
}

# Coordinates are saved only where a public map listing identifies the venue.
# Other live venues remain selectable but are excluded from distance claims.
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

_CACHE: dict[int, tuple[float, float, list[dict]]] = {}
_LOCK = Lock()


def _event_for_title(title: str) -> tuple[int, str] | None:
    return TITLE_EVENTS.get(title.casefold().strip())


def _session_out(raw: dict, slug: str, now: datetime) -> dict | None:
    try:
        starts_at = datetime.fromisoformat(str(raw["time"])).astimezone(timezone.utc)
        raw_id = int(raw["id"])
        hall_id = int(raw["hall_id"])
        venue_id = int(raw["venue_id"])
        price = int(raw["min_price"])
    except (KeyError, TypeError, ValueError):
        return None
    venue = str(raw.get("venue_name") or "").strip()
    if (raw.get("sales_status") != "on_sale" or venue not in ALLOWED_VENUES
            or starts_at <= now or not raw_id or not hall_id or not venue_id):
        return None
    hall = str(raw.get("hall_name") or "").strip()
    metadata = VENUE_METADATA.get(venue, {})
    return {
        # Negative values keep Ticketon's source IDs disjoint from Cinematica
        # repertory IDs already used in Parda's database.
        "id": -raw_id,
        "date": starts_at.astimezone(timezone(timedelta(hours=5))).date().isoformat(),
        "time": starts_at.astimezone(timezone(timedelta(hours=5))).strftime("%H:%M"),
        "cinema_name": DISPLAY_NAMES.get(venue, venue),
        "source_cinema_name": venue,
        "cinema_id": venue_id,
        "hall_id": hall_id,
        "hall_name": hall,
        "hall_type": "vip" if "vip" in hall.casefold() else "standard",
        "format_type": str(raw.get("format") or "2D").strip(),
        "audio_language": str(raw.get("language") or raw.get("language_short") or "").strip(),
        "price": price,
        "address": str(raw.get("address") or "").strip() or None,
        "latitude": metadata.get("latitude"),
        "longitude": metadata.get("longitude"),
        "source_name": "ticketon",
        "source_url": f"{EVENT_PAGE}/{slug}",
    }


def _fetch_event(event_id: int, slug: str) -> list[dict]:
    """Fetch future on-sale sessions from Ticketon's public JSON endpoint."""
    now = datetime.now(timezone.utc)
    tashkent_today = now.astimezone(timezone(timedelta(hours=5))).date()
    found: dict[int, dict] = {}
    for offset in range(LOOKAHEAD_DAYS):
        query = urlencode({"id": event_id, "date_day": (tashkent_today + timedelta(days=offset)).isoformat(),
                           "city_id": TASHKENT_CITY_ID})
        request = Request(f"{EVENT_API}/{event_id}/sessions/movie?{query}", headers={
            "Accept": "application/json", "Accept-Language": "en",
            "User-Agent": "PardaCinema/1.0 (+https://parda.uz)",
        })
        try:
            with urlopen(request, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.warning("Ticketon API fetch failed for event %s: %s", event_id, error)
            continue
        for raw in payload.get("sessions") or []:
            session = _session_out(raw, slug, now)
            if session:
                found[-int(raw["id"])] = session
    return sorted(found.values(), key=lambda item: (item["date"], item["time"], item["cinema_name"]))


def shows_for_title(title: str) -> list[dict]:
    """Return future, saleable sessions for a verified public title mapping."""
    event = _event_for_title(title)
    if not event:
        return []
    event_id, slug = event
    now = time.monotonic()
    stale: list[dict] | None = None
    with _LOCK:
        cached = _CACHE.get(event_id)
        if cached:
            fresh_until, stale_until, payload = cached
            if fresh_until > now:
                return payload
            if stale_until > now:
                stale = payload
    sessions = _fetch_event(event_id, slug)
    if not sessions and stale is not None:
        return stale
    with _LOCK:
        _CACHE[event_id] = (now + FRESH_SECONDS, now + STALE_SECONDS, sessions)
    return sessions


def show_for_title(title: str, source_id: int) -> dict | None:
    return next((item for item in shows_for_title(title) if item["id"] == source_id), None)
