"""The audit log: what is recorded, what is not, who can read it, and that it cannot be rewritten."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import DBAPIError

from app.models import Role
from tests.support import ApiTestCase, auth, make_hall, make_screening, make_user, scalar, sql

def entries(**filters):
    clauses = " AND ".join(f"{key} = :{key}" for key in filters) or "true"
    return sql(f"SELECT action, actor_email, target_type, target_id, details, request_id, ip FROM audit_log "
               f"WHERE {clauses} ORDER BY id", **filters)

class AuditLogCase(ApiTestCase):
    def admin(self):
        user = make_user(role=Role.ADMIN)
        return user, auth(user["token"])

class RecordingTests(AuditLogCase):
    def test_creating_a_promotion_is_recorded_with_who_what_and_which_request(self):
        user, headers = self.admin()
        code = f"AUD{uuid.uuid4().hex[:6]}".upper()
        resp = self.client.post("/api/admin/promotions", headers=headers,
                                json={"code": code, "label": "Audit test", "percent_off": 15, "usage_limit": 5})
        self.assertEqual(resp.status_code, 201, resp.text)
        (row,) = entries(actor_email=user["email"], action="promotion.created")
        self.assertEqual((row.target_type, row.target_id), ("promotion", str(resp.json()["id"])))
        self.assertEqual((row.details["code"], row.details["percent_off"], row.details["usage_limit"]), (code, 15, 5))
        self.assertEqual(row.request_id, resp.headers["X-Request-ID"])
        self.assertTrue(row.ip)

    def test_film_and_hall_management_is_recorded(self):
        user, headers = self.admin()
        movie = self.client.post("/api/movies", headers=headers, json={"title": "Audit film", "duration_minutes": 90}).json()
        self.client.patch(f"/api/movies/{movie['id']}", headers=headers,
                          json={"title": "Audit film", "duration_minutes": 95, "genre": "Thriller"})
        self.client.delete(f"/api/movies/{movie['id']}", headers=headers)
        hall = self.client.post("/api/cinemas", headers=headers, json={
            "name": "Audit hall", "cinema_name": "Audit cinema", "row_count": 2, "seats_per_row": 3}).json()
        self.client.patch(f"/api/cinemas/{hall['id']}", headers=headers, json={"address": "New street 1"})
        actions = [(e.action, e.target_type) for e in entries(actor_email=user["email"])]
        self.assertEqual(actions, [("movie.created", "movie"), ("movie.updated", "movie"), ("movie.archived", "movie"),
                                   ("cinema.created", "auditorium"), ("cinema.updated", "auditorium")])
        updated = entries(actor_email=user["email"], action="movie.updated")[0]
        self.assertEqual(sorted(updated.details["fields"]), ["duration_minutes", "genre"])
        self.assertEqual(entries(actor_email=user["email"], action="cinema.created")[0].details["seats"], 6)

    def test_scheduling_a_screening_is_recorded(self):
        user, headers = self.admin()
        movie = self.client.post("/api/movies", headers=headers, json={"title": "Sched film", "duration_minutes": 100}).json()
        hall = make_hall()
        start = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        resp = self.client.post("/api/screenings", headers=headers, json={
            "movie_id": movie["id"], "auditorium_id": hall["id"], "starts_at": start, "base_price": 40000})
        self.assertEqual(resp.status_code, 201, resp.text)
        (row,) = entries(actor_email=user["email"], action="screening.created")
        self.assertEqual(row.target_id, str(resp.json()["id"]))
        self.assertEqual(row.details["auditorium_id"], hall["id"])

    def test_ticket_check_in_is_recorded(self):
        user, headers = self.admin()
        hall = make_hall()
        screening = make_screening(hall, starts_in=timedelta(minutes=30))
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        ticket = shop.pay(booking["id"]).json()["booking"]["ticket_code"]
        self.assertEqual(self.client.post("/api/admin/tickets/check-in", headers=headers, json={"ticket_code": ticket}).status_code, 200)
        (row,) = entries(actor_email=user["email"], action="ticket.checked_in")
        self.assertEqual((row.target_type, row.target_id, row.details["ticket_code"]), ("booking", str(booking["id"]), ticket))

    def test_operator_status_changes_are_recorded_but_customer_cancellations_are_not(self):
        admin, headers = self.admin()
        hall = make_hall()
        screening = make_screening(hall)
        customer = self.shop()
        mine = customer.book(screening, [hall["seat_ids"][0]]).json()
        theirs = customer.book(screening, [hall["seat_ids"][1]]).json()
        self.assertEqual(customer.set_status(mine["id"], "cancelled").status_code, 200)
        self.assertEqual(entries(action="booking.status_changed", target_id=str(mine["id"])), [])
        resp = self.client.patch(f"/api/bookings/{theirs['id']}/status", headers=headers, json={"status": "cancelled"})
        self.assertEqual(resp.status_code, 200, resp.text)
        (row,) = entries(action="booking.status_changed", target_id=str(theirs["id"]))
        self.assertEqual((row.actor_email, row.details), (admin["email"], {"from_status": "pending", "to_status": "cancelled"}))

    def test_password_reset_and_session_revocation_are_recorded_without_secrets(self):
        user = make_user()
        headers = auth(user["token"])
        self.assertEqual(self.client.post("/api/auth/logout-all", headers=headers).status_code, 204)
        started = self.client.post("/api/auth/password-reset/request", json={"email": user["email"]})
        code = started.json()["demo_code"]
        done = self.client.post("/api/auth/password-reset/confirm",
                                json={"email": user["email"], "code": code, "password": "another-long-password-1"})
        self.assertEqual(done.status_code, 200, done.text)
        rows = entries(actor_email=user["email"])
        self.assertEqual([r.action for r in rows], ["auth.sessions_revoked", "auth.password_reset"])
        self.assertTrue(all(r.details == {} for r in rows))
        self.assertNotIn(code, str([r.details for r in rows]))

    def test_actions_that_fail_leave_no_entry(self):
        user, headers = self.admin()
        code = f"DUP{uuid.uuid4().hex[:6]}".upper()
        payload = {"code": code, "label": "Dup", "percent_off": 10}
        self.assertEqual(self.client.post("/api/admin/promotions", headers=headers, json=payload).status_code, 201)
        self.assertEqual(self.client.post("/api/admin/promotions", headers=headers, json=payload).status_code, 409)
        self.assertEqual(self.client.post("/api/admin/tickets/check-in", headers=headers, json={"ticket_code": "PRD-NOSUCH99"}).status_code, 404)
        self.assertEqual([e.action for e in entries(actor_email=user["email"])], ["promotion.created"])

class ViewerTests(AuditLogCase):
    def test_only_operators_can_read_the_log(self):
        self.assertEqual(self.client.get("/api/admin/audit-log", headers=auth(make_user()["token"])).status_code, 403)
        self.assertIn(self.client.get("/api/admin/audit-log").status_code, (401, 403))

    def test_newest_first_with_pagination_and_filters(self):
        user, headers = self.admin()
        for i in range(5):
            self.client.post("/api/admin/promotions", headers=headers,
                             json={"code": f"PG{uuid.uuid4().hex[:6]}".upper(), "label": f"Page {i}", "percent_off": 5})
        first = self.client.get("/api/admin/audit-log", headers=headers, params={"actor_id": user["id"], "limit": 2}).json()
        self.assertEqual(len(first["items"]), 2)
        self.assertGreater(first["items"][0]["id"], first["items"][1]["id"])
        self.assertIsNotNone(first["next_before_id"])
        second = self.client.get("/api/admin/audit-log", headers=headers, params={
            "actor_id": user["id"], "limit": 2, "before_id": first["next_before_id"]}).json()
        self.assertLess(second["items"][0]["id"], first["items"][1]["id"])
        last = self.client.get("/api/admin/audit-log", headers=headers, params={
            "actor_id": user["id"], "limit": 50, "action": "promotion.created"}).json()
        self.assertEqual(len(last["items"]), 5)
        self.assertIsNone(last["next_before_id"])
        self.assertTrue(all(i["action"] == "promotion.created" and i["actor_email"] == user["email"] for i in last["items"]))

    def test_limit_is_bounded(self):
        _, headers = self.admin()
        self.assertEqual(self.client.get("/api/admin/audit-log", headers=headers, params={"limit": 500}).status_code, 422)

class AppendOnlyTests(AuditLogCase):
    def _entry_id(self):
        user, headers = self.admin()
        self.client.post("/api/movies", headers=headers, json={"title": "Immutable film"})
        return user, scalar("SELECT max(id) FROM audit_log WHERE actor_email = :e", e=user["email"])

    def test_entries_cannot_be_edited_or_deleted(self):
        _, entry_id = self._entry_id()
        for statement in ("UPDATE audit_log SET action = 'forged' WHERE id = :i",
                          "UPDATE audit_log SET details = '{}'::jsonb WHERE id = :i",
                          "UPDATE audit_log SET actor_email = 'someone@else.com' WHERE id = :i",
                          "DELETE FROM audit_log WHERE id = :i"):
            with self.subTest(statement=statement):
                with self.assertRaises(DBAPIError) as ctx:
                    sql(statement, i=entry_id)
                self.assertIn("append-only", str(ctx.exception))
        self.assertEqual(scalar("SELECT action FROM audit_log WHERE id = :i", i=entry_id), "movie.created")

    def test_deleting_an_account_keeps_its_entries_without_the_link(self):
        user, entry_id = self._entry_id()
        sql("DELETE FROM users WHERE id = :i", i=user["id"])
        row = sql("SELECT actor_id, actor_email, action FROM audit_log WHERE id = :i", i=entry_id)[0]
        self.assertEqual((row.actor_id, row.actor_email, row.action), (None, user["email"], "movie.created"))

if __name__ == "__main__":
    unittest.main()
