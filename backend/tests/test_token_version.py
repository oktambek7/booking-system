"""Access-token revocation against a real PostgreSQL (set DATABASE_URL; skipped if unreachable)."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, engine
from app.main import app
from app.models import Role, User
from app.security import hash_password, make_token

PASSWORD = "correct-horse-battery"

def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

@unittest.skipUnless(_db_available(), "PostgreSQL not reachable")
class TokenVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.emails: list[str] = []

    @classmethod
    def tearDownClass(cls):
        with SessionLocal() as db:
            db.execute(text("DELETE FROM users WHERE email = ANY(:e)"), {"e": cls.emails})
            db.commit()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_buckets"))
        cls.client.__exit__(None, None, None)

    def _user(self) -> User:
        email = f"tv-{uuid.uuid4().hex[:10]}@example.com"
        with SessionLocal() as db:
            user = User(email=email, name=email[:20], nickname=email[:20], role=Role.CUSTOMER,
                        password_hash=hash_password(PASSWORD), active=True, email_verified=True)
            db.add(user)
            db.commit()
        self.emails.append(email)
        return user

    def _login(self, email: str) -> str:
        resp = self.client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["access_token"]

    def _me(self, token: str) -> int:
        return self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code

    def test_login_token_carries_current_version(self):
        user = self._user()
        claims = jwt.decode(self._login(user.email), settings.jwt_secret, algorithms=["HS256"])
        self.assertEqual(claims["tv"], 0)

    def test_token_without_version_claim_still_works_for_unrevoked_user(self):
        user = self._user()
        now = datetime.now(timezone.utc)
        legacy = jwt.encode({"sub": str(user.id), "role": "customer", "iat": now, "exp": now + timedelta(hours=1)},
                            settings.jwt_secret, algorithm="HS256")
        self.assertEqual(self._me(legacy), 200)

    def test_logout_all_revokes_every_earlier_token(self):
        user = self._user()
        first, second = self._login(user.email), self._login(user.email)
        self.assertEqual(self._me(first), 200)
        resp = self.client.post("/api/auth/logout-all", headers={"Authorization": f"Bearer {first}"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self._me(first), 401)
        self.assertEqual(self._me(second), 401)
        self.assertEqual(self._me(self._login(user.email)), 200)     # signing in again works

    def test_password_reset_revokes_existing_sessions(self):
        user = self._user()
        old = self._login(user.email)
        started = self.client.post("/api/auth/password-reset/request", json={"email": user.email})
        self.assertEqual(started.status_code, 200, started.text)
        code = started.json()["demo_code"]
        self.assertTrue(code, "development mode should return the mock code")
        done = self.client.post("/api/auth/password-reset/confirm",
                                json={"email": user.email, "code": code, "password": "brand-new-password-1"})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self._me(old), 401)

    def test_forged_or_stale_version_is_rejected(self):
        user = self._user()
        now = datetime.now(timezone.utc)
        for version in (1, 99):
            with self.subTest(version=version):
                token = jwt.encode({"sub": str(user.id), "tv": version, "iat": now, "exp": now + timedelta(hours=1)},
                                   settings.jwt_secret, algorithm="HS256")
                self.assertEqual(self._me(token), 401)

    def test_deactivated_account_token_is_rejected(self):
        user = self._user()
        token = self._login(user.email)
        with SessionLocal() as db:
            db.execute(text("UPDATE users SET active = false WHERE id = :i"), {"i": user.id})
            db.commit()
        self.assertEqual(self._me(token), 401)

    def test_logout_all_requires_authentication(self):
        self.assertIn(self.client.post("/api/auth/logout-all").status_code, (401, 403))

if __name__ == "__main__":
    unittest.main()
