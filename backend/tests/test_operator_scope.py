"""Operators limited to particular cinemas, and the owner-only management of who is an operator."""
import csv
import io
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from app.models import Role
from tests.support import ApiTestCase, auth, make_hall, make_screening, make_user, run_parallel, scalar, sql

TASHKENT = ZoneInfo("Asia/Tashkent")
SHOW = datetime(2031, 6, 10, 20, 0, tzinfo=TASHKENT)
DAY = date(2031, 6, 10)

def rows_of(response) -> list[dict]:
    text = response.text.lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text)))

class ScopeCase(ApiTestCase):
    def setUp(self):
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")
        patcher = mock.patch("app.routes.payments.deliver_due_notifications")
        patcher.start()
        self.addCleanup(patcher.stop)
        tag = uuid.uuid4().hex[:8]
        self.cinema_a, self.cinema_b = f"Alpha {tag}", f"Beta {tag}"
        self.hall_a, self.hall_b = make_hall(cinema=self.cinema_a), make_hall(cinema=self.cinema_b)
        self.screening_a, self.screening_b = make_screening(self.hall_a), make_screening(self.hall_b)
        for screening in (self.screening_a, self.screening_b):
            start = SHOW.astimezone(timezone.utc)
            sql("UPDATE screenings SET starts_at = :s, ends_at = :e WHERE id = :i", s=start, e=start + timedelta(hours=2), i=screening)
        self.owner_user = make_user(role=Role.ADMIN)
        self.owner = auth(self.owner_user["token"])
        self.op_a = self.scoped([self.cinema_a])
        self.shop_a, self.shop_b = self.shop(), self.shop()
        self.booking_a = self.shop_a.book(self.screening_a, [self.hall_a["seat_ids"][0]]).json()["id"]
        self.booking_b = self.shop_b.book(self.screening_b, [self.hall_b["seat_ids"][0]]).json()["id"]
        self.shop_a.pay(self.booking_a)
        self.shop_b.pay(self.booking_b)

    def scoped(self, cinemas: list[str]) -> dict:
        user = make_user(role=Role.ADMIN)
        sql("UPDATE users SET cinema_scoped = true WHERE id = :i", i=user["id"])
        for name in cinemas:
            sql("INSERT INTO cinema_operators (user_id, cinema_name) VALUES (:u, :c)", u=user["id"], c=name)
        return auth(user["token"])

    def get(self, path, headers=None, **params):
        return self.client.get(path, headers=headers or self.owner, params=params)

class VisibilityTests(ScopeCase):
    def test_halls_are_filtered_to_the_operators_cinemas(self):
        owner_names = {h["cinema_name"] for h in self.get("/api/admin/cinemas").json()}
        scoped_names = {h["cinema_name"] for h in self.get("/api/admin/cinemas", self.op_a).json()}
        self.assertTrue({self.cinema_a, self.cinema_b} <= owner_names)
        self.assertEqual(scoped_names, {self.cinema_a})

    def test_the_dashboard_only_counts_the_operators_cinemas(self):
        owner = self.get("/api/admin/dashboard", date=DAY.isoformat()).json()
        scoped = self.get("/api/admin/dashboard", self.op_a, date=DAY.isoformat()).json()
        self.assertEqual({s["id"] for s in scoped["screenings"]}, {self.screening_a})
        self.assertEqual({b["id"] for b in scoped["bookings"]}, {self.booking_a})
        self.assertEqual((scoped["metrics"]["screenings"], scoped["metrics"]["bookings"]), (1, 1))
        self.assertTrue({self.screening_a, self.screening_b} <= {s["id"] for s in owner["screenings"]})

    def test_the_booking_list_is_filtered(self):
        scoped_ids = {b["id"] for b in self.get("/api/bookings", self.op_a).json()}
        owner_ids = {b["id"] for b in self.get("/api/bookings").json()}
        self.assertIn(self.booking_a, scoped_ids)
        self.assertNotIn(self.booking_b, scoped_ids)
        self.assertTrue({self.booking_a, self.booking_b} <= owner_ids)

    def test_reports_contain_only_the_operators_cinemas(self):
        for kind in ("bookings", "revenue"):
            with self.subTest(kind=kind):
                scoped = rows_of(self.get(f"/api/admin/reports/{kind}.csv", self.op_a, **{"from": DAY.isoformat(), "to": DAY.isoformat()}))
                owner = rows_of(self.get(f"/api/admin/reports/{kind}.csv", **{"from": DAY.isoformat(), "to": DAY.isoformat()}))
                self.assertEqual({r["cinema"] for r in scoped}, {self.cinema_a})
                self.assertTrue({self.cinema_a, self.cinema_b} <= {r["cinema"] for r in owner})

    def test_the_audit_entry_for_a_scoped_export_records_the_scope(self):
        self.get("/api/admin/reports/revenue.csv", self.op_a, **{"from": DAY.isoformat(), "to": DAY.isoformat()})
        details = scalar("SELECT details FROM audit_log WHERE action = 'report.exported' ORDER BY id DESC LIMIT 1")
        self.assertEqual(details["cinemas"], [self.cinema_a])

    def test_an_operator_with_no_cinemas_sees_nothing_and_is_not_an_owner(self):
        nobody = self.scoped([])
        self.assertEqual(self.get("/api/admin/cinemas", nobody).json(), [])
        self.assertEqual(self.get("/api/admin/dashboard", nobody, date=DAY.isoformat()).json()["bookings"], [])
        self.assertEqual(self.get("/api/admin/operators", nobody).status_code, 403)

    def test_me_tells_the_app_which_kind_of_operator_this_is(self):
        self.assertIsNone(self.get("/api/auth/me").json()["operator_cinemas"])
        self.assertEqual(self.get("/api/auth/me", self.op_a).json()["operator_cinemas"], [self.cinema_a])
        self.assertNotIn("operator_cinemas", self.get("/api/auth/me", self.shop_a.headers).json())

class ActionTests(ScopeCase):
    def test_other_cinemas_bookings_cannot_be_read_or_changed(self):
        self.assertEqual(self.get(f"/api/bookings/{self.booking_b}/cancellation-quote", self.op_a).status_code, 404)
        self.assertEqual(self.get(f"/api/bookings/{self.booking_a}/cancellation-quote", self.op_a).status_code, 200)
        response = self.client.patch(f"/api/bookings/{self.booking_b}/status", headers=self.op_a, json={"status": "cancelled"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(str(scalar("SELECT status FROM bookings WHERE id = :i", i=self.booking_b)).lower(), "confirmed")
        response = self.client.patch(f"/api/bookings/{self.booking_a}/status", headers=self.op_a, json={"status": "cancelled"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_check_in_is_limited_to_the_operators_cinemas(self):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        sql("UPDATE screenings SET starts_at = :s, ends_at = :e WHERE id IN (:a, :b)", s=start, e=start + timedelta(hours=2), a=self.screening_a, b=self.screening_b)
        code_a = scalar("SELECT ticket_code FROM bookings WHERE id = :i", i=self.booking_a)
        code_b = scalar("SELECT ticket_code FROM bookings WHERE id = :i", i=self.booking_b)
        self.assertEqual(self.client.post("/api/admin/tickets/check-in", headers=self.op_a, json={"ticket_code": code_b}).status_code, 404)
        self.assertIsNone(scalar("SELECT checked_in_at FROM bookings WHERE id = :i", i=self.booking_b))
        self.assertEqual(self.client.post("/api/admin/tickets/check-in", headers=self.op_a, json={"ticket_code": code_a}).status_code, 200)
        self.assertEqual(self.client.post("/api/admin/tickets/check-in", headers=self.owner, json={"ticket_code": code_b}).status_code, 200)

    def test_screenings_can_only_be_scheduled_in_the_operators_cinemas(self):
        movie_id = scalar("SELECT movie_id FROM screenings WHERE id = :i", i=self.screening_a)
        start = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0).isoformat()
        body = lambda hall: {"movie_id": movie_id, "auditorium_id": hall["id"], "starts_at": start, "base_price": 30000}   # noqa: E731
        self.assertEqual(self.client.post("/api/screenings", headers=self.op_a, json=body(self.hall_b)).status_code, 403)
        self.assertEqual(self.client.post("/api/screenings", headers=self.op_a, json=body(self.hall_a)).status_code, 201)

    def test_halls_can_only_be_changed_in_the_operators_cinemas(self):
        self.assertEqual(self.client.patch(f"/api/cinemas/{self.hall_b['id']}", headers=self.op_a, json={"address": "x"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/cinemas/{self.hall_a['id']}", headers=self.op_a, json={"address": "x"}).status_code, 200)
        hall = lambda cinema: {"name": f"New {uuid.uuid4().hex[:5]}", "cinema_name": cinema, "row_count": 2, "seats_per_row": 4}   # noqa: E731
        self.assertEqual(self.client.post("/api/cinemas", headers=self.op_a, json=hall(self.cinema_b)).status_code, 403)
        self.assertEqual(self.client.post("/api/cinemas", headers=self.op_a, json=hall("A brand new cinema")).status_code, 403)
        self.assertEqual(self.client.post("/api/cinemas", headers=self.op_a, json=hall(self.cinema_a)).status_code, 201)

    def test_global_settings_are_owner_only(self):
        calls = [("get", "/api/admin/promotions", None), ("post", "/api/admin/promotions", {"code": "NOPE10", "label": "no", "percent_off": 10}),
                 ("get", "/api/admin/audit-log", None), ("get", "/api/admin/diagnostics/client-ip", None),
                 ("post", "/api/catalog/sync", None), ("post", "/api/admin/catalog-sync", None), ("get", "/api/admin/catalog-sync/status", None),
                 ("post", "/api/cinematica/sync", None), ("post", "/api/movies", {"title": "Nope"}),
                 ("patch", "/api/movies/1", {"title": "Nope"}), ("delete", "/api/movies/1", None),
                 ("get", "/api/admin/operators", None), ("put", "/api/admin/operators", {"email": "a@example.com", "cinemas": None}),
                 ("delete", "/api/admin/operators/1", None)]
        for method, path, body in calls:
            with self.subTest(path=path, method=method):
                response = self.client.request(method, path, headers=self.op_a, json=body)
                self.assertEqual(response.status_code, 403, response.text)

    def test_owners_keep_every_global_setting(self):
        self.assertEqual(self.get("/api/admin/promotions").status_code, 200)
        self.assertEqual(self.get("/api/admin/audit-log").status_code, 200)
        self.assertEqual(self.get("/api/admin/operators").status_code, 200)

    def test_customers_are_still_refused_everything_administrative(self):
        for path in ("/api/admin/cinemas", "/api/admin/operators", "/api/admin/promotions"):
            self.assertEqual(self.get(path, self.shop_a.headers).status_code, 403)

class ManagementTests(ScopeCase):
    def grant(self, email, cinemas, headers=None):
        return self.client.put("/api/admin/operators", headers=headers or self.owner, json={"email": email, "cinemas": cinemas})

    def test_an_owner_can_make_a_customer_a_scoped_operator(self):
        customer = self.shop()
        response = self.grant(customer.user["email"], [self.cinema_a])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["owner"], response.json()["cinemas"]), (False, [self.cinema_a]))
        headers = customer.headers
        self.assertEqual({h["cinema_name"] for h in self.get("/api/admin/cinemas", headers).json()}, {self.cinema_a})
        self.assertEqual(self.get("/api/admin/promotions", headers).status_code, 403)
        listed = {o["email"]: o for o in self.get("/api/admin/operators").json()}
        self.assertEqual(listed[customer.user["email"]]["cinemas"], [self.cinema_a])

    def test_the_cinema_list_is_replaced_not_added_to(self):
        customer = self.shop()
        self.grant(customer.user["email"], [self.cinema_a])
        self.grant(customer.user["email"], [self.cinema_b])
        self.assertEqual({h["cinema_name"] for h in self.get("/api/admin/cinemas", customer.headers).json()}, {self.cinema_b})
        self.assertEqual(scalar("SELECT count(*) FROM cinema_operators WHERE user_id = :i", i=customer.user["id"]), 1)

    def test_null_cinemas_makes_an_owner_and_a_list_narrows_one_down(self):
        customer = self.shop()
        self.assertEqual(self.grant(customer.user["email"], None).json()["owner"], True)
        self.assertEqual(self.get("/api/admin/promotions", customer.headers).status_code, 200)
        self.assertEqual(self.grant(customer.user["email"], [self.cinema_a]).json()["owner"], False)
        self.assertEqual(self.get("/api/admin/promotions", customer.headers).status_code, 403)

    def test_bad_requests_are_refused(self):
        customer = self.shop()
        self.assertEqual(self.grant(customer.user["email"], ["No such cinema"]).status_code, 422)
        self.assertEqual(self.grant("nobody-here@example.com", None).status_code, 404)
        sql("UPDATE users SET email_verified = false WHERE id = :i", i=customer.user["id"])
        self.assertEqual(self.grant(customer.user["email"], None).status_code, 409)
        self.assertEqual(self.grant(self.owner_user["email"], [self.cinema_a]).status_code, 409)            # not yourself

    def test_a_scoped_operator_cannot_grant_anything(self):
        customer = self.shop()
        self.assertEqual(self.grant(customer.user["email"], None, headers=self.op_a).status_code, 403)
        self.assertEqual(scalar("SELECT role FROM users WHERE id = :i", i=customer.user["id"]).lower(), "customer")

    def test_revoking_returns_the_account_to_a_customer_and_signs_it_out(self):
        customer = self.shop()
        self.grant(customer.user["email"], [self.cinema_a])
        self.assertEqual(self.client.delete(f"/api/admin/operators/{customer.user['id']}", headers=self.owner).status_code, 204)
        self.assertEqual(scalar("SELECT role FROM users WHERE id = :i", i=customer.user["id"]).lower(), "customer")
        self.assertEqual(scalar("SELECT cinema_scoped FROM users WHERE id = :i", i=customer.user["id"]), False)
        self.assertEqual(scalar("SELECT count(*) FROM cinema_operators WHERE user_id = :i", i=customer.user["id"]), 0)
        self.assertEqual(self.get("/api/admin/cinemas", customer.headers).status_code, 401)                    # old token revoked

    def test_you_cannot_remove_yourself_and_unknown_operators_are_404(self):
        self.assertEqual(self.client.delete(f"/api/admin/operators/{self.owner_user['id']}", headers=self.owner).status_code, 409)
        self.assertEqual(self.client.delete("/api/admin/operators/99999999", headers=self.owner).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/admin/operators/{self.shop_a.user['id']}", headers=self.owner).status_code, 404)

    def test_every_change_is_audited(self):
        customer = self.shop()
        self.grant(customer.user["email"], [self.cinema_a])
        self.client.delete(f"/api/admin/operators/{customer.user['id']}", headers=self.owner)
        actions = [r[0] for r in sql("SELECT action FROM audit_log WHERE target_type = 'user' AND target_id = :i AND action LIKE 'operator.%' ORDER BY id", i=str(customer.user["id"]))]
        self.assertEqual(actions, ["operator.granted", "operator.revoked"])

    def test_two_owners_cannot_remove_each_other_at_the_same_time(self):
        other = make_user(role=Role.ADMIN)
        mine = self.owner_user
        results = run_parallel([
            lambda: self.client.delete(f"/api/admin/operators/{other['id']}", headers=self.owner),
            lambda: self.client.delete(f"/api/admin/operators/{mine['id']}", headers=auth(other["token"])),
        ])
        self.assertEqual(sorted(r.status_code for r in results), [204, 403])
        survivors = scalar("SELECT count(*) FROM users WHERE id IN (:a, :b) AND role = 'ADMIN' AND NOT cinema_scoped", a=mine["id"], b=other["id"])
        self.assertEqual(survivors, 1)
