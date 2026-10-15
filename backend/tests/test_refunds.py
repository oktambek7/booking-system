"""Cancellation policy and refunds."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import Role
from app.notifications import deliver_due_notifications
from app.refunds import CUSTOMER, OPERATOR, refund_percent
from tests.support import ApiTestCase, auth, make_hall, make_screening, make_user, run_parallel, scalar, sql

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

class PolicyTests(unittest.TestCase):
    def test_share_depends_on_how_far_away_the_screening_is(self):
        cases = {timedelta(days=3): 100, timedelta(hours=24): 100, timedelta(hours=23, minutes=59): 50,
                 timedelta(hours=2): 50, timedelta(hours=1, minutes=59): 0, timedelta(minutes=1): 0, timedelta(hours=-1): 0}
        for lead, expected in cases.items():
            with self.subTest(lead=lead):
                self.assertEqual(refund_percent(NOW + lead, NOW, CUSTOMER), expected)

    def test_operators_always_refund_in_full(self):
        for lead in (timedelta(days=3), timedelta(minutes=5), timedelta(hours=-3)):
            self.assertEqual(refund_percent(NOW + lead, NOW, OPERATOR), 100)

    def test_the_policy_is_configurable(self):
        original = (settings.refund_full_hours, settings.refund_partial_hours, settings.refund_partial_percent)
        settings.refund_full_hours, settings.refund_partial_hours, settings.refund_partial_percent = 48, 6, 30
        try:
            self.assertEqual(refund_percent(NOW + timedelta(hours=30), NOW, CUSTOMER), 30)
            self.assertEqual(refund_percent(NOW + timedelta(hours=5), NOW, CUSTOMER), 0)
            self.assertEqual(refund_percent(NOW + timedelta(hours=49), NOW, CUSTOMER), 100)
        finally:
            settings.refund_full_hours, settings.refund_partial_hours, settings.refund_partial_percent = original

class RefundCase(ApiTestCase):
    def setUp(self):
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")
        patcher = mock.patch("app.routes.payments.deliver_due_notifications")
        patcher.start()
        self.addCleanup(patcher.stop)

    def paid_ticket(self, starts_in, *, points=0, redeem=0, base_price=30000):
        hall = make_hall()
        screening = make_screening(hall, starts_in=starts_in, base_price=base_price, surcharge=0)
        shop = self.shop(points=points)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        if redeem:
            shop.price(booking["id"], points=redeem)
        paid = shop.pay(booking["id"])
        self.assertEqual(paid.status_code, 200, paid.text)
        return shop, paid.json()["booking"], hall, screening

    def refund_rows(self, booking_id):
        return sql("SELECT amount, percent, points_restored, points_clawed_back, status, initiated_by FROM refunds "
                   "WHERE booking_id = :b", b=booking_id)

    def payment_status(self, booking_id):
        return scalar("SELECT status FROM payments WHERE booking_id = :b", b=booking_id)

class RefundFlowTests(RefundCase):
    def test_a_cancellation_well_before_the_screening_refunds_everything(self):
        shop, booking, hall, _ = self.paid_ticket(timedelta(hours=30))
        resp = shop.set_status(booking["id"], "cancelled")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual((body["status"], body["refund_percent"], float(body["refund_amount"])), ("cancelled", 100, 30000.0))
        self.assertIsNotNone(body["refunded_at"])
        (row,) = self.refund_rows(booking["id"])
        self.assertEqual((float(row.amount), row.percent, row.status, row.initiated_by), (30000.0, 100, "succeeded_demo", "customer"))
        self.assertEqual(self.payment_status(booking["id"]), "refunded_demo")
        self.assertEqual(self.shop().book(booking["screening_id"], [hall["seat_ids"][0]]).status_code, 201, "the seat is free again")

    def test_a_cancellation_a_few_hours_before_refunds_half(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=5))
        body = shop.set_status(booking["id"], "cancelled").json()
        self.assertEqual((body["refund_percent"], float(body["refund_amount"])), (50, 15000.0))
        self.assertEqual(self.payment_status(booking["id"]), "partially_refunded_demo")

    def test_a_late_cancellation_refunds_nothing_but_still_releases_the_seats(self):
        shop, booking, hall, _ = self.paid_ticket(timedelta(minutes=90))
        body = shop.set_status(booking["id"], "cancelled").json()
        self.assertEqual((body["refund_percent"], float(body["refund_amount"]), body["refunded_at"]), (0, 0.0, None))
        self.assertEqual(self.refund_rows(booking["id"]), [])
        self.assertEqual(self.payment_status(booking["id"]), "succeeded_demo")
        self.assertEqual(scalar("SELECT count(*) FROM booking_notifications WHERE booking_id = :b AND event_type = 'refund'", b=booking["id"]), 0)
        self.assertEqual(self.shop().book(booking["screening_id"], [hall["seat_ids"][0]]).status_code, 201)

    def test_an_operator_cancelling_always_refunds_in_full(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(minutes=90))
        operator = make_user(role=Role.ADMIN)
        resp = self.client.patch(f"/api/bookings/{booking['id']}/status", headers=auth(operator["token"]), json={"status": "cancelled"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual((resp.json()["refund_percent"], float(resp.json()["refund_amount"])), (100, 30000.0))
        self.assertEqual(self.refund_rows(booking["id"])[0].initiated_by, "operator")

    def test_the_amount_is_rounded_down_to_a_whole_sum(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=5), base_price=30001)
        self.assertEqual(float(shop.set_status(booking["id"], "cancelled").json()["refund_amount"]), 15000.0)

    def test_unpaid_holds_have_nothing_to_refund(self):
        hall = make_hall()
        screening = make_screening(hall)
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        body = shop.set_status(booking["id"], "cancelled").json()
        self.assertEqual((body["refund_percent"], float(body["refund_amount"])), (None, 0.0))
        self.assertEqual(self.refund_rows(booking["id"]), [])

    def test_a_checked_in_ticket_cannot_be_cancelled_or_refunded(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(minutes=30))
        operator = make_user(role=Role.ADMIN)
        self.client.post("/api/admin/tickets/check-in", headers=auth(operator["token"]), json={"ticket_code": booking["ticket_code"]})
        self.assertEqual(shop.set_status(booking["id"], "cancelled").status_code, 409)
        self.assertEqual(self.refund_rows(booking["id"]), [])

class PointsTests(RefundCase):
    def test_a_full_refund_gives_back_spent_points_and_takes_back_earned_ones(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=30), points=1000, redeem=100)   # pays 20 000, earns 20
        self.assertEqual(shop.points(), (1000 - 100 + 20, 0))
        shop.set_status(booking["id"], "cancelled")
        self.assertEqual(shop.points(), (1000, 0))
        (row,) = self.refund_rows(booking["id"])
        self.assertEqual((row.points_restored, row.points_clawed_back), (100, 20))

    def test_a_partial_refund_moves_points_in_proportion(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=5), points=1000, redeem=100)
        shop.set_status(booking["id"], "cancelled")
        self.assertEqual(shop.points(), (1000 - 100 + 20 + 50 - 10, 0))
        self.assertEqual(float(self.refund_rows(booking["id"])[0].amount), 10000.0)   # 50% of the 20 000 actually paid

    def test_the_balance_never_goes_negative_when_earned_points_were_already_spent(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=30))                 # earns 30
        sql("UPDATE users SET parda_points = 10 WHERE id = :i", i=shop.user["id"])
        shop.set_status(booking["id"], "cancelled")
        self.assertEqual(shop.points()[0], 0)

class IntegrityTests(RefundCase):
    def test_two_simultaneous_cancellations_refund_once(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=30), points=1000, redeem=100)
        results = run_parallel([lambda: shop.set_status(booking["id"], "cancelled") for _ in range(4)])
        self.assertEqual(sorted(r.status_code for r in results), [200, 422, 422, 422], [r.text for r in results])
        self.assertEqual(len(self.refund_rows(booking["id"])), 1)
        self.assertEqual(shop.points(), (1000, 0))                                     # adjusted exactly once

    def test_the_database_refuses_a_second_refund_for_one_payment(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=30))
        shop.set_status(booking["id"], "cancelled")
        with self.assertRaises(IntegrityError):
            sql("INSERT INTO refunds (payment_id, booking_id, amount, percent, status, initiated_by) "
                "SELECT payment_id, booking_id, 1, 1, 'succeeded_demo', 'customer' FROM refunds WHERE booking_id = :b", b=booking["id"])

    def test_a_refund_cannot_be_zero_or_over_a_hundred_percent(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=30))
        payment_id = scalar("SELECT id FROM payments WHERE booking_id = :b", b=booking["id"])
        for amount, percent in ((0, 50), (100, 0), (100, 101)):
            with self.subTest(amount=amount, percent=percent), self.assertRaises(IntegrityError):
                sql("INSERT INTO refunds (payment_id, booking_id, amount, percent, status, initiated_by) "
                    "VALUES (:p, :b, :a, :c, 'x', 'customer')", p=payment_id, b=booking["id"], a=amount, c=percent)

class QuoteTests(RefundCase):
    def quote(self, shop, booking_id):
        return self.client.get(f"/api/bookings/{booking_id}/cancellation-quote", headers=shop.headers)

    def test_the_quote_matches_what_cancelling_then_does(self):
        for lead, percent in ((timedelta(hours=30), 100), (timedelta(hours=5), 50), (timedelta(minutes=90), 0)):
            with self.subTest(lead=lead):
                shop, booking, _, _ = self.paid_ticket(lead, points=1000, redeem=100)
                quote = self.quote(shop, booking["id"]).json()
                self.assertEqual((quote["paid"], quote["refund_percent"]), (True, percent))
                done = shop.set_status(booking["id"], "cancelled").json()
                self.assertEqual(float(quote["refund_amount"]), float(done["refund_amount"]), "the quote must promise what the cancellation pays")
                self.assertEqual(done["refund_percent"], percent)
                self.assertEqual([s["percent"] for s in quote["policy"]], [100, 50, 0])

    def test_an_unpaid_hold_quotes_no_refund(self):
        hall = make_hall()
        screening = make_screening(hall)
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        quote = self.quote(shop, booking["id"]).json()
        self.assertEqual((quote["paid"], quote["refund_percent"], float(quote["refund_amount"])), (False, 0, 0.0))

    def test_quotes_are_private_to_the_owner_and_operators_quote_full_refunds(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(minutes=90))
        self.assertEqual(self.client.get(f"/api/bookings/{booking['id']}/cancellation-quote", headers=self.shop().headers).status_code, 404)
        self.assertIn(self.client.get(f"/api/bookings/{booking['id']}/cancellation-quote").status_code, (401, 403))
        operator = auth(make_user(role=Role.ADMIN)["token"])
        self.assertEqual(self.client.get(f"/api/bookings/{booking['id']}/cancellation-quote", headers=operator).json()["refund_percent"], 100)

    def test_the_policy_is_public(self):
        resp = self.client.get("/api/refund-policy")
        self.assertEqual([(s["hours_before_start"], s["percent"]) for s in resp.json()], [(24, 100), (2, 50), (0, 0)])

class VisibilityTests(RefundCase):
    def test_the_refund_is_audited(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=5))
        shop.set_status(booking["id"], "cancelled")
        row = sql("SELECT actor_email, details FROM audit_log WHERE action = 'booking.refunded' AND target_id = :b", b=str(booking["id"]))[0]
        self.assertEqual(row.actor_email, shop.user["email"])
        self.assertEqual((row.details["percent"], row.details["initiated_by"]), (50, "customer"))

    def test_the_customer_is_emailed_and_sees_it_in_their_notifications(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=5), points=1000, redeem=100)
        shop.set_status(booking["id"], "cancelled")
        with mock.patch("app.notifications.send_refund_email") as sender, mock.patch("app.notifications.send_screening_reminder_email") as reminder:
            sql("UPDATE booking_notifications SET due_at = now() - interval '1 minute' WHERE booking_id = :b", b=booking["id"])
            deliver_due_notifications()
        sender.assert_called_once()
        kwargs = sender.call_args.kwargs
        self.assertEqual((kwargs["percent"], kwargs["points_restored"], kwargs["amount"]), (50, 50, "10,000 UZS"))
        reminder.assert_not_called()                         # reminders for a cancelled ticket are skipped
        listing = self.client.get("/api/notifications", headers=shop.headers).json()
        self.assertIn(("refund", "sent"), [(n["kind"], n["state"]) for n in listing])

    def test_the_refund_email_is_not_sent_if_the_booking_is_somehow_not_cancelled(self):
        shop, booking, _, _ = self.paid_ticket(timedelta(hours=5))
        shop.set_status(booking["id"], "cancelled")
        sql("UPDATE bookings SET status = 'CONFIRMED' WHERE id = :b", b=booking["id"])
        with mock.patch("app.notifications.send_refund_email") as sender:
            sql("UPDATE booking_notifications SET due_at = now() - interval '1 minute' WHERE booking_id = :b AND event_type = 'refund'", b=booking["id"])
            deliver_due_notifications()
        sender.assert_not_called()

    def test_the_operator_dashboard_totals_the_money_returned(self):
        shop, booking, _, screening = self.paid_ticket(timedelta(hours=5))
        shop.set_status(booking["id"], "cancelled")
        day = (datetime.now(timezone.utc) + timedelta(hours=5)).astimezone(ZoneInfo("Asia/Tashkent")).date().isoformat()
        operator = auth(make_user(role=Role.ADMIN)["token"])
        metrics = self.client.get("/api/admin/dashboard", headers=operator, params={"date": day}).json()["metrics"]
        self.assertGreaterEqual(float(metrics["refunded_amount"]), 15000.0)

if __name__ == "__main__":
    unittest.main()
