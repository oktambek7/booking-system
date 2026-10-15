import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from ..config import settings
from ..database import SessionLocal
from ..live import broadcaster
from ..models import Screening
from ..ratelimit import client_ip

router = APIRouter()

def _screening_state(screening_id: int) -> str:
    with SessionLocal() as db:
        screening = db.get(Screening, screening_id)
        if not screening or screening.status != "scheduled":
            return "missing"
        return "started" if screening.starts_at <= datetime.now(timezone.utc) else "open"

def _message(event: str, screening_id: int) -> str:
    return f"event: {event}\ndata: {json.dumps({'screening_id': screening_id})}\n\n"

@router.get("/screenings/{screening_id}/seats/stream")
async def seat_stream(screening_id: int, request: Request):
    """Server-Sent Events: a `seats` event whenever a seat of this screening is taken or released.

    The event carries no seat data; the page refetches /seats. Browsers reconnect on their own, and
    pages fall back to polling if a proxy refuses to keep the stream open."""
    state = await run_in_threadpool(_screening_state, screening_id)
    if state == "missing":
        raise HTTPException(404, "Screening not found")
    if state == "started":
        raise HTTPException(410, "This screening has already started")
    ip = client_ip(request)
    if broadcaster.subscriber_count >= settings.live_max_streams or broadcaster.per_ip[ip] >= settings.live_max_streams_per_ip:
        raise HTTPException(429, "Too many live connections. The page will keep refreshing on its own")
    broadcaster.per_ip[ip] += 1
    wakeup = broadcaster.subscribe(screening_id)

    async def stream():
        try:
            yield "retry: 3000\n\n" + _message("ready", screening_id)
            while True:
                try:
                    await asyncio.wait_for(wakeup.wait(), timeout=settings.live_heartbeat_seconds)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"                      # keeps idle proxies from closing the stream
                    continue
                wakeup.clear()
                yield _message("seats", screening_id)
                await asyncio.sleep(0.5)                    # one booking touches many seats: coalesce the burst
        finally:
            broadcaster.unsubscribe(screening_id, wakeup)
            broadcaster.per_ip[ip] -= 1
            if broadcaster.per_ip[ip] <= 0:
                broadcaster.per_ip.pop(ip, None)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
