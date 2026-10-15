"""Live seat-map updates over Server-Sent Events.

PostgreSQL does the signalling: a trigger NOTIFYs the screening id whenever a seat's availability changes
(alembic revision 0005). Each API process keeps one LISTEN connection (`SeatBroadcaster`) and wakes the
browsers watching that screening. The event carries no seat data, only "this screening changed": the page
refetches through the normal seat endpoint, so nothing new is exposed and the browser always sees the
same truth as a page reload.
"""
import asyncio
import logging
import threading
from collections import defaultdict
import psycopg
from .config import settings
from .database import engine

logger = logging.getLogger("parda.live")
CHANNEL = "seat_changes"
RESYNC = -1          # wakes everyone after the listener reconnects: notifications may have been missed

class SeatBroadcaster:
    def __init__(self) -> None:
        self._waiters: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = defaultdict(set)
        self._lock = threading.Lock()
        self._owners = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = threading.Event()
        self.per_ip: dict[str, int] = defaultdict(int)

    # --- subscribers (called on the event loop that serves the stream) ---
    def subscribe(self, screening_id: int) -> asyncio.Event:
        event = asyncio.Event()
        with self._lock:
            self._waiters[screening_id].add((asyncio.get_running_loop(), event))
        return event

    def unsubscribe(self, screening_id: int, event: asyncio.Event) -> None:
        with self._lock:
            self._waiters[screening_id] = {w for w in self._waiters[screening_id] if w[1] is not event}
            if not self._waiters[screening_id]:
                del self._waiters[screening_id]

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return sum(len(waiters) for waiters in self._waiters.values())

    def _wake(self, screening_id: int) -> None:
        with self._lock:
            targets = [w for waiters in self._waiters.values() for w in waiters] if screening_id == RESYNC \
                else list(self._waiters.get(screening_id, ()))
        for loop, event in targets:
            if not loop.is_closed():
                loop.call_soon_threadsafe(event.set)

    # --- listener (own thread, shared by every app instance in the process) ---
    def start(self) -> None:
        with self._lock:
            self._owners += 1
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="seat-listener", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._owners = max(0, self._owners - 1)
            if self._owners or self._thread is None:
                return
            thread, self._thread = self._thread, None
        self._stop.set()
        thread.join(timeout=5)
        self.connected.clear()

    @staticmethod
    def _dsn() -> str:
        return engine.url.set(drivername="postgresql").render_as_string(hide_password=False)

    def _run(self) -> None:
        backoff, first = 1.0, True
        while not self._stop.is_set():
            try:
                with psycopg.connect(self._dsn(), autocommit=True, connect_timeout=10) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    self.connected.set()
                    backoff = 1.0
                    if not first:
                        self._wake(RESYNC)          # we were deaf for a while: make every page refetch
                    first = False
                    while not self._stop.is_set():
                        for note in conn.notifies(timeout=0.25):
                            try:
                                self._wake(int(note.payload))
                            except ValueError:
                                logger.warning("Ignoring malformed seat notification %r", note.payload)
            except Exception:
                self.connected.clear()
                if self._stop.is_set():
                    break
                logger.warning("Seat listener lost its database connection; retrying in %.0fs", backoff, exc_info=True)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)

broadcaster = SeatBroadcaster()

async def start_live_updates() -> None:
    if settings.live_updates_enabled:
        broadcaster.start()

async def stop_live_updates() -> None:
    if settings.live_updates_enabled:
        await asyncio.to_thread(broadcaster.stop)
