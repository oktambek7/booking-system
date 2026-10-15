"""Optional error reporting to Sentry. Off unless SENTRY_DSN is set.

Parda handles tickets, e-mail addresses and sign-in tokens, so nothing personal is sent: no default PII, and every
event is scrubbed of cookies, authorization headers, request bodies and query strings before it leaves the server.
"""
import logging

from .config import settings

logger = logging.getLogger(__name__)

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-forwarded-for", "x-real-ip", "cf-connecting-ip",
                     "x-vercel-forwarded-for", "true-client-ip", "x-parda-signature"}

def scrub_event(event: dict, hint: dict | None = None) -> dict:
    """Remove what must never reach a third party from a Sentry event."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        request.pop("data", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}
        if isinstance(request.get("url"), str):
            request["url"] = request["url"].split("?", 1)[0]
    event.pop("user", None)
    return event

def init_sentry() -> bool:
    """Start Sentry when configured. Returns whether it is on. Never raises: monitoring must not stop the API."""
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_environment, release=settings.sentry_release or None,
                        traces_sample_rate=settings.sentry_traces_sample_rate, send_default_pii=False,
                        before_send=scrub_event, max_request_body_size="never")
    except Exception:
        logger.exception("Sentry could not be started; continuing without it")
        return False
    logger.info("Error reporting to Sentry is on")
    return True
