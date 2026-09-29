import hashlib
import hmac
import secrets
import httpx
from .config import settings

class SmsDeliveryError(Exception):
    pass

def new_code() -> str:
    return f"{secrets.randbelow(10_000):04d}"

def code_hash(payment_id: int, code: str) -> str:
    key = (settings.otp_secret or settings.jwt_secret).encode()
    message = f"parda-payment:{payment_id}:{code}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()

def code_matches(payment_id: int, code: str, saved_hash: str) -> bool:
    return hmac.compare_digest(code_hash(payment_id, code), saved_hash)

def send_code(phone: str, code: str) -> bool:
    """Send a four-digit code; return True only when using the explicit demo mock."""
    if settings.sms_mode == "mock":
        return True
    if settings.sms_mode != "eskiz" or not settings.sms_email or not settings.sms_password:
        raise SmsDeliveryError("SMS gateway is not configured")
    try:
        with httpx.Client(timeout=10.0) as client:
            auth = client.post(f"{settings.sms_api_url.rstrip('/')}/auth/login",
                data={"email": settings.sms_email, "password": settings.sms_password})
            auth.raise_for_status()
            token = auth.json().get("data", {}).get("token")
            if not token:
                raise SmsDeliveryError("SMS gateway authentication failed")
            result = client.post(f"{settings.sms_api_url.rstrip('/')}/message/sms/send",
                headers={"Authorization": f"Bearer {token}"},
                data={"mobile_phone": phone.removeprefix("+"),
                      "message": f"Parda Cinema: tasdiqlash kodi {code}. Kodni hech kimga bermang.",
                      "from": settings.sms_sender})
            result.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise SmsDeliveryError("SMS could not be sent. Check the phone number or try again.") from exc
    return False
