"""Rotating httpOnly refresh-token sessions."""
import unittest

from app.config import settings
from app.sessions import COOKIE_NAME, purge_expired_refresh_tokens
from tests.support import ApiTestCase, auth, make_user, run_parallel, scalar, sql

PASSWORD = "correct-horse-battery"

class SessionCase(ApiTestCase):
    def setUp(self):
        self.client.cookies.clear()
        self.addCleanup(self.client.cookies.clear)

    def sign_in(self, user=None):
        user = user or make_user()
        resp = self.client.post("/api/auth/login", json={"email": user["email"], "password": PASSWORD})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.client.cookies.clear()                       # tests pass the cookie explicitly
        return user, resp, resp.cookies[COOKIE_NAME]

    def refresh(self, token, **headers):
        return self.client.post("/api/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={token}", **headers})

    def me(self, access):
        return self.client.get("/api/auth/me", headers=auth(access)).status_code

    @staticmethod
    def new_cookie(resp):
        return resp.cookies.get(COOKIE_NAME)

class CookieTests(SessionCase):
    def test_login_sets_a_locked_down_refresh_cookie_and_keeps_it_out_of_the_body(self):
        _, resp, token = self.sign_in()
        header = next(h for h in resp.headers.get_list("set-cookie") if h.startswith(COOKIE_NAME))
        for attribute in ("HttpOnly", "Path=/api/auth", "SameSite=strict"):
            self.assertIn(attribute, header)
        self.assertNotIn("Secure", header)               # plain http in development
        self.assertGreater(int(header.split("Max-Age=")[1].split(";")[0]), 29 * 86400)
        self.assertNotIn(token, resp.text)
        self.assertEqual(resp.json()["expires_in"], settings.jwt_expire_minutes * 60)

    def test_the_cookie_is_secure_in_production(self):
        settings.app_environment = "production"
        try:
            _, resp, _ = self.sign_in()
        finally:
            settings.app_environment = "development"
        self.assertIn("Secure", next(h for h in resp.headers.get_list("set-cookie") if h.startswith(COOKIE_NAME)))

    def test_only_a_hash_of_the_token_is_stored(self):
        user, _, token = self.sign_in()
        stored = scalar("SELECT token_hash FROM refresh_tokens WHERE user_id = :u", u=user["id"])
        self.assertEqual(len(stored), 64)
        self.assertNotEqual(stored, token)
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE token_hash = :t", t=token), 0)

    def test_email_verification_also_signs_in(self):
        user = make_user()
        sql("UPDATE users SET email_verified = false WHERE id = :i", i=user["id"])
        registration = self.client.post("/api/auth/register", json={
            "nickname": f"n{user['id']}x", "email": f"v{user['id']}@example.com", "password": PASSWORD}).json()
        verified = self.client.post("/api/auth/email/verify", json={"email": registration["email"], "code": registration["demo_code"]})
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertIn(COOKIE_NAME, verified.cookies)

class RefreshTests(SessionCase):
    def test_refresh_returns_a_working_access_token_and_a_new_cookie(self):
        user, _, first = self.sign_in()
        resp = self.refresh(first)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.me(resp.json()["access_token"]), 200)
        second = self.new_cookie(resp)
        self.assertTrue(second and second != first)
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE user_id = :u", u=user["id"]), 2)

    def test_a_chain_of_refreshes_keeps_working(self):
        _, _, token = self.sign_in()
        for _ in range(4):
            resp = self.refresh(token)
            self.assertEqual(resp.status_code, 200)
            token = self.new_cookie(resp)
            sql("UPDATE refresh_tokens SET rotated_at = now() - interval '1 minute' WHERE rotated_at IS NOT NULL")

    def test_missing_or_garbage_cookies_are_refused_cleanly(self):
        self.assertEqual(self.client.post("/api/auth/refresh").status_code, 401)
        resp = self.refresh("not-a-real-token")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Max-Age=0", next(h for h in resp.headers.get_list("set-cookie") if h.startswith(COOKIE_NAME)))

    def test_expired_and_deactivated_sessions_are_refused(self):
        user, _, token = self.sign_in()
        sql("UPDATE refresh_tokens SET expires_at = now() - interval '1 second' WHERE user_id = :u", u=user["id"])
        self.assertEqual(self.refresh(token).status_code, 401)
        user, _, token = self.sign_in()
        sql("UPDATE users SET active = false WHERE id = :u", u=user["id"])
        self.assertEqual(self.refresh(token).status_code, 401)

    def test_a_session_can_never_outlive_the_absolute_family_limit(self):
        user, _, token = self.sign_in()
        sql("UPDATE refresh_tokens SET family_created_at = now() - interval '89 days' WHERE user_id = :u", u=user["id"])
        resp = self.refresh(token)
        self.assertEqual(resp.status_code, 200)
        remaining = scalar("SELECT extract(epoch FROM (max(expires_at) - now())) FROM refresh_tokens WHERE user_id = :u AND rotated_at IS NULL", u=user["id"])
        self.assertLess(remaining, 2 * 86400)            # 90-day cap, not another 30 days

class ReuseDetectionTests(SessionCase):
    def test_replaying_a_rotated_token_after_the_grace_period_revokes_the_whole_session(self):
        user, _, stolen = self.sign_in()
        newest = self.new_cookie(self.refresh(stolen))
        sql("UPDATE refresh_tokens SET rotated_at = now() - interval '1 minute' WHERE rotated_at IS NOT NULL")
        replay = self.refresh(stolen)
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(self.refresh(newest).status_code, 401, "the legitimate holder is signed out too")
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=user["id"]), 0)
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE actor_id = :u AND action = 'auth.refresh_reuse_detected'", u=user["id"]), 1)

    def test_a_request_racing_a_refresh_within_the_grace_period_is_not_treated_as_theft(self):
        _, _, token = self.sign_in()
        first = self.refresh(token)
        second = self.refresh(token)                      # same old cookie, a moment later
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(self.me(second.json()["access_token"]), 200)
        self.assertIsNone(self.new_cookie(second), "the racing request must not rotate again")
        self.assertEqual(self.refresh(self.new_cookie(first)).status_code, 200)

    def test_parallel_refreshes_rotate_exactly_once(self):
        user, _, token = self.sign_in()
        results = run_parallel([lambda: self.refresh(token) for _ in range(6)])
        self.assertEqual([r.status_code for r in results], [200] * 6, [r.text for r in results])
        self.assertEqual(sum(1 for r in results if self.new_cookie(r)), 1)
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE user_id = :u", u=user["id"]), 2)
        self.assertEqual(scalar("SELECT count(*) FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NOT NULL", u=user["id"]), 0)

class SignOutTests(SessionCase):
    def test_logout_ends_only_this_browsers_session(self):
        user = make_user()
        _, _, laptop = self.sign_in(user)
        _, _, phone = self.sign_in(user)
        resp = self.client.post("/api/auth/logout", headers={"Cookie": f"{COOKIE_NAME}={laptop}"})
        self.assertEqual(resp.status_code, 204)
        self.assertIn("Max-Age=0", next(h for h in resp.headers.get_list("set-cookie") if h.startswith(COOKIE_NAME)))
        self.assertEqual(self.refresh(laptop).status_code, 401)
        self.assertEqual(self.refresh(phone).status_code, 200)

    def test_logout_works_without_any_session(self):
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)

    def test_sign_out_everywhere_revokes_every_browser(self):
        user = make_user()
        _, login, laptop = self.sign_in(user)
        _, _, phone = self.sign_in(user)
        access = login.json()["access_token"]
        self.assertEqual(self.client.post("/api/auth/logout-all", headers=auth(access)).status_code, 204)
        self.assertEqual([self.refresh(laptop).status_code, self.refresh(phone).status_code], [401, 401])
        self.assertEqual(self.me(access), 401)

    def test_a_password_reset_revokes_every_browser(self):
        user = make_user()
        _, _, token = self.sign_in(user)
        started = self.client.post("/api/auth/password-reset/request", json={"email": user["email"]}).json()
        done = self.client.post("/api/auth/password-reset/confirm", json={
            "email": user["email"], "code": started["demo_code"], "password": "a-brand-new-password-1"})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.refresh(token).status_code, 401)

class CrossSiteTests(SessionCase):
    def test_refresh_and_logout_refuse_foreign_origins(self):
        _, _, token = self.sign_in()
        for path in ("/api/auth/refresh", "/api/auth/logout"):
            resp = self.client.post(path, headers={"Cookie": f"{COOKIE_NAME}={token}", "Origin": "https://evil.example"})
            self.assertEqual(resp.status_code, 403, path)
        self.assertEqual(self.refresh(token).status_code, 200, "the token must still be intact")

    def test_the_browsers_same_origin_signal_is_trusted_but_cross_site_is_not(self):
        _, _, token = self.sign_in()
        foreign = {"Origin": "https://not-in-the-configured-list.example"}
        self.assertEqual(self.refresh(token, **foreign, **{"Sec-Fetch-Site": "same-origin"}).status_code, 200)
        _, _, token = self.sign_in()
        self.assertEqual(self.refresh(token, **foreign, **{"Sec-Fetch-Site": "cross-site"}).status_code, 403)

    def test_the_configured_frontend_origin_is_accepted(self):
        _, _, token = self.sign_in()
        origin = settings.cors_origins.split(",")[0]
        self.assertEqual(self.refresh(token, Origin=origin).status_code, 200)

class CleanupTests(SessionCase):
    def test_purge_removes_only_long_dead_tokens(self):
        user, _, _ = self.sign_in()
        sql("""INSERT INTO refresh_tokens (user_id, token_hash, family_id, family_created_at, expires_at, revoked_at) VALUES
               (:u, 'old-expired', 'f1', now() - interval '60 days', now() - interval '30 days', NULL),
               (:u, 'old-revoked', 'f2', now() - interval '60 days', now() + interval '30 days', now() - interval '20 days'),
               (:u, 'fresh-revoked', 'f3', now(), now() + interval '30 days', now() - interval '1 day')""", u=user["id"])
        self.assertGreaterEqual(purge_expired_refresh_tokens(), 2)
        remaining = {r[0] for r in sql("SELECT token_hash FROM refresh_tokens WHERE user_id = :u", u=user["id"])}
        self.assertIn("fresh-revoked", remaining)
        self.assertTrue({"old-expired", "old-revoked"}.isdisjoint(remaining))

if __name__ == "__main__":
    unittest.main()
