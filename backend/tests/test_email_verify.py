"""E-mail verification must never act as a way to sign in."""
import uuid
from datetime import datetime, timedelta, timezone

from app.mail import email_code_hash
from tests.support import ApiTestCase, make_user, scalar, sql

class EmailVerifyTests(ApiTestCase):
    def verify(self, email, code="0000"):
        return self.client.post("/api/auth/email/verify", json={"email": email, "code": code})

    def test_an_already_verified_account_is_not_signed_in_without_a_code(self):
        """This endpoint used to start a session for any verified account, whatever code was sent."""
        victim = make_user()
        response = self.verify(victim["email"])
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn("access_token", response.text)
        self.assertNotIn("set-cookie", {key.lower() for key in response.headers})
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE user_id = :i", i=victim["id"]), 0)

    def test_a_right_code_still_verifies_and_signs_in_a_new_account(self):
        user = make_user()
        sql("UPDATE users SET email_verified = false WHERE id = :i", i=user["id"])
        sql("INSERT INTO email_otp_challenges (user_id, code_hash, expires_at, attempts) VALUES (:i, :h, :e, 0)",
            i=user["id"], h=email_code_hash(user["id"], "4821"), e=datetime.now(timezone.utc) + timedelta(minutes=10))
        self.assertEqual(self.verify(user["email"], "1111").status_code, 422)
        response = self.verify(user["email"], "4821")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("access_token", response.json())
        self.assertEqual(scalar("SELECT email_verified FROM users WHERE id = :i", i=user["id"]), True)
        # once verified, the same request is refused like for any verified account
        self.assertEqual(self.verify(user["email"], "4821").status_code, 404)

    def test_unknown_accounts_get_the_same_answer(self):
        self.assertEqual(self.verify("nobody-at-all@example.com").status_code, 404)

class RegistrationPasswordTests(ApiTestCase):
    """The password an account ends up with is the one sent together with the code that was proven."""

    def setUp(self):
        super().setUp()
        self.VICTIM = f"victim-{uuid.uuid4().hex[:10]}@example.com"

    def register(self, password, nickname=None):
        response = self.client.post("/api/auth/register", json={"email": self.VICTIM, "nickname": nickname or f"v{uuid.uuid4().hex[:8]}", "password": password})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["demo_code"]

    def verify(self, code):
        return self.client.post("/api/auth/email/verify", json={"email": self.VICTIM, "code": code})

    def login(self, password):
        return self.client.post("/api/auth/login", json={"email": self.VICTIM, "password": password})

    def test_an_attackers_earlier_registration_does_not_leave_its_password_on_the_account(self):
        self.register("attacker-chosen-pass-1", nickname=f"a{uuid.uuid4().hex[:8]}")
        victims_code = self.register("victims-own-password-2")
        response = self.verify(victims_code)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.login("attacker-chosen-pass-1").status_code, 401)
        self.assertEqual(self.login("victims-own-password-2").status_code, 200)

    def test_the_attackers_code_cannot_be_used_once_the_victim_registered(self):
        attackers_code = self.register("attacker-chosen-pass-1", nickname=f"a{uuid.uuid4().hex[:8]}")
        self.register("victims-own-password-2")
        self.assertEqual(self.verify(attackers_code).status_code, 422)
        self.assertNotEqual(self.login("victims-own-password-2").status_code, 200)    # still unverified: nobody signs in

    def test_a_single_registration_works_as_before(self):
        code = self.register("only-one-password-3")
        self.assertEqual(self.verify(code).status_code, 200)
        self.assertEqual(self.login("only-one-password-3").status_code, 200)

    def test_resending_keeps_the_password_that_was_typed(self):
        self.register("typed-password-for-resend-4")
        sql("UPDATE email_otp_challenges SET created_at = created_at - interval '5 minutes'")
        resent = self.client.post("/api/auth/email/resend", json={"email": self.VICTIM})
        self.assertEqual(resent.status_code, 200, resent.text)
        self.assertEqual(self.verify(resent.json()["demo_code"]).status_code, 200)
        self.assertEqual(self.login("typed-password-for-resend-4").status_code, 200)

    def test_a_challenge_from_before_this_change_keeps_the_accounts_own_password(self):
        user = make_user()
        sql("UPDATE users SET email_verified = false WHERE id = :i", i=user["id"])
        sql("INSERT INTO email_otp_challenges (user_id, code_hash, expires_at, attempts) VALUES (:i, :h, :e, 0)",
            i=user["id"], h=email_code_hash(user["id"], "4821"), e=datetime.now(timezone.utc) + timedelta(minutes=10))
        self.assertEqual(self.client.post("/api/auth/email/verify", json={"email": user["email"], "code": "4821"}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": user["email"], "password": "correct-horse-battery"}).status_code, 200)
