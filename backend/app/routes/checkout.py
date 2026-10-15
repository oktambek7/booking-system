"""Hosted-checkout payments: start a payment, receive the provider's signed webhook, report the outcome.

The browser is never trusted to say a payment succeeded. It is sent to the provider's page, and the booking is
confirmed only when a signed callback from the provider reaches `/payments/webhook/{provider}`.
"""
import html
import json
import logging
from datetime import datetime, timezone
from secrets import token_urlsafe
from urllib.parse import parse_qs

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..checkout import ensure_payable, handle_webhook, start_checkout
from ..config import settings
from ..database import get_db
from ..models import Booking, Payment, User
from ..notifications import deliver_due_notifications
from ..payment_providers import OPEN, PAID_OR_REFUNDED, SandboxProvider, WebhookRejected, get_provider
from ..schemas import CheckoutIn, CheckoutOut, PaymentConfigOut, PaymentStatusOut
from ..security import current_user
from ..services import booking_out, owned_pending_booking

router = APIRouter()
logger = logging.getLogger("parda.payments")

MAX_WEBHOOK_BYTES = 64 * 1024

def _checkout_out(payment: Payment, provider) -> CheckoutOut:
    url = provider.checkout_url(payment) if payment.status == "awaiting_provider" else None
    return CheckoutOut(payment_id=payment.id, reference=payment.reference, status=payment.status,
                       amount=payment.amount, checkout_url=url)

@router.get("/payments/config", response_model=PaymentConfigOut)
def payment_config():
    """Which checkout the app should show: the card form ("demo") or a redirect to a hosted page."""
    return PaymentConfigOut(provider=settings.payment_provider.strip().lower())

@router.post("/payments/checkout", response_model=CheckoutOut, status_code=201)
def create_checkout(data: CheckoutIn, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user),
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=80,
                                                         pattern=r"^[A-Za-z0-9_\-]+$")):
    provider = get_provider()
    if provider is None:
        raise HTTPException(409, "This server uses the card checkout, not a hosted payment page")
    if idempotency_key:
        # The same key from the same customer for the same booking is the same request: answer it again,
        # even when the booking has moved on since (paid, expired), instead of creating a second payment.
        previous = db.scalar(sa.select(Payment).join(Booking, Booking.id == Payment.booking_id).where(
            Payment.booking_id == data.booking_id, Payment.idempotency_key == idempotency_key,
            Booking.customer_id == user.id))
        if previous:
            response.status_code = 200
            return _checkout_out(previous, provider)
    booking = owned_pending_booking(data.booking_id, db, user, lock=True)
    ensure_payable(db, booking, user)
    open_payment = db.scalar(sa.select(Payment).where(Payment.booking_id == booking.id, Payment.status.in_(OPEN)).with_for_update())
    if open_payment:
        if open_payment.status == "awaiting_provider" and open_payment.provider == provider.name:
            response.status_code = 200            # the customer came back: resume the open payment
            return _checkout_out(open_payment, provider)
        raise HTTPException(409, "A payment verification is already in progress for this booking")
    payment = start_checkout(db, provider, booking, idempotency_key)
    db.commit()
    return _checkout_out(payment, provider)

@router.get("/payments/by-reference/{reference}", response_model=PaymentStatusOut)
def payment_status(reference: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Where the customer lands after the hosted page: the webhook may still be on its way, so the app polls this."""
    payment = db.scalar(sa.select(Payment).join(Booking, Booking.id == Payment.booking_id).where(
        Payment.reference == reference, Booking.customer_id == user.id))
    if not payment:
        raise HTTPException(404, "Payment not found")
    booking = booking_out(payment.booking) if payment.status in PAID_OR_REFUNDED else None
    return PaymentStatusOut(payment_id=payment.id, reference=payment.reference, status=payment.status, booking=booking)

@router.post("/payments/webhook/{provider_name}")
async def payment_webhook(provider_name: str, request: Request, background_tasks: BackgroundTasks,
                          db: Session = Depends(get_db)):
    provider = get_provider()
    if provider is None or provider.name != provider_name:
        raise HTTPException(404, "Unknown payment provider")
    if int(request.headers.get("content-length") or 0) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Webhook too large")
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Webhook too large")
    try:
        outcome = await run_in_threadpool(handle_webhook, db, provider, request.headers, body)
    except WebhookRejected as exc:
        logger.warning("rejected %s webhook: %s", provider_name, exc)
        raise HTTPException(400, "Invalid webhook") from exc
    if outcome == "applied":
        background_tasks.add_task(deliver_due_notifications)
    return {"status": outcome}

# ---- the sandbox provider's hosted page (development only; the production validator refuses PAYMENT_PROVIDER=sandbox) ----

def _sandbox_payment(db: Session, reference: str) -> Payment:
    provider = get_provider()
    payment = db.scalar(sa.select(Payment).where(Payment.provider == "sandbox", Payment.provider_reference == reference))
    if not isinstance(provider, SandboxProvider) or not payment:
        raise HTTPException(404, "Payment not found")
    return payment

def _page(body: str) -> HTMLResponse:
    document = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>Parda sandbox payment</title><style>body{font:16px system-ui;max-width:26rem;margin:12vh auto;padding:0 1rem;"
                "background:#0a0a18;color:#eee}button{font:inherit;padding:.7rem 1.2rem;margin:.3rem .3rem 0 0;border-radius:.6rem;"
                "border:0;cursor:pointer}.ok{background:#7c5cff;color:#fff}.no{background:#333;color:#eee}</style>" + body)
    return HTMLResponse(document, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
                                           "Cache-Control": "no-store"})

@router.get("/payments/sandbox/{reference}")
def sandbox_page(reference: str, db: Session = Depends(get_db)):
    payment = _sandbox_payment(db, reference)
    booking = payment.booking
    if payment.status != "awaiting_provider":
        return _page(f"<h1>Payment {html.escape(payment.status)}</h1><p>This payment is already settled.</p>")
    return _page(
        f"<h1>Sandbox payment</h1><p>{html.escape(booking.screening.movie.title)}</p>"
        f"<p><b>{payment.amount:,.0f} UZS</b></p><p>No real money moves. Choose how this payment ends.</p>"
        "<form method=post><button class=ok name=outcome value=paid>Pay</button>"
        "<button class=no name=outcome value=failed>Cancel</button></form>")

@router.post("/payments/sandbox/{reference}")
async def sandbox_settle(reference: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """What a real gateway does when the customer finishes on its page: send a signed webhook, then redirect back."""
    payment = _sandbox_payment(db, reference)
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Request too large")
    form = parse_qs(raw.decode("utf-8", "ignore"))
    outcome = (form.get("outcome") or [""])[0]
    if outcome not in ("paid", "failed"):
        raise HTTPException(422, "Choose pay or cancel")
    provider = get_provider()
    body = json.dumps({"id": "evt_" + token_urlsafe(12), "type": "payment.succeeded" if outcome == "paid" else "payment.failed",
                       "reference": reference, "amount": str(payment.amount)}).encode()
    headers = provider.signed_headers(body, datetime.now(timezone.utc))
    result = await run_in_threadpool(handle_webhook, db, provider, headers, body)
    if result == "applied":
        background_tasks.add_task(deliver_due_notifications)
    origin = (settings.payment_return_url or settings.cors_origins.split(",")[0]).strip().rstrip("/")
    return RedirectResponse(f"{origin}/?payment={payment.reference}", status_code=303)
