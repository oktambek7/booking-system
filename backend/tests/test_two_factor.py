"""Two-step verification: the TOTP maths, enrolment, sign-in, recovery codes, and operator enforcement."""
import time
import unittest
from unittest import mock

import jwt

from app import totp
from app.config import settings
from app.models import Role
from tests.support import ApiTestCase, auth, make_hall, make_screening, make_user, scalar, sql

PASSWORD = "correct-horse-battery"
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # ASCII "12345678901234567890", the RFC 6238 test key

class TotpMathTests(unittest.TestCase):
    def test_matches_the_rfc_6238_test_vectors(self):
        for at, expected in ((59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"),
                             (2000000000, "279037"), (20000000000, "353130")):
            with self.subTest(at=at):
                self.assertEqual(totp.code_at(RFC_SECRET, at), expected)

    def test_a_code_is_accepted_one_step_either_side_but_not_further(self):
        now = 1_700_000_000
        for offset, ok in ((0, True), (-30, True), (30, True), (-60, False), (60, False)):
            with self.subTest(offset=offset):
                step = totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, now + offset), now=now)
                self.assertEqual(step is not None, ok)

    def test_a_code_cannot_be_used_twice(self):
        now = 1_700_000_000
        code = totp.code_at(RFC_SECRET, now)
        step = totp.verify(RFC_SECRET, code, now=now)
        self.assertIsNotNone(step)
        self.assertIsNone(totp.verify(RFC_SECRET, code, last_step=step, now=now))
        self.assertIsNone(totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, now - 30), last_step=step, now=now))   # older step either
        self.assertIsNotNone(totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, now + 30), last_step=step, now=now))

    def test_malformed_codes_are_rejected_without_error(self):
        for code in ("", "12345", "1234567", "abcdef", "12 34 5", "١٢٣٤٥٦"):
            self.assertIsNone(totp.verify(RFC_SECRET, code, now=1_700_000_000), code)

    def test_spaces_in_a_pasted_code_are_ignored(self):
        code = totp.code_at(RFC_SECRET, 1_700_000_000)
        self.assertIsNotNone(totp.verify(RFC_SECRET, f"{code[:3]} {code[3:]}", now=1_700_000_000))

    def test_secrets_are_encrypted_and_only_readable_with_the_same_key(self):
        secret = totp.new_secret()
        stored = totp.encrypt(secret)
        self.assertNotIn(secret, stored)
        self.assertEqual(totp.decrypt(stored), secret)
        with mock.patch.object(settings, "totp_encryption_key", "another-key-entirely-0123456789abcdef"):
            self.assertIsNone(totp.decrypt(stored))

    def test_recovery_codes_are_unique_readable_and_hashed_regardless_of_formatting(self):
        codes = totp.new_recovery_codes()
        self.assertEqual((len(codes), len(set(codes))), (10, 10))
        self.assertRegex(codes[0], r"^[a-z2-9]{5}-[a-z2-9]{5}$")
        self.assertEqual(totp.recovery_hash(codes[0]), totp.recovery_hash(codes[0].upper().replace("-", " ")))
        self.assertTrue(totp.looks_like_recovery_code(codes[0]))
        self.assertFalse(totp.looks_like_recovery_code("123456"))

    def test_the_otpauth_uri_names_the_issuer_and_account(self):
        uri = totp.otpauth_uri("ABC", "me@example.com")
        self.assertTrue(uri.startswith("otpauth://totp/Phantora%3Ame%40example.com?secret=ABC&issuer=Phantora"))

class TwoFactorCase(ApiTestCase):
    def setUp(self):
        sql("DELETE FROM rate_limit_buckets")
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")

    def user(self, role=Role.CUSTOMER):
        return make_user(role=role)

    def post(self, path, headers=None, **body):
        return self.client.post(path, headers=headers, json=body)

    def enrol(self, user) -> tuple[str, list[str], str]:
        """Turn on two-step verification; returns (secret, recovery codes, a token for the session that did it)."""
        headers = auth(user["token"])
        setup = self.post("/api/auth/2fa/setup", headers, password=PASSWORD)
        self.assertEqual(setup.status_code, 200, setup.text)
        secret = setup.json()["secret"]
        enabled = self.post("/api/auth/2fa/enable", headers, code=totp.code_at(secret, time.time()))
        self.assertEqual(enabled.status_code, 200, enabled.text)
        return secret, enabled.json()["recovery_codes"], enabled.json()["access_token"]

    def next_code(self, secret):
        """A valid code that has not been used yet (the next time step is accepted, then the clock moves on)."""
        sql("UPDATE user_totp SET last_step = NULL")
        return totp.code_at(secret, time.time())

    def login(self, user):
        return self.post("/api/auth/login", email=user["email"], password=PASSWORD)

    def second_step(self, challenge, code):
        return self.post("/api/auth/login/2fa", challenge=challenge, code=code)

class EnrolmentTests(TwoFactorCase):
    def test_status_starts_off_and_setup_needs_the_password(self):
        user = self.user()
        headers = auth(user["token"])
        self.assertEqual(self.client.get("/api/auth/2fa", headers=headers).json(), {"enabled": False, "recovery_codes_left": 0, "required": False})
        self.assertEqual(self.post("/api/auth/2fa/setup", headers, password="wrong-password-here").status_code, 403)
        self.assertEqual(scalar("SELECT count(*) FROM user_totp WHERE user_id = :i", i=user["id"]), 0)

    def test_a_pending_setup_changes_nothing_until_a_code_is_confirmed(self):
        user = self.user()
        self.post("/api/auth/2fa/setup", auth(user["token"]), password=PASSWORD)
        self.assertEqual(self.login(user).json()["two_factor_required"], False)               # still a normal sign-in
        self.assertEqual(self.client.get("/api/auth/2fa", headers=auth(user["token"])).json()["enabled"], False)

    def test_a_wrong_code_does_not_enable_it(self):
        user = self.user()
        self.post("/api/auth/2fa/setup", auth(user["token"]), password=PASSWORD)
        self.assertEqual(self.post("/api/auth/2fa/enable", auth(user["token"]), code="000000").status_code, 422)
        self.assertIsNone(scalar("SELECT confirmed_at FROM user_totp WHERE user_id = :i", i=user["id"]))

    def test_enabling_returns_recovery_codes_once_and_stores_secrets_encrypted(self):
        user = self.user()
        secret, codes, _ = self.enrol(user)
        self.assertEqual(len(codes), 10)
        stored = scalar("SELECT secret_enc FROM user_totp WHERE user_id = :i", i=user["id"])
        self.assertNotIn(secret, stored)
        hashes = {r[0] for r in sql("SELECT code_hash FROM totp_recovery_codes WHERE user_id = :i", i=user["id"])}
        self.assertEqual(len(hashes), 10)
        self.assertFalse(any(code.replace("-", "") in h for code in codes for h in hashes))
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE action = '2fa.enabled' AND target_id = :i", i=str(user["id"])), 1)

    def test_enabling_signs_out_other_devices_but_keeps_this_one(self):
        user = self.user()
        other_device = auth(user["token"])
        _, _, fresh = self.enrol(user)
        self.assertEqual(self.client.get("/api/auth/me", headers=other_device).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me", headers=auth(fresh)).status_code, 200)
        self.assertTrue(jwt.decode(fresh, settings.jwt_secret, algorithms=["HS256"])["mfa"])

    def test_it_cannot_be_enrolled_twice(self):
        user = self.user()
        _, _, fresh = self.enrol(user)
        self.assertEqual(self.post("/api/auth/2fa/setup", auth(fresh), password=PASSWORD).status_code, 409)

class SignInTests(TwoFactorCase):
    def setUp(self):
        super().setUp()
        self.account = self.user()
        self.secret, self.codes, _ = self.enrol(self.account)

    def challenge(self):
        response = self.login(self.account)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["two_factor_required"], body["access_token"]), (True, None))
        self.assertNotIn("set-cookie", {k.lower() for k in response.headers})              # no session yet
        return body["challenge"]

    def test_the_password_alone_does_not_sign_in(self):
        self.challenge()
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE user_id = :i AND created_at > now() - interval '1 minute' AND mfa = false", i=self.account["id"]), 0)

    def test_a_right_code_completes_the_sign_in_with_an_mfa_session(self):
        response = self.second_step(self.challenge(), self.next_code(self.secret))
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        self.assertTrue(jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["mfa"])
        self.assertIn("parda_refresh", response.cookies)
        self.assertEqual(self.client.get("/api/auth/me", headers=auth(token)).status_code, 200)
        self.assertEqual(scalar("SELECT mfa FROM refresh_tokens WHERE user_id = :i ORDER BY id DESC LIMIT 1", i=self.account["id"]), True)

    def test_refreshing_keeps_the_mfa_mark(self):
        self.second_step(self.challenge(), self.next_code(self.secret))
        for _ in range(2):                    # the mark must survive every rotation, not only the first
            refreshed = self.client.post("/api/auth/refresh", headers={"Sec-Fetch-Site": "same-origin"})
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            self.assertTrue(jwt.decode(refreshed.json()["access_token"], settings.jwt_secret, algorithms=["HS256"])["mfa"])
        self.client.cookies.clear()

    def test_a_wrong_code_is_refused_and_locks_after_five_tries(self):
        challenge = self.challenge()
        for _ in range(5):
            self.assertEqual(self.second_step(challenge, "000000").status_code, 422)
        locked = self.second_step(challenge, self.next_code(self.secret))
        self.assertEqual(locked.status_code, 429)                                           # even the right code, now

    def test_the_same_code_cannot_sign_in_twice(self):
        code = self.next_code(self.secret)
        self.assertEqual(self.second_step(self.challenge(), code).status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.second_step(self.challenge(), code).status_code, 422)

    def test_a_recovery_code_works_exactly_once(self):
        first = self.second_step(self.challenge(), self.codes[0])
        self.assertEqual(first.status_code, 200, first.text)
        self.client.cookies.clear()
        self.assertEqual(self.second_step(self.challenge(), self.codes[0]).status_code, 422)
        self.assertEqual(self.client.get("/api/auth/2fa", headers=auth(first.json()["access_token"])).json()["recovery_codes_left"], 9)
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE action = '2fa.recovery_code_used' AND target_id = :i", i=str(self.account["id"])), 1)

    def test_a_recovery_code_is_accepted_however_it_is_typed(self):
        self.assertEqual(self.second_step(self.challenge(), self.codes[1].upper().replace("-", " ")).status_code, 200)

    def test_challenges_are_not_sessions_and_sessions_are_not_challenges(self):
        challenge = self.challenge()
        self.assertEqual(self.client.get("/api/auth/me", headers=auth(challenge)).status_code, 401)
        self.assertEqual(self.second_step(self.account["token"], "000000").status_code, 401)
        self.assertEqual(self.second_step("not-a-token-at-all", "000000").status_code, 401)

    def test_a_challenge_dies_when_the_account_signs_out_everywhere(self):
        challenge = self.challenge()
        sql("UPDATE users SET token_version = token_version + 1 WHERE id = :i", i=self.account["id"])
        self.assertEqual(self.second_step(challenge, self.next_code(self.secret)).status_code, 401)

    def test_an_expired_challenge_is_refused(self):
        with mock.patch("app.twofactor.CHALLENGE_MINUTES", -1):
            challenge = self.challenge()
        self.assertEqual(self.second_step(challenge, self.next_code(self.secret)).status_code, 401)

class ManagementTests(TwoFactorCase):
    def setUp(self):
        super().setUp()
        self.account = self.user()
        self.secret, self.codes, self.token = self.enrol(self.account)
        self.headers = auth(self.token)

    def test_disabling_needs_the_password_and_a_code_and_ends_other_sessions(self):
        self.assertEqual(self.post("/api/auth/2fa/disable", self.headers, password="nope-nope-nope", code=self.next_code(self.secret)).status_code, 403)
        self.assertEqual(self.post("/api/auth/2fa/disable", self.headers, password=PASSWORD, code="000000").status_code, 422)
        self.assertEqual(self.post("/api/auth/2fa/disable", self.headers, password=PASSWORD, code=self.next_code(self.secret)).status_code, 204)
        self.assertEqual(scalar("SELECT count(*) FROM user_totp WHERE user_id = :i", i=self.account["id"]), 0)
        self.assertEqual(scalar("SELECT count(*) FROM totp_recovery_codes WHERE user_id = :i", i=self.account["id"]), 0)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers).status_code, 401)
        self.assertEqual(self.login(self.account).json()["two_factor_required"], False)

    def test_a_stolen_session_alone_cannot_turn_it_off(self):
        self.assertEqual(self.post("/api/auth/2fa/disable", self.headers, password=PASSWORD, code="123456").status_code, 422)
        self.assertEqual(scalar("SELECT count(*) FROM user_totp WHERE user_id = :i", i=self.account["id"]), 1)

    def test_recovery_codes_can_be_replaced_and_the_old_ones_stop_working(self):
        response = self.post("/api/auth/2fa/recovery-codes", self.headers, password=PASSWORD, code=self.next_code(self.secret))
        self.assertEqual(response.status_code, 200, response.text)
        fresh = response.json()["recovery_codes"]
        self.assertEqual(len(fresh), 10)
        challenge = self.login(self.account).json()["challenge"]
        self.assertEqual(self.second_step(challenge, self.codes[0]).status_code, 422)
        self.assertEqual(self.second_step(challenge, fresh[0]).status_code, 200)

    def test_failed_attempts_on_any_second_step_share_one_lockout(self):
        for _ in range(5):
            self.post("/api/auth/2fa/disable", self.headers, password=PASSWORD, code="000000")
        self.assertEqual(self.post("/api/auth/2fa/disable", self.headers, password=PASSWORD, code=self.next_code(self.secret)).status_code, 429)

    def test_deleting_the_account_removes_the_secrets(self):
        sql("DELETE FROM users WHERE id = :i", i=self.account["id"])
        self.assertEqual(scalar("SELECT count(*) FROM user_totp WHERE user_id = :i", i=self.account["id"]), 0)
        self.assertEqual(scalar("SELECT count(*) FROM totp_recovery_codes WHERE user_id = :i", i=self.account["id"]), 0)

class OperatorEnforcementTests(TwoFactorCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(settings, "require_operator_2fa", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.operator = self.user(Role.ADMIN)
        self.hall = make_hall()
        self.screening = make_screening(self.hall)
        self.customer = self.shop()
        self.booking = self.customer.book(self.screening, [self.hall["seat_ids"][0]]).json()["id"]

    def test_an_operator_without_the_second_step_gets_no_operator_powers(self):
        plain = auth(self.operator["token"])                 # a token minted without mfa
        for path in ("/api/admin/cinemas", "/api/admin/promotions", "/api/admin/operators", "/api/admin/audit-log"):
            with self.subTest(path=path):
                response = self.client.get(path, headers=plain)
                self.assertEqual(response.status_code, 403)
                self.assertIn("two-step", response.json()["detail"].lower())

    def test_they_also_cannot_read_or_cancel_other_customers_bookings_through_the_customer_routes(self):
        plain = auth(self.operator["token"])
        listed = {b["id"] for b in self.client.get("/api/bookings", headers=plain).json()}
        self.assertNotIn(self.booking, listed)
        self.assertEqual(self.client.get(f"/api/bookings/{self.booking}/cancellation-quote", headers=plain).status_code, 404)
        response = self.client.patch(f"/api/bookings/{self.booking}/status", headers=plain, json={"status": "cancelled"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(str(scalar("SELECT status FROM bookings WHERE id = :i", i=self.booking)).lower(), "pending")

    def test_with_the_second_step_everything_works_again(self):
        secret, _, token = self.enrol(self.operator)
        headers = auth(token)
        self.assertEqual(self.client.get("/api/admin/cinemas", headers=headers).status_code, 200)
        self.assertIn(self.booking, {b["id"] for b in self.client.get("/api/bookings", headers=headers).json()})
        response = self.client.patch(f"/api/bookings/{self.booking}/status", headers=headers, json={"status": "cancelled"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_signing_in_with_the_second_step_gives_an_operator_token(self):
        secret, _, _ = self.enrol(self.operator)
        challenge = self.login(self.operator).json()["challenge"]
        token = self.second_step(challenge, self.next_code(secret)).json()["access_token"]
        self.assertEqual(self.client.get("/api/admin/cinemas", headers=auth(token)).status_code, 200)

    def test_operators_cannot_turn_it_off_and_status_says_it_is_required(self):
        secret, _, token = self.enrol(self.operator)
        headers = auth(token)
        self.assertTrue(self.client.get("/api/auth/2fa", headers=headers).json()["required"])
        self.assertEqual(self.post("/api/auth/2fa/disable", headers, password=PASSWORD, code=self.next_code(secret)).status_code, 409)

    def test_customers_are_unaffected_by_the_requirement(self):
        self.assertEqual(self.client.get("/api/bookings", headers=self.customer.headers).status_code, 200)

    def test_when_the_requirement_is_off_a_plain_operator_token_still_works(self):
        with mock.patch.object(settings, "require_operator_2fa", False):
            self.assertEqual(self.client.get("/api/admin/cinemas", headers=auth(self.operator["token"])).status_code, 200)
