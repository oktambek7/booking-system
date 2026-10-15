"""E-mail verification must never act as a way to sign in."""
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
