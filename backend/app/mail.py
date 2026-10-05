import hashlib
import hmac
import html
import logging
import re
import smtplib
from email.message import EmailMessage
import httpx
from .config import settings

logger = logging.getLogger(__name__)

class EmailDeliveryError(Exception):
    pass

def email_code_hash(user_id: int, code: str) -> str:
    key = (settings.otp_secret or settings.jwt_secret).encode()
    message = f"parda-email:{user_id}:{code}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()

def email_code_matches(user_id: int, code: str, saved_hash: str) -> bool:
    return hmac.compare_digest(email_code_hash(user_id, code), saved_hash)

def send_email_code(address: str, code: str) -> bool:
    """Send verification code; only development mock returns a code to the caller."""
    return _send_email(address, "Parda Cinema email verification", (
        f"Your Parda Cinema verification code is {code}. It expires in 10 minutes. "
        "If you did not create this account, you can ignore this message."
    ))

def _email_html(content: str) -> str:
    """Create a compact, readable email that makes one-time codes easy to find."""
    code_match = re.search(r"(?:code is:?|code:)\s*(\d{4,6})", content, flags=re.IGNORECASE)
    code = code_match.group(1) if code_match else None
    text = html.escape(content).replace("\n", "<br>")
    code_block = (
        f'<div style="margin:24px 0;padding:18px;border-radius:12px;background:#101827;'
        f'color:#fff;font:700 32px/1.1 Arial,sans-serif;letter-spacing:8px;text-align:center;">{code}</div>'
        if code else ""
    )
    return (
        '<!doctype html><html><body style="margin:0;padding:24px;background:#f3f5f9;">'
        '<main style="max-width:520px;margin:auto;padding:32px;border-radius:18px;background:#fff;'
        'color:#172033;font:16px/1.6 Arial,sans-serif;">'
        '<h1 style="margin:0 0 18px;font-size:24px;">Parda Cinema</h1>'
        f'{code_block}<p style="margin:0;">{text}</p>'
        '</main></body></html>'
    )

def _send_email(address: str, subject: str, content: str, *, tag: str = "parda-transactional") -> bool:
    """Return True only for a local-development mock delivery."""
    email_mode = settings.email_mode.strip().lower()
    if email_mode == "mock" and settings.app_environment.lower() != "production":
        return True
    if email_mode == "resend":
        if not all((settings.resend_api_key, settings.resend_from)):
            raise EmailDeliveryError("Email delivery is not configured")
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.resend_from, "to": [address], "subject": subject, "text": content},
                timeout=12.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Resend verification email failed (%s)", type(exc).__name__)
            raise EmailDeliveryError("Verification email could not be sent. Try again shortly.") from exc
        return False
    if email_mode == "brevo":
        if not all((settings.brevo_api_key, settings.brevo_from)):
            raise EmailDeliveryError("Email delivery is not configured")
        try:
            response = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
                json={
                    "sender": {"name": "Parda Cinema", "email": settings.brevo_from},
                    "to": [{"email": address}],
                    "subject": subject,
                    "htmlContent": _email_html(content),
                    "tags": [tag],
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Brevo verification email failed (%s)", type(exc).__name__)
            raise EmailDeliveryError("Verification email could not be sent. Try again shortly.") from exc
        return False
    if email_mode != "smtp" or not all((settings.smtp_host, settings.smtp_username,
            settings.smtp_password, settings.smtp_from)):
        raise EmailDeliveryError("Email delivery is not configured")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = address
    message.set_content(content)
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=12) as server:
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12) as server:
                server.starttls()
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("SMTP verification email failed (%s)", type(exc).__name__)
        raise EmailDeliveryError("Verification email could not be sent. Try again shortly.") from exc
    return False

def send_payment_verification_email(address: str, code: str, *, movie: str, cinema: str,
                                    starts_at: str, seats: str, amount: str) -> bool:
    return _send_email(address, "Your Cinema Payment Verification Code", (
        f"Your verification code is: {code}\n\n"
        "This code expires in 5 minutes.\n\n"
        f"Booking\nMovie: {movie}\nCinema: {cinema}\nDate / time: {starts_at}\n"
        f"Seats: {seats}\nAmount: {amount}\n\n"
        "This is a demo payment. No real money will be charged. "
        "Do not reply with card or CVV information."
    ))

def send_password_reset_email(address: str, code: str) -> bool:
    return _send_email(address, "Reset your Parda Cinema password", (
        f"Your password reset code is: {code}\n\n"
        "It expires in 10 minutes. If you did not request a password reset, you can ignore this email."
    ))

def send_booking_confirmation_email(address: str, *, movie: str, cinema: str, starts_at: str,
                                    seats: str, ticket_code: str, amount: str) -> bool:
    return _send_email(address, "Your Parda Cinema ticket is confirmed", (
        "Your ticket is confirmed. Keep this email and present the QR ticket or ticket code at entry.\n\n"
        f"Movie: {movie}\nCinema: {cinema}\nDate / time: {starts_at}\n"
        f"Seats: {seats}\nTicket code: {ticket_code}\nAmount: {amount}\n\n"
        "We will send reminders before the screening."
    ), tag="parda-booking-confirmation")

def send_screening_reminder_email(address: str, *, movie: str, cinema: str, starts_at: str,
                                  seats: str, ticket_code: str, when: str) -> bool:
    return _send_email(address, f"Reminder: {movie} starts {when}", (
        f"Your Parda Cinema screening starts {when}.\n\n"
        f"Movie: {movie}\nCinema: {cinema}\nDate / time: {starts_at}\n"
        f"Seats: {seats}\nTicket code: {ticket_code}\n\n"
        "Please arrive early and show your QR ticket or ticket code at entry."
    ), tag="parda-screening-reminder")
