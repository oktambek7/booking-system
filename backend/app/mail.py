import hashlib
import hmac
import smtplib
from email.message import EmailMessage
from .config import settings

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
    if settings.email_mode == "mock" and settings.app_environment.lower() != "production":
        return True
    if settings.email_mode != "smtp" or not all((settings.smtp_host, settings.smtp_username,
            settings.smtp_password, settings.smtp_from)):
        raise EmailDeliveryError("Email verification is not configured")
    message = EmailMessage()
    message["Subject"] = "Parda Cinema email verification"
    message["From"] = settings.smtp_from
    message["To"] = address
    message.set_content(
        f"Your Parda Cinema verification code is {code}. It expires in 10 minutes. "
        "If you did not create this account, you can ignore this message."
    )
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
        raise EmailDeliveryError("Verification email could not be sent. Try again shortly.") from exc
    return False

def _send_email(address: str, subject: str, content: str) -> bool:
    """Return True only for a local-development mock delivery."""
    if settings.email_mode == "mock" and settings.app_environment.lower() != "production":
        return True
    if settings.email_mode != "smtp" or not all((settings.smtp_host, settings.smtp_username,
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
