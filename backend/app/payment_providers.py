"""Payment providers.

Two checkouts exist side by side, chosen by PAYMENT_PROVIDER:

* ``demo``    the original card form + e-mailed code; no money moves and there is no provider object.
* ``sandbox`` a hosted-page flow that behaves like a real gateway (redirect out, signed webhook back, refunds
              through an API) but runs inside Parda, so the whole path is testable without merchant credentials.

A real gateway (Payme, Click, Uzum, Stripe ...) is one more class implementing ``PaymentProvider`` and one more
entry in ``get_provider``. What the rest of the app relies on, and what each adapter must therefore guarantee:

* ``parse_webhook`` authenticates the request itself (signature, replay window) and raises ``WebhookRejected``
  for anything it cannot prove came from the provider. Nothing about a payment is believed before that.
* ``WebhookEvent.event_id`` is stable across redeliveries, so a repeated callback is recognised.
* ``refund`` is idempotent for a given ``idempotency_key``: asking twice refunds once.
"""
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from secrets import token_urlsafe
from typing import Mapping, Protocol

from .config import settings
from .models import Booking, Payment

DEMO = "demo"
# Statuses of a payment row. "_demo" and plain variants mean the same thing for the demo and a real provider.
PAID = ("succeeded_demo", "succeeded")
REFUNDED = ("refunded_demo", "partially_refunded_demo", "refunded", "partially_refunded")
OPEN = ("awaiting_verification", "awaiting_provider")
PAID_OR_REFUNDED = PAID + REFUNDED

SIGNATURE_HEADER = "x-parda-signature"
TIMESTAMP_HEADER = "x-parda-timestamp"
REPLAY_WINDOW_SECONDS = 300

class WebhookRejected(Exception):
    """The callback is not provably from the provider (bad or missing signature, stale, malformed)."""

class ProviderError(Exception):
    """The provider could not do what was asked (network failure, declined refund ...)."""

@dataclass(frozen=True)
class Checkout:
    url: str
    provider_reference: str

@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    provider_reference: str
    kind: str                       # "paid" or "failed"
    amount: Decimal | None

class PaymentProvider(Protocol):
    name: str
    def create_checkout(self, payment: Payment, booking: Booking) -> Checkout: ...
    def checkout_url(self, payment: Payment) -> str: ...
    def parse_webhook(self, headers: Mapping[str, str], body: bytes, now: datetime) -> WebhookEvent: ...
    def refund(self, payment: Payment, amount: Decimal, idempotency_key: str) -> str: ...

def sign(secret: str, timestamp: int, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()

class SandboxProvider:
    name = "sandbox"
    EVENT_KINDS = {"payment.succeeded": "paid", "payment.failed": "failed"}

    def __init__(self, secret: str):
        self.secret = secret

    def create_checkout(self, payment: Payment, booking: Booking) -> Checkout:
        reference = "sbx_" + token_urlsafe(16)
        return Checkout(url=f"/api/payments/sandbox/{reference}", provider_reference=reference)

    def checkout_url(self, payment: Payment) -> str:
        return f"/api/payments/sandbox/{payment.provider_reference}"

    def signed_headers(self, body: bytes, now: datetime) -> dict[str, str]:
        timestamp = int(now.timestamp())
        return {TIMESTAMP_HEADER: str(timestamp), SIGNATURE_HEADER: sign(self.secret, timestamp, body)}

    def parse_webhook(self, headers: Mapping[str, str], body: bytes, now: datetime) -> WebhookEvent:
        lowered = {key.lower(): value for key, value in headers.items()}
        signature, stamp = lowered.get(SIGNATURE_HEADER), lowered.get(TIMESTAMP_HEADER)
        if not signature or not stamp or not self.secret:
            raise WebhookRejected("missing signature")
        try:
            timestamp = int(stamp)
        except ValueError as exc:
            raise WebhookRejected("bad timestamp") from exc
        # Verify the signature before looking at the age or the content, and compare in constant time.
        if not hmac.compare_digest(signature, sign(self.secret, timestamp, body)):
            raise WebhookRejected("signature mismatch")
        if abs(now.timestamp() - timestamp) > REPLAY_WINDOW_SECONDS:
            raise WebhookRejected("stale or future timestamp")
        try:
            data = json.loads(body)
            kind = self.EVENT_KINDS[data["type"]]
            event_id, reference = str(data["id"])[:80], str(data["reference"])[:80]
            amount = Decimal(str(data["amount"])) if data.get("amount") is not None else None
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            raise WebhookRejected("malformed event") from exc
        if not event_id or not reference:
            raise WebhookRejected("malformed event")
        return WebhookEvent(event_id=event_id, provider_reference=reference, kind=kind, amount=amount)

    def refund(self, payment: Payment, amount: Decimal, idempotency_key: str) -> str:
        # A real gateway would be called here; the same key must yield the same refund.
        return "sbx_refund_" + hashlib.sha256(f"{payment.provider_reference}:{idempotency_key}".encode()).hexdigest()[:20]

def get_provider(name: str | None = None) -> PaymentProvider | None:
    """The provider object for `name` (default: the configured one); None for the demo checkout or an unknown name."""
    name = (name or settings.payment_provider).strip().lower()
    if name == "sandbox":
        return SandboxProvider(settings.payment_webhook_secret)
    return None
