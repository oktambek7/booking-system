"""Request IDs, structured logging, and response hardening headers.

Every request gets an id (taken from a valid incoming X-Request-ID, else generated). It is
returned in the X-Request-ID response header, attached to every log line written while the
request runs, and included in the body of unexpected 500 errors, so one id ties a customer's
report to the server logs.
"""
import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from .config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("parda.access")

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
_QUIET_PATHS = ("/health",)      # probes run every few seconds; log them at DEBUG only

# --------------------------------------------------------------------------- logging

_default_factory = logging.getLogRecordFactory()

def _record_factory(*args, **kwargs) -> logging.LogRecord:
    record = _default_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    return record

class JsonFormatter(logging.Formatter):
    """One JSON object per line, ready for Render / Datadog / Loki style log search."""
    _extras = ("method", "path", "status", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                 "logger": record.name, "message": record.getMessage(),
                 "request_id": getattr(record, "request_id", "-")}
        for key in self._extras:
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)

def configure_logging() -> None:
    """Idempotent: safe to call from the API and the worker, and again in tests."""
    logging.setLogRecordFactory(_record_factory)
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    handler = next((h for h in root.handlers if getattr(h, "_parda", False)), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler._parda = True
        root.addHandler(handler)
    use_json = (settings.log_format or ("json" if settings.is_production else "text")).lower() == "json"
    handler.setFormatter(JsonFormatter() if use_json else
                         logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"))
    logging.getLogger("uvicorn.access").disabled = True      # replaced by the access line below

# --------------------------------------------------------------------------- headers

def response_headers(has_authorization: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    }
    if has_authorization:
        headers["Cache-Control"] = "no-store"          # personal data must not sit in shared caches
    if settings.is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers

# --------------------------------------------------------------------------- middleware

class RequestContextMiddleware:
    """Pure ASGI middleware (BaseHTTPMiddleware would lose the context variable in background work)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope["headers"])
        incoming = raw.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        has_authorization = b"authorization" in raw
        started = time.perf_counter()
        state = {"status": 500, "started": False}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"], state["started"] = message["status"], True
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in response_headers(has_authorization).items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("Unhandled error while serving %s %s", scope["method"], scope["path"])
            if not state["started"]:
                body = json.dumps({"detail": "Internal server error", "request_id": request_id}).encode()
                await send_with_headers({"type": "http.response.start", "status": 500, "headers": [
                    (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send_with_headers({"type": "http.response.body", "body": body})
        finally:
            path = scope["path"]
            level = logging.DEBUG if path.startswith(_QUIET_PATHS) else logging.INFO
            logger.log(level, "%s %s -> %s", scope["method"], path, state["status"], extra={
                "method": scope["method"], "path": path, "status": state["status"],
                "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
            request_id_var.reset(token)
