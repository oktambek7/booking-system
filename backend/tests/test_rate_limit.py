"""Rate-limit behaviour against a real PostgreSQL (set DATABASE_URL; skipped if unreachable)."""
import unittest
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import ratelimit
from app.config import settings
from app.database import SessionLocal, engine
from app.main import app
from app.models import Role, User
from app.security import hash_password

def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def _request(headers=None, host="10.1.2.3"):
    return SimpleNamespace(headers={k.lower(): v for k, v in (headers or {}).items()},
                           client=SimpleNamespace(host=host))

class ClientIpTests(unittest.TestCase):
    def setUp(self):
        self.original = settings.client_ip_header

    def tearDown(self):
        settings.client_ip_header = self.original

    def test_socket_peer_used_when_no_header_configured(self):
        settings.client_ip_header = ""
        self.assertEqual(ratelimit.client_ip(_request({"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "9.9.9.9"})), "10.1.2.3")

    def test_configured_header_is_used(self):
        settings.client_ip_header = "cf-connecting-ip"
        self.assertEqual(ratelimit.client_ip(_request({"CF-Connecting-IP": "203.0.113.7"})), "203.0.113.7")

    def test_invalid_or_missing_header_falls_back_to_socket_peer(self):
        settings.client_ip_header = "cf-connecting-ip"
        self.assertEqual(ratelimit.client_ip(_request({"cf-connecting-ip": "not-an-ip"})), "10.1.2.3")
        self.assertEqual(ratelimit.client_ip(_request()), "10.1.2.3")

@unittest.skipUnless(_db_available(), "PostgreSQL not reachable")
class RateLimitDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()          # runs lifespan: creates tables / applies migrations
        cls.emails: list[str] = []

    @classmethod
    def tearDownClass(cls):
        with SessionLocal() as db:
            db.execute(text("DELETE FROM users WHERE email = ANY(:e)"), {"e": cls.emails})
            db.commit()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_buckets"))
        cls.client.__exit__(None, None, None)

    def _user(self, password="correct-horse-battery") -> str:
        email = f"rl-{uuid.uuid4().hex[:10]}@example.com"
        with SessionLocal() as db:
            db.add(User(email=email, name=email[:20], nickname=email[:20], role=Role.CUSTOMER,
                        password_hash=hash_password(password), active=True, email_verified=True))
            db.commit()
        self.emails.append(email)
        return email

    def _login(self, email, password):
        return self.client.post("/api/auth/login", json={"email": email, "password": password})

    def test_hit_blocks_after_limit_with_retry_after(self):
        key = uuid.uuid4().hex
        for _ in range(3):
            ratelimit.hit("t-hit", key, 3, 60)
        with self.assertRaises(HTTPException) as ctx:
            ratelimit.hit("t-hit", key, 3, 60)
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertTrue(1 <= int(ctx.exception.headers["Retry-After"]) <= 60)
        ratelimit.hit("t-hit", uuid.uuid4().hex, 3, 60)   # other keys are unaffected

    def test_window_expiry_resets_counter(self):
        key = uuid.uuid4().hex
        for _ in range(2):
            ratelimit.hit("t-win", key, 2, 60)
        with engine.begin() as conn:
            conn.execute(text("UPDATE rate_limit_buckets SET window_start = now() - interval '2 minutes'"))
        ratelimit.hit("t-win", key, 2, 60)

    def test_login_locks_after_repeated_failures_even_with_correct_password(self):
        email = self._user()
        for _ in range(5):
            self.assertEqual(self._login(email, "wrong-password").status_code, 401)
        locked = self._login(email, "correct-horse-battery")
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Retry-After", locked.headers)
        self.assertEqual(self._login(self._user(), "correct-horse-battery").status_code, 200)  # other accounts fine

    def test_successful_login_clears_the_failure_counter(self):
        email = self._user()
        for _ in range(4):
            self.assertEqual(self._login(email, "wrong-password").status_code, 401)
        self.assertEqual(self._login(email, "correct-horse-battery").status_code, 200)
        for _ in range(4):
            self.assertEqual(self._login(email, "wrong-password").status_code, 401)

    def test_unknown_email_failures_are_counted_too(self):
        email = f"ghost-{uuid.uuid4().hex[:8]}@example.com"
        codes = [self._login(email, "whatever-password").status_code for _ in range(6)]
        self.assertEqual(codes, [401] * 5 + [429])

    def test_email_code_guessing_is_locked_per_account(self):
        email = self._user()
        with SessionLocal() as db:
            db.execute(text("UPDATE users SET email_verified = false WHERE email = :e"), {"e": email})
            db.commit()
        # Without a live challenge the endpoint answers 410; pre-seed failures directly.
        for _ in range(10):
            ratelimit.record_failure("email-verify-fail", email, 1800)
        resp = self.client.post("/api/auth/email/verify", json={"email": email, "code": "0000"})
        self.assertEqual(resp.status_code, 429)

    def test_disabled_limiter_never_blocks(self):
        settings.rate_limit_enabled = False
        try:
            key = uuid.uuid4().hex
            for _ in range(10):
                ratelimit.hit("t-off", key, 1, 60)
        finally:
            settings.rate_limit_enabled = True

if __name__ == "__main__":
    unittest.main()
