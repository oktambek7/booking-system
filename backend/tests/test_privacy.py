"""Data export and account deletion."""
import json
import unittest
from datetime import timedelta
from unittest import mock

from sqlalchemy.exc import DBAPIError

from app.models import Role
from app.sessions import COOKIE_NAME
from tests.support import ApiTestCase, auth, make_hall, make_screening, make_user, run_parallel, scalar, sql

PASSWORD = "correct-horse-battery"

class PrivacyCase(ApiTestCase):
    def setUp(self):
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")
        patcher = mock.patch("app.routes.payments.deliver_due_notifications")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.cookies.clear()

    def paid_ticket(self, shop, starts_in=timedelta(hours=30)):
        hall = make_hall()
        screening = make_screening(hall, starts_in=starts_in, surcharge=0)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        return shop.pay(booking["id"]).json()["booking"], screening, hall

    def export(self, shop):
        return self.client.get("/api/account/export", headers=shop.headers)

    def delete(self, shop, password=PASSWORD, confirm=True):
        return self.client.request("DELETE", "/api/account", headers=shop.headers, json={"password": password, "confirm": confirm})

class ExportTests(PrivacyCase):
    def test_requires_a_signed_in_account(self):
        self.assertIn(self.client.get("/api/account/export").status_code, (401, 403))

    def test_contains_the_customers_own_records(self):
        shop = self.shop(points=500)
        ticket, screening, hall = self.paid_ticket(shop)
        hold = shop.book(screening, [hall["seat_ids"][1]]).json()
        movie_id = scalar("SELECT movie_id FROM screenings WHERE id = :s", s=screening)
        sql("INSERT INTO movie_watchlists (user_id, movie_id) VALUES (:u, :m)", u=shop.user["id"], m=movie_id)
        sql("INSERT INTO screening_waitlist (screening_id, user_id, seat_count, status) VALUES (:s, :u, 2, 'waiting')", s=screening, u=shop.user["id"])
        sql("INSERT INTO audit_log (actor_id, actor_email, action, ip) VALUES (:u, :e, 'auth.sessions_revoked', '203.0.113.9')", u=shop.user["id"], e=shop.user["email"])
        self.client.post("/api/auth/login", json={"email": shop.user["email"], "password": PASSWORD})
        self.client.cookies.clear()
        data = self.export(shop).json()
        self.assertEqual(data["export_version"], 1)
        self.assertEqual((data["account"]["email"], data["account"]["role"]), (shop.user["email"], "customer"))
        self.assertEqual(sorted(b["id"] for b in data["bookings"]), sorted([ticket["id"], hold["id"]]))
        paid = next(b for b in data["bookings"] if b["id"] == ticket["id"])
        self.assertEqual((paid["status"], paid["ticket_code"], paid["seats"]), ("confirmed", ticket["ticket_code"], ["A1"]))
        self.assertEqual([(p["booking_id"], p["card_last4"], p["status"]) for p in data["payments"]], [(ticket["id"], "1234", "succeeded_demo")])
        self.assertEqual(len(data["saved_movies"]), 1)
        self.assertEqual(data["waitlist"][0]["seat_count"], 2)
        self.assertEqual(data["telegram"], {"linked": False})
        self.assertTrue(any(a["action"] == "auth.sessions_revoked" and a["ip"] == "203.0.113.9" for a in data["activity_log"]))
        self.assertEqual(len(data["active_sessions"]), 1)
        self.assertGreater(data["loyalty"]["points"], 0)

    def test_never_includes_secrets_or_other_peoples_data(self):
        shop, other = self.shop(), self.shop()
        self.paid_ticket(other)
        self.paid_ticket(shop)
        body = self.export(shop).text
        for secret in ("password_hash", "$argon2", "token_hash", "code_hash", "token_version"):
            self.assertNotIn(secret, body)
        self.assertNotIn(other.user["email"], body)
        self.assertEqual(len(json.loads(body)["bookings"]), 1)

    def test_arrives_as_a_private_download(self):
        shop = self.shop()
        resp = self.export(shop)
        self.assertRegex(resp.headers["Content-Disposition"], r'^attachment; filename="parda-data-\d{4}-\d{2}-\d{2}\.json"$')
        self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_is_rate_limited(self):
        shop = self.shop()
        self.assertEqual([self.export(shop).status_code for _ in range(7)], [200] * 5 + [429] * 2)

class DeletionRefusalTests(PrivacyCase):
    def test_needs_the_password_and_an_explicit_confirmation(self):
        shop = self.shop()
        self.assertEqual(self.delete(shop, password="not-my-password").status_code, 403)
        self.assertEqual(self.delete(shop, confirm=False).status_code, 422)
        self.assertEqual(self.client.request("DELETE", "/api/account", json={"password": PASSWORD, "confirm": True}).status_code in (401, 403), True)
        self.assertTrue(scalar("SELECT active FROM users WHERE id = :u", u=shop.user["id"]))
        self.assertEqual(self.client.get("/api/auth/me", headers=shop.headers).status_code, 200)

    def test_password_guessing_through_this_endpoint_is_limited(self):
        shop = self.shop()
        codes = [self.delete(shop, password=f"wrong-{i}").status_code for i in range(7)]
        self.assertEqual(codes, [403] * 5 + [429] * 2)

    def test_operators_cannot_delete_themselves(self):
        operator = self.shop(role=Role.ADMIN)
        resp = self.delete(operator)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("Operator", resp.json()["detail"])
        self.assertTrue(scalar("SELECT active FROM users WHERE id = :u", u=operator.user["id"]))

    def test_upcoming_paid_tickets_block_deletion_until_they_are_cancelled(self):
        shop = self.shop()
        ticket, _, _ = self.paid_ticket(shop)
        resp = self.delete(shop)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("1 upcoming paid ticket", resp.json()["detail"])
        self.assertTrue(scalar("SELECT active FROM users WHERE id = :u", u=shop.user["id"]))
        self.assertEqual(shop.set_status(ticket["id"], "cancelled").status_code, 200)       # refunded
        self.assertEqual(self.delete(shop).status_code, 204)

    def test_old_tickets_do_not_block_deletion(self):
        shop = self.shop()
        ticket, screening, _ = self.paid_ticket(shop)
        sql("UPDATE screenings SET starts_at = now() - interval '3 hours', ends_at = now() - interval '1 hour' WHERE id = :s", s=screening)
        self.assertEqual(self.delete(shop).status_code, 204)

class DeletionTests(PrivacyCase):
    def test_the_account_is_anonymised_and_locked_out(self):
        shop = self.shop(points=800)
        ticket, screening, _ = self.paid_ticket(shop)
        sql("UPDATE users SET avatar_data = 'data:image/png;base64,AAAA', phone = '+998901234567' WHERE id = :u", u=shop.user["id"])
        sql("UPDATE screenings SET starts_at = now() - interval '3 hours', ends_at = now() - interval '1 hour' WHERE id = :s", s=screening)
        login = self.client.post("/api/auth/login", json={"email": shop.user["email"], "password": PASSWORD})
        cookie = login.cookies[COOKIE_NAME]
        self.client.cookies.clear()
        self.assertEqual(self.delete(shop).status_code, 204)
        user = sql("SELECT email, name, nickname, active, email_verified, avatar_data, phone, parda_points, reserved_points FROM users WHERE id = :u", u=shop.user["id"])[0]
        marker = f"deleted-user-{shop.user['id']}"
        self.assertEqual((user.email, user.name, user.nickname), (f"{marker}@deleted.invalid", marker, marker))
        self.assertEqual((user.active, user.email_verified, user.avatar_data, user.phone, user.parda_points, user.reserved_points), (False, False, None, None, 0, 0))
        self.assertEqual(self.client.post("/api/auth/login", json={"email": shop.user["email"], "password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me", headers=shop.headers).status_code, 401, "the old access token must die")
        self.assertEqual(self.client.post("/api/auth/refresh", headers={"Cookie": f"{COOKIE_NAME}={cookie}"}).status_code, 401)
        self.assertEqual(self.export(shop).status_code, 401)

    def test_personal_side_records_are_erased(self):
        shop = self.shop()
        _, screening, _ = self.paid_ticket(shop, starts_in=timedelta(hours=30))
        uid = shop.user["id"]
        movie_id = scalar("SELECT movie_id FROM screenings WHERE id = :s", s=screening)
        sql("INSERT INTO movie_watchlists (user_id, movie_id) VALUES (:u, :m)", u=uid, m=movie_id)
        sql("INSERT INTO screening_waitlist (screening_id, user_id, seat_count, status) VALUES (:s, :u, 1, 'waiting')", s=screening, u=uid)
        sql("INSERT INTO telegram_links (user_id, chat_id) VALUES (:u, :c)", u=uid, c=9_100_000_000 + uid)
        self.client.post("/api/auth/login", json={"email": shop.user["email"], "password": PASSWORD})
        self.client.cookies.clear()
        sql("UPDATE screenings SET starts_at = now() - interval '3 hours', ends_at = now() - interval '1 hour' WHERE id = :s", s=screening)
        self.assertEqual(self.delete(shop).status_code, 204)
        for table in ("movie_watchlists", "screening_waitlist", "telegram_links", "telegram_link_tokens", "refresh_tokens",
                      "email_otp_challenges", "password_reset_challenges", "payment_email_challenges"):
            self.assertEqual(scalar(f"SELECT count(*) FROM {table} WHERE user_id = :u", u=uid), 0, table)

    def test_financial_records_are_kept_without_the_person(self):
        shop = self.shop()
        ticket, screening, _ = self.paid_ticket(shop)
        sql("UPDATE screenings SET starts_at = now() - interval '3 hours', ends_at = now() - interval '1 hour' WHERE id = :s", s=screening)
        self.assertEqual(self.delete(shop).status_code, 204)
        row = sql("SELECT b.total_price, p.status, p.card_last4, u.email FROM bookings b JOIN payments p ON p.booking_id = b.id "
                  "JOIN users u ON u.id = b.customer_id WHERE b.id = :b", b=ticket["id"])[0]
        self.assertEqual((float(row.total_price), row.status, row.card_last4), (30000.0, "succeeded_demo", "1234"))
        self.assertTrue(row.email.endswith("@deleted.invalid"))

    def test_unpaid_holds_are_released(self):
        shop = self.shop(points=500)
        hall = make_hall()
        screening = make_screening(hall, surcharge=0)
        hold = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.price(hold["id"], points=100)
        self.assertEqual(shop.points(), (500, 100))
        self.assertEqual(self.delete(shop).status_code, 204)
        self.assertEqual(sql("SELECT status FROM bookings WHERE id = :b", b=hold["id"])[0][0], "CANCELLED")
        self.assertEqual(self.shop().book(screening, [hall["seat_ids"][0]]).status_code, 201, "the seat is free again")

    def test_the_operator_dashboard_still_loads_for_days_with_a_deleted_customers_booking(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        shop = self.shop()
        hall = make_hall()
        screening = make_screening(hall, starts_in=timedelta(hours=30), surcharge=0)
        hold = shop.book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(self.delete(shop).status_code, 204)
        day = (datetime.now(timezone.utc) + timedelta(hours=30)).astimezone(ZoneInfo("Asia/Tashkent")).date().isoformat()
        operator = auth(make_user(role=Role.ADMIN)["token"])
        resp = self.client.get("/api/admin/dashboard", headers=operator, params={"date": day})
        self.assertEqual(resp.status_code, 200, resp.text)
        mine = [b for b in resp.json()["bookings"] if b["id"] == hold["id"]]
        self.assertEqual([b["customer_email"] for b in mine], [f"deleted-user-{shop.user['id']}@deleted.invalid"])

    def test_the_email_and_nickname_can_be_used_again(self):
        shop = self.shop()
        nickname = scalar("SELECT nickname FROM users WHERE id = :u", u=shop.user["id"])
        self.assertEqual(self.delete(shop).status_code, 204)
        again = self.client.post("/api/auth/register", json={"nickname": nickname, "email": shop.user["email"], "password": "another-valid-password-1"})
        self.assertEqual(again.status_code, 201, again.text)

    def test_the_audit_trail_is_anonymised_but_still_tamper_proof(self):
        shop = self.shop()
        sql("INSERT INTO audit_log (actor_id, actor_email, action, ip) VALUES (:u, :e, 'auth.password_reset', '198.51.100.4')", u=shop.user["id"], e=shop.user["email"])
        self.assertEqual(self.delete(shop).status_code, 204)
        rows = sql("SELECT actor_email, ip, action FROM audit_log WHERE actor_id = :u ORDER BY id", u=shop.user["id"])
        self.assertEqual([r.action for r in rows], ["auth.password_reset", "account.deleted"])
        self.assertTrue(all(r.actor_email == f"deleted-user-{shop.user['id']}@deleted.invalid" and r.ip is None for r in rows))
        for statement in ("UPDATE audit_log SET action = 'forged' WHERE actor_id = :u",
                          "UPDATE audit_log SET actor_email = 'someone@else.com' WHERE actor_id = :u",
                          "UPDATE audit_log SET ip = '1.2.3.4' WHERE actor_id = :u",
                          "DELETE FROM audit_log WHERE actor_id = :u"):
            with self.subTest(statement=statement), self.assertRaises(DBAPIError):
                sql(statement, u=shop.user["id"])

    def test_the_audit_trigger_only_allows_the_erasure_edits(self):
        sql("INSERT INTO audit_log (actor_email, action, ip) VALUES ('keep@example.com', 'test.entry', '10.0.0.1')")
        entry = scalar("SELECT max(id) FROM audit_log WHERE action = 'test.entry'")
        with self.assertRaises(DBAPIError):
            sql("UPDATE audit_log SET actor_email = NULL WHERE id = :i", i=entry)
        sql("UPDATE audit_log SET actor_email = 'deleted-user-1@deleted.invalid', ip = NULL WHERE id = :i", i=entry)

    def test_simultaneous_requests_delete_once(self):
        shop = self.shop()
        results = run_parallel([lambda: self.delete(shop) for _ in range(3)])
        self.assertEqual(sorted(r.status_code for r in results).count(204), 1, [r.text for r in results])
        self.assertTrue(all(r.status_code in (204, 401, 409) for r in results), [r.status_code for r in results])
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE actor_id = :u AND action = 'account.deleted'", u=shop.user["id"]), 1)

    def test_a_goodbye_email_goes_to_the_old_address_and_cannot_block_the_deletion(self):
        shop = self.shop()
        with mock.patch("app.routes.privacy.send_account_deleted_email") as sender:
            self.assertEqual(self.delete(shop).status_code, 204)
        sender.assert_called_once_with(shop.user["email"])
        other = self.shop()
        with mock.patch("app.routes.privacy.send_account_deleted_email", side_effect=RuntimeError("smtp down")):
            self.assertEqual(self.delete(other).status_code, 204)

if __name__ == "__main__":
    unittest.main()
