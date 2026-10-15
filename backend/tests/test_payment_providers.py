"""Hosted-checkout payments: signed webhooks, idempotency, late payments, provider refunds, the sandbox page."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from app.config import settings
from app.models import Role
from app.payment_providers import ProviderError, SandboxProvider, WebhookRejected, get_provider, sign
from app.reports import PAID_STATUSES
from app.services import POINT_EARN_RATE_UZS
from tests.support import ApiTestCase, auth, make_promo, make_user, run_parallel, scalar, sql
from tests.test_config import make as make_settings

SECRET = "w" * 40
NOW = datetime(2031, 1, 1, 12, 0, tzinfo=timezone.utc)

def body_for(reference="sbx_ref", kind="payment.succeeded", amount="30000", event_id="evt_1") -> bytes:
    return json.dumps({"id": event_id, "type": kind, "reference": reference, "amount": amount}).encode()

class SignatureTests(unittest.TestCase):
    provider = SandboxProvider(SECRET)

    def parse(self, headers, body, now=NOW):
        return self.provider.parse_webhook(headers, body, now)

    def test_a_correctly_signed_event_is_accepted(self):
        body = body_for()
        event = self.parse(self.provider.signed_headers(body, NOW), body)
        self.assertEqual((event.event_id, event.provider_reference, event.kind, event.amount), ("evt_1", "sbx_ref", "paid", Decimal(30000)))

    def test_anything_not_provably_from_the_provider_is_rejected(self):
        body = body_for()
        good = self.provider.signed_headers(body, NOW)
        stamp = int(NOW.timestamp())
        cases = {
            "no headers": {},
            "no signature": {"x-parda-timestamp": str(stamp)},
            "no timestamp": {"x-parda-signature": good["x-parda-signature"]},
            "wrong secret": {"x-parda-timestamp": str(stamp), "x-parda-signature": sign("x" * 40, stamp, body)},
            "garbage timestamp": {"x-parda-timestamp": "yesterday", "x-parda-signature": good["x-parda-signature"]},
            "signature for another timestamp": {"x-parda-timestamp": str(stamp + 1), "x-parda-signature": good["x-parda-signature"]},
        }
        for label, headers in cases.items():
            with self.subTest(label), self.assertRaises(WebhookRejected):
                self.parse(headers, body)
        with self.assertRaises(WebhookRejected):                       # a signed body that was edited afterwards
            self.parse(good, body.replace(b"30000", b"1"))

    def test_old_and_future_timestamps_are_rejected_even_when_signed(self):
        body = body_for()
        for skew in (timedelta(minutes=6), timedelta(minutes=-6), timedelta(days=2)):
            with self.subTest(skew=skew), self.assertRaises(WebhookRejected):
                self.parse(self.provider.signed_headers(body, NOW + skew), body)
        self.parse(self.provider.signed_headers(body, NOW - timedelta(minutes=4)), body)

    def test_an_empty_secret_never_authenticates(self):
        body = body_for()
        weak = SandboxProvider("")
        with self.assertRaises(WebhookRejected):
            weak.parse_webhook(weak.signed_headers(body, NOW), body, NOW)

    def test_signed_but_malformed_events_are_rejected(self):
        for body in (b"not json", b"[]", b'{"type":"payment.succeeded"}', body_for(kind="payment.exploded"),
                     body_for(amount="lots"), body_for(event_id=""), body_for(reference="")):
            with self.subTest(body=body), self.assertRaises(WebhookRejected):
                self.parse(self.provider.signed_headers(body, NOW), body)

class ConfigTests(unittest.TestCase):
    def test_sandbox_is_never_allowed_in_production(self):
        problems = make_settings(payment_provider="sandbox", payment_webhook_secret=SECRET).production_problems()
        self.assertTrue(any("sandbox" in p for p in problems))

    def test_unknown_provider_and_missing_secret_are_refused(self):
        self.assertTrue(any("PAYMENT_PROVIDER must" in p for p in make_settings(payment_provider="paypal").production_problems()))
        self.assertTrue(any("PAYMENT_WEBHOOK_SECRET" in p for p in make_settings(payment_provider="sandbox", payment_webhook_secret="short").production_problems()))
        self.assertEqual(make_settings(payment_provider="demo").production_problems(), [])

    def test_demo_has_no_provider_object(self):
        self.assertIsNone(get_provider("demo"))
        self.assertIsNone(get_provider("unknown"))
        self.assertIsInstance(get_provider("sandbox"), SandboxProvider)

    def test_report_totals_count_provider_payments(self):
        for status in ("succeeded", "refunded", "partially_refunded", "succeeded_demo"):
            self.assertIn(status, PAID_STATUSES)

class ProviderCase(ApiTestCase):
    def setUp(self):
        for name, value in (("payment_provider", "sandbox"), ("payment_webhook_secret", SECRET)):
            patcher = mock.patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")
        patcher = mock.patch("app.routes.checkout.deliver_due_notifications")
        patcher.start()
        self.addCleanup(patcher.stop)

    # ---- helpers
    def pending(self, *, points=0, redeem=0, promo=None, **venue):
        hall, screening = self.venue(base_price=30000, surcharge=0, **venue)
        shop = self.shop(points=points)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        if promo or redeem:
            booking = shop.price(booking["id"], promo_code=promo, points=redeem).json()
        return shop, booking, hall

    def checkout(self, shop, booking_id, key=None):
        headers = dict(shop.headers, **({"Idempotency-Key": key} if key else {}))
        return self.client.post("/api/payments/checkout", headers=headers, json={"booking_id": booking_id})

    def reference(self, payment_id):
        return scalar("SELECT provider_reference FROM payments WHERE id = :i", i=payment_id)

    def send(self, reference, *, kind="payment.succeeded", amount="30000", event_id=None, secret=SECRET, now=None, tamper=False):
        body = body_for(reference, kind, amount, event_id or f"evt_{datetime.now().timestamp()}_{id(object())}")
        headers = SandboxProvider(secret).signed_headers(body, now or datetime.now(timezone.utc))
        if tamper:
            body = body.replace(b"30000", b"1")
        return self.client.post("/api/payments/webhook/sandbox", content=body, headers=headers)

    def paid_booking(self, **kwargs):
        shop, booking, hall = self.pending(**kwargs)
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        outcome = self.send(self.reference(payment_id), amount=str(booking["total_price"]).split(".")[0])
        self.assertEqual(outcome.json(), {"status": "applied"})
        return shop, booking, payment_id

    def booking_row(self, booking_id):
        status, ticket = sql("SELECT status, ticket_code FROM bookings WHERE id = :i", i=booking_id)[0]
        return str(status).lower(), ticket

    def payment_status(self, payment_id):
        return scalar("SELECT status FROM payments WHERE id = :i", i=payment_id)

class CheckoutTests(ProviderCase):
    def test_config_tells_the_app_which_checkout_to_show(self):
        self.assertEqual(self.client.get("/api/payments/config").json(), {"provider": "sandbox"})
        with mock.patch.object(settings, "payment_provider", "demo"):
            self.assertEqual(self.client.get("/api/payments/config").json(), {"provider": "demo"})

    def test_starting_a_checkout_creates_an_open_payment_with_a_hosted_page_link(self):
        shop, booking, _ = self.pending()
        response = self.checkout(shop, booking["id"])
        self.assertEqual(response.status_code, 201, response.text)
        out = response.json()
        self.assertEqual((out["status"], Decimal(out["amount"])), ("awaiting_provider", Decimal(30000)))
        self.assertEqual(out["checkout_url"], f"/api/payments/sandbox/{self.reference(out['payment_id'])}")
        self.assertEqual(self.booking_row(booking["id"])[0], "pending")          # nothing is confirmed by starting

    def test_the_demo_checkout_refuses_a_hosted_payment_request(self):
        shop, booking, _ = self.pending()
        with mock.patch.object(settings, "payment_provider", "demo"):
            self.assertEqual(self.checkout(shop, booking["id"]).status_code, 409)

    def test_coming_back_resumes_the_open_payment_instead_of_starting_another(self):
        shop, booking, _ = self.pending()
        first = self.checkout(shop, booking["id"]).json()
        again = self.checkout(shop, booking["id"])
        self.assertEqual((again.status_code, again.json()["payment_id"]), (200, first["payment_id"]))
        self.assertEqual(scalar("SELECT count(*) FROM payments WHERE booking_id = :i", i=booking["id"]), 1)

    def test_the_same_idempotency_key_returns_the_same_payment_even_after_it_was_paid(self):
        shop, booking, _ = self.pending()
        first = self.checkout(shop, booking["id"], key="try-1").json()
        self.send(self.reference(first["payment_id"]), amount="30000")
        replay = self.checkout(shop, booking["id"], key="try-1")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual((replay.json()["payment_id"], replay.json()["status"], replay.json()["checkout_url"]),
                         (first["payment_id"], "succeeded", None))
        self.assertEqual(scalar("SELECT count(*) FROM payments WHERE booking_id = :i", i=booking["id"]), 1)

    def test_another_customer_cannot_replay_someone_elses_key(self):
        shop, booking, _ = self.pending()
        self.checkout(shop, booking["id"], key="mine")
        thief = self.shop()
        response = self.checkout(thief, booking["id"], key="mine")
        self.assertEqual(response.status_code, 403)

    def test_malformed_idempotency_keys_are_refused(self):
        shop, booking, _ = self.pending()
        for key in ("has space", "x" * 81, "semi;colon"):
            with self.subTest(key=key):
                self.assertEqual(self.checkout(shop, booking["id"], key=key).status_code, 422)

    def test_the_usual_checkout_rules_still_apply(self):
        shop, booking, _ = self.pending()
        self.assertEqual(self.checkout(self.shop(), booking["id"]).status_code, 403)             # not yours
        sql("UPDATE users SET email_verified = false WHERE id = :i", i=shop.user["id"])
        self.assertEqual(self.checkout(shop, booking["id"]).status_code, 403)                    # e-mail unverified
        sql("UPDATE users SET email_verified = true WHERE id = :i", i=shop.user["id"])
        self.assertEqual(self.checkout(shop, 99999999).status_code, 404)
        sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=booking["id"])
        self.assertEqual(self.checkout(shop, booking["id"]).status_code, 410)                    # hold expired

    def test_a_changed_promotion_blocks_checkout(self):
        code = make_promo(percent=10)
        shop, booking, _ = self.pending(promo=code)
        sql("UPDATE promotions SET percent_off = 20 WHERE code = :c", c=code)
        self.assertEqual(self.checkout(shop, booking["id"]).status_code, 409)

    def test_repricing_is_blocked_while_a_payment_is_open(self):
        shop, booking, _ = self.pending()
        self.checkout(shop, booking["id"])
        self.assertEqual(shop.price(booking["id"]).status_code, 409)

    def test_status_is_visible_to_the_owner_only(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        url = f"/api/payments/by-reference/{out['reference']}"
        self.assertEqual(self.client.get(url, headers=shop.headers).json()["status"], "awaiting_provider")
        self.assertEqual(self.client.get(url, headers=auth(make_user()["token"])).status_code, 404)
        self.assertIn(self.client.get(url).status_code, (401, 403))
        self.assertIsNone(self.client.get(url, headers=shop.headers).json()["booking"])

class WebhookTests(ProviderCase):
    def test_a_signed_payment_confirms_the_booking(self):
        shop, booking, payment_id = self.paid_booking()
        status, ticket = self.booking_row(booking["id"])
        self.assertEqual((status, bool(ticket), self.payment_status(payment_id)), ("confirmed", True, "succeeded"))
        self.assertEqual(shop.points(), (int(30000 / POINT_EARN_RATE_UZS), 0))
        self.assertGreater(scalar("SELECT count(*) FROM booking_notifications WHERE booking_id = :i", i=booking["id"]), 0)
        out = self.client.get(f"/api/payments/by-reference/{scalar('SELECT reference FROM payments WHERE id = :i', i=payment_id)}",
                              headers=shop.headers).json()
        self.assertEqual((out["status"], out["booking"]["status"]), ("succeeded", "confirmed"))

    def test_a_forged_or_unsigned_callback_changes_nothing(self):
        shop, booking, _ = self.pending()
        reference = self.reference(self.checkout(shop, booking["id"]).json()["payment_id"])
        for label, response in {
            "wrong secret": self.send(reference, secret="x" * 40),
            "tampered body": self.send(reference, tamper=True),
            "stale": self.send(reference, now=datetime.now(timezone.utc) - timedelta(hours=1)),
            "unsigned": self.client.post("/api/payments/webhook/sandbox", content=body_for(reference)),
        }.items():
            with self.subTest(label):
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.booking_row(booking["id"])[0], "pending")
        self.assertEqual(scalar("SELECT count(*) FROM payment_events"), scalar("SELECT count(*) FROM payment_events WHERE outcome <> 'pending'"))

    def test_the_browser_cannot_confirm_a_booking_itself(self):
        shop, booking, _ = self.pending()
        self.checkout(shop, booking["id"])
        self.assertEqual(shop.set_status(booking["id"], "confirmed").status_code, 403)       # customers can only cancel
        operator = auth(make_user(role=Role.ADMIN)["token"])
        response = self.client.patch(f"/api/bookings/{booking['id']}/status", headers=operator, json={"status": "confirmed"})
        self.assertEqual(response.status_code, 409)                                          # even operators need a paid payment
        self.assertEqual(self.booking_row(booking["id"])[0], "pending")

    def test_unknown_providers_and_demo_mode_have_no_webhook(self):
        self.assertEqual(self.client.post("/api/payments/webhook/stripe", content=b"{}").status_code, 404)
        with mock.patch.object(settings, "payment_provider", "demo"):
            self.assertEqual(self.client.post("/api/payments/webhook/sandbox", content=b"{}").status_code, 404)

    def test_oversized_webhooks_are_refused(self):
        self.assertEqual(self.client.post("/api/payments/webhook/sandbox", content=b"x" * (70 * 1024)).status_code, 413)

    def test_a_redelivered_event_is_applied_once(self):
        shop, booking, _ = self.pending()
        reference = self.reference(self.checkout(shop, booking["id"]).json()["payment_id"])
        first = self.send(reference, event_id="evt_same")
        second = self.send(reference, event_id="evt_same")
        self.assertEqual((first.json()["status"], second.json()["status"]), ("applied", "duplicate"))
        self.assertEqual(shop.points()[0], int(30000 / POINT_EARN_RATE_UZS))
        self.assertEqual(scalar("SELECT count(*) FROM payment_events WHERE event_id = 'evt_same'"), 1)

    def test_simultaneous_deliveries_of_one_event_are_applied_once(self):
        shop, booking, _ = self.pending()
        reference = self.reference(self.checkout(shop, booking["id"]).json()["payment_id"])
        body = body_for(reference, event_id="evt_race")
        headers = SandboxProvider(SECRET).signed_headers(body, datetime.now(timezone.utc))
        results = run_parallel([lambda: self.client.post("/api/payments/webhook/sandbox", content=body, headers=headers)] * 2)
        self.assertEqual(sorted(r.json()["status"] for r in results), ["applied", "duplicate"])
        self.assertEqual(shop.points()[0], int(30000 / POINT_EARN_RATE_UZS))

    def test_a_second_event_for_a_paid_payment_changes_nothing(self):
        shop, booking, payment_id = self.paid_booking()
        before = shop.points()
        self.assertEqual(self.send(self.reference(payment_id)).json()["status"], "already_applied")
        self.assertEqual(self.send(self.reference(payment_id), kind="payment.failed").json()["status"], "ignored")
        self.assertEqual((shop.points(), self.payment_status(payment_id)), (before, "succeeded"))

    def test_a_wrong_amount_is_never_confirmed(self):
        shop, booking, _ = self.pending()
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        self.assertEqual(self.send(self.reference(payment_id), amount="1000").json()["status"], "amount_mismatch")
        self.assertEqual((self.booking_row(booking["id"])[0], self.payment_status(payment_id)), ("pending", "amount_mismatch"))
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE action = 'payment.amount_mismatch' AND target_id = :i", i=str(payment_id)), 1)

    def test_an_event_without_an_amount_is_not_trusted(self):
        shop, booking, _ = self.pending()
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        body = json.dumps({"id": "evt_noamount", "type": "payment.succeeded", "reference": self.reference(payment_id)}).encode()
        headers = SandboxProvider(SECRET).signed_headers(body, datetime.now(timezone.utc))
        self.assertEqual(self.client.post("/api/payments/webhook/sandbox", content=body, headers=headers).json()["status"], "amount_mismatch")
        self.assertEqual(self.booking_row(booking["id"])[0], "pending")

    def test_a_failed_payment_frees_the_booking_to_try_again(self):
        shop, booking, _ = self.pending()
        first = self.checkout(shop, booking["id"]).json()["payment_id"]
        self.assertEqual(self.send(self.reference(first), kind="payment.failed").json()["status"], "failed")
        self.assertEqual(self.payment_status(first), "failed")
        second = self.checkout(shop, booking["id"])
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(second.json()["payment_id"], first)

    def test_an_unknown_payment_is_acknowledged_and_recorded(self):
        response = self.send("sbx_nobody", event_id="evt_unknown")
        self.assertEqual((response.status_code, response.json()["status"]), (200, "unknown_payment"))
        self.assertEqual(scalar("SELECT outcome FROM payment_events WHERE event_id = 'evt_unknown'"), "unknown_payment")

    def test_the_price_the_customer_paid_is_honoured_even_if_the_promotion_lapsed(self):
        code = make_promo(percent=10)
        shop, booking, _ = self.pending(promo=code)
        total = str(booking["total_price"]).split(".")[0]
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        sql("UPDATE promotions SET active = false, usage_limit = 1, usage_count = 1 WHERE code = :c", c=code)
        self.assertEqual(self.send(self.reference(payment_id), amount=total).json()["status"], "applied")
        self.assertEqual(self.booking_row(booking["id"])[0], "confirmed")
        self.assertEqual(scalar("SELECT usage_count FROM promotions WHERE code = :c", c=code), 2)
        self.assertEqual(scalar("SELECT count(*) FROM promotion_redemptions WHERE booking_id = :i", i=booking["id"]), 1)

    def test_redeemed_points_are_spent_on_confirmation(self):
        shop, booking, _ = self.pending(points=10_000, redeem=150)
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        self.assertEqual(shop.points(), (10_000, 150))
        total = str(booking["total_price"]).split(".")[0]
        self.assertEqual(self.send(self.reference(payment_id), amount=total).json()["status"], "applied")
        earned = int(Decimal(total) / POINT_EARN_RATE_UZS)
        self.assertEqual(shop.points(), (10_000 - 150 + earned, 0))

class LatePaymentTests(ProviderCase):
    def test_money_for_a_hold_that_lapsed_but_was_not_yet_swept_still_buys_the_seat(self):
        shop, booking, _ = self.pending()
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=booking["id"])
        self.assertEqual(self.send(self.reference(payment_id)).json()["status"], "applied")
        self.assertEqual(self.booking_row(booking["id"])[0], "confirmed")

    def test_money_for_a_cancelled_booking_is_refunded_automatically(self):
        shop, booking, hall = self.pending()
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        shop.set_status(booking["id"], "cancelled")                       # the customer gave up, then paid anyway
        self.assertEqual(self.send(self.reference(payment_id)).json()["status"], "refunded_unfulfilled")
        self.assertEqual((self.booking_row(booking["id"])[0], self.payment_status(payment_id)), ("cancelled", "refunded"))
        row = sql("SELECT amount, percent, status, initiated_by, provider_reference FROM refunds WHERE payment_id = :i", i=payment_id)[0]
        self.assertEqual((row[0], row[1], row[2], row[3]), (Decimal(30000), 100, "succeeded", "system"))
        self.assertTrue(row[4].startswith("sbx_refund_"))
        self.assertEqual(scalar("SELECT count(*) FROM booking_seats WHERE booking_id = :i AND active", i=booking["id"]), 0)
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE action = 'payment.auto_refunded' AND target_id = :i", i=str(payment_id)), 1)

    def test_if_the_automatic_refund_fails_the_payment_is_flagged_for_a_human(self):
        shop, booking, _ = self.pending()
        payment_id = self.checkout(shop, booking["id"]).json()["payment_id"]
        shop.set_status(booking["id"], "cancelled")
        with mock.patch.object(SandboxProvider, "refund", side_effect=ProviderError("down")):
            self.assertEqual(self.send(self.reference(payment_id)).json()["status"], "paid_unfulfilled")
        self.assertEqual(self.payment_status(payment_id), "paid_unfulfilled")
        self.assertEqual(scalar("SELECT count(*) FROM refunds WHERE payment_id = :i", i=payment_id), 0)
        self.assertEqual(scalar("SELECT count(*) FROM audit_log WHERE action = 'payment.paid_unfulfilled' AND target_id = :i", i=str(payment_id)), 1)
        self.assertEqual(self.send(self.reference(payment_id)).json()["status"], "already_applied")   # a retry does not re-refund

class ProviderRefundTests(ProviderCase):
    def test_cancelling_a_paid_ticket_refunds_through_the_provider(self):
        shop, booking, payment_id = self.paid_booking(starts_in=timedelta(days=3))
        with mock.patch.object(SandboxProvider, "refund", autospec=True, return_value="rf_123") as refund:
            response = shop.set_status(booking["id"], "cancelled")
        self.assertEqual(response.status_code, 200, response.text)
        (_, payment, amount, key), _ = refund.call_args
        self.assertEqual((amount, key, payment.id), (Decimal(30000), f"refund-{payment_id}", payment_id))
        self.assertEqual(self.payment_status(payment_id), "refunded")
        row = sql("SELECT status, provider_reference, amount FROM refunds WHERE payment_id = :i", i=payment_id)[0]
        self.assertEqual((row[0], row[1], row[2]), ("succeeded", "rf_123", Decimal(30000)))

    def test_a_partial_refund_sends_only_the_share(self):
        shop, booking, payment_id = self.paid_booking(starts_in=timedelta(hours=5))
        with mock.patch.object(SandboxProvider, "refund", autospec=True, return_value="rf_half") as refund:
            shop.set_status(booking["id"], "cancelled")
        self.assertEqual(refund.call_args.args[2], Decimal(15000))
        self.assertEqual(self.payment_status(payment_id), "partially_refunded")

    def test_nothing_is_sent_when_no_money_comes_back(self):
        shop, booking, payment_id = self.paid_booking(starts_in=timedelta(minutes=30))
        with mock.patch.object(SandboxProvider, "refund", autospec=True) as refund:
            self.assertEqual(shop.set_status(booking["id"], "cancelled").status_code, 200)
        refund.assert_not_called()
        self.assertEqual(self.payment_status(payment_id), "succeeded")

    def test_if_the_provider_refuses_the_ticket_stays_valid(self):
        shop, booking, payment_id = self.paid_booking(starts_in=timedelta(days=3))
        with mock.patch.object(SandboxProvider, "refund", side_effect=ProviderError("declined")):
            response = shop.set_status(booking["id"], "cancelled")
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual((self.booking_row(booking["id"])[0], self.payment_status(payment_id)), ("confirmed", "succeeded"))
        self.assertEqual(scalar("SELECT count(*) FROM refunds WHERE payment_id = :i", i=payment_id), 0)
        self.assertEqual(scalar("SELECT count(*) FROM booking_seats WHERE booking_id = :i AND active", i=booking["id"]), 1)
        self.assertEqual(shop.points()[0], int(30000 / POINT_EARN_RATE_UZS))          # points untouched too

    def test_provider_refunds_are_idempotent_per_key(self):
        provider = SandboxProvider(SECRET)
        class P:  # a stand-in carrying only what the sandbox reads
            provider_reference = "sbx_x"
        self.assertEqual(provider.refund(P, Decimal(1), "k"), provider.refund(P, Decimal(1), "k"))
        self.assertNotEqual(provider.refund(P, Decimal(1), "k"), provider.refund(P, Decimal(1), "other"))

class SandboxPageTests(ProviderCase):
    def test_the_page_shows_the_payment_and_is_locked_down(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        page = self.client.get(out["checkout_url"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("30,000 UZS", page.text)
        self.assertIn("form-action 'self'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-store")

    def test_titles_are_escaped(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        sql("UPDATE movies SET title = '<script>alert(1)</script>' WHERE id = (SELECT s.movie_id FROM screenings s JOIN bookings b ON b.screening_id = s.id WHERE b.id = :i)", i=booking["id"])
        page = self.client.get(out["checkout_url"]).text
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_paying_on_the_page_confirms_the_booking_and_returns_the_customer(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        response = self.client.post(out["checkout_url"], content="outcome=paid", headers={"content-type": "application/x-www-form-urlencoded"},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"{settings.cors_origins.split(',')[0].rstrip('/')}/?payment={out['reference']}")
        self.assertEqual(self.booking_row(booking["id"])[0], "confirmed")
        self.assertIn("Payment succeeded", self.client.get(out["checkout_url"]).text)          # the page now reports it as settled

    def test_cancelling_on_the_page_fails_the_payment(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        response = self.client.post(out["checkout_url"], content="outcome=failed", headers={"content-type": "application/x-www-form-urlencoded"},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual((self.booking_row(booking["id"])[0], self.payment_status(out["payment_id"])), ("pending", "failed"))

    def test_other_outcomes_and_unknown_payments_are_refused(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        self.assertEqual(self.client.post(out["checkout_url"], content="outcome=refund").status_code, 422)
        self.assertEqual(self.client.get("/api/payments/sandbox/sbx_nope").status_code, 404)

    def test_the_page_does_not_exist_when_the_sandbox_is_off(self):
        shop, booking, _ = self.pending()
        out = self.checkout(shop, booking["id"]).json()
        with mock.patch.object(settings, "payment_provider", "demo"):
            self.assertEqual(self.client.get(out["checkout_url"]).status_code, 404)
            self.assertEqual(self.client.post(out["checkout_url"], content="outcome=paid").status_code, 404)

class DemoUnchangedTests(ApiTestCase):
    def test_the_card_checkout_still_works_and_uses_the_shared_confirmation(self):
        with mock.patch.object(settings, "payment_provider", "demo"), mock.patch("app.routes.payments.deliver_due_notifications"):
            hall, screening = self.venue(base_price=30000, surcharge=0)
            shop = self.shop()
            booking = shop.book(screening, [hall["seat_ids"][0]]).json()
            result = shop.pay(booking["id"])
        self.assertEqual((result.status_code, result.json()["status"]), (200, "succeeded_demo"))

    def test_a_failed_points_check_does_not_leave_a_promotion_redemption_behind(self):
        """The promotion used to be counted before the points were checked, and that count was committed on failure."""
        code = make_promo(percent=10)
        with mock.patch.object(settings, "payment_provider", "demo"):
            hall, screening = self.venue(base_price=30000, surcharge=0)
            shop = self.shop(points=10_000)
            booking = shop.book(screening, [hall["seat_ids"][0]]).json()
            shop.price(booking["id"], promo_code=code, points=100)
            started, otp = shop.start_payment(booking["id"])
            self.assertEqual(started.status_code, 201, started.text)
            sql("UPDATE users SET parda_points = 0 WHERE id = :i", i=shop.user["id"])      # balance vanishes before verification
            result = shop.verify(started.json()["payment_id"], otp)
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(scalar("SELECT usage_count FROM promotions WHERE code = :c", c=code), 0)
        self.assertEqual(scalar("SELECT count(*) FROM promotion_redemptions WHERE booking_id = :i", i=booking["id"]), 0)
        self.assertEqual(scalar("SELECT status FROM payments WHERE booking_id = :i", i=booking["id"]), "loyalty_unavailable")

if __name__ == "__main__":
    unittest.main()
