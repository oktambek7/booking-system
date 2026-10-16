"""Business rules around seat holds, pricing, promo codes, Phantora Pass points, payment and check-in."""
import unittest
from datetime import timedelta
from decimal import Decimal

from app.config import settings
from app.models import Role
from tests.support import (ApiTestCase, auth, make_hall, make_promo, make_screening, make_user, run_parallel,
                           scalar, sql)

def money(value) -> Decimal:
    return Decimal(str(value))

class HoldValidationTests(ApiTestCase):
    def test_requires_a_signed_in_customer(self):
        hall, screening = self.venue()
        resp = self.client.post("/api/bookings", json={"screening_id": screening, "seat_ids": [hall["seat_ids"][0]]})
        self.assertIn(resp.status_code, (401, 403))

    def test_rejects_duplicate_seats(self):
        hall, screening = self.venue()
        seat = hall["seat_ids"][0]
        self.assertEqual(self.shop().book(screening, [seat, seat]).status_code, 422)

    def test_rejects_more_than_eight_seats(self):
        hall, screening = self.venue()
        self.assertEqual(self.shop().book(screening, hall["seat_ids"][:9]).status_code, 422)

    def test_rejects_seats_from_another_hall(self):
        _, screening = self.venue()
        other = make_hall()
        resp = self.shop().book(screening, [other["seat_ids"][0]])
        self.assertEqual(resp.status_code, 422)

    def test_rejects_unknown_screening_and_started_screening(self):
        hall, _ = self.venue()
        shop = self.shop()
        self.assertEqual(shop.book(999_999_999, [hall["seat_ids"][0]]).status_code, 404)
        started = make_screening(make_hall(), starts_in=timedelta(minutes=-10))
        self.assertEqual(shop.book(started, [make_hall()["seat_ids"][0]]).status_code, 410)

    def test_hold_lasts_about_ten_minutes(self):
        hall, screening = self.venue()
        booking = self.shop().book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(booking["status"], "pending")
        self.assertTrue(540 <= booking["hold_seconds_remaining"] <= 600, booking["hold_seconds_remaining"])

class HoldLimitTests(ApiTestCase):
    """One customer must not be able to tie up seats with a pile of unpaid holds."""

    def _hold_on_new_screenings(self, shop, count):
        responses = []
        for _ in range(count):
            hall, screening = self.venue()
            responses.append(shop.book(screening, [hall["seat_ids"][0]]))
        return responses

    def test_a_customer_can_only_have_three_unpaid_holds(self):
        shop = self.shop()
        codes = [r.status_code for r in self._hold_on_new_screenings(shop, 5)]
        self.assertEqual(codes, [201, 201, 201, 409, 409])

    def test_the_refusal_explains_what_to_do(self):
        shop = self.shop()
        self._hold_on_new_screenings(shop, 3)
        hall, screening = self.venue()
        detail = shop.book(screening, [hall["seat_ids"][0]]).json()["detail"]
        self.assertIn("3 seat holds", detail)
        self.assertRegex(detail, r"about \d+ min")

    def test_cancelling_a_hold_makes_room(self):
        shop = self.shop()
        held = self._hold_on_new_screenings(shop, 3)
        self.assertEqual(self._hold_on_new_screenings(shop, 1)[0].status_code, 409)
        self.assertEqual(shop.set_status(held[0].json()["id"], "cancelled").status_code, 200)
        self.assertEqual(self._hold_on_new_screenings(shop, 1)[0].status_code, 201)

    def test_expired_holds_do_not_count(self):
        shop = self.shop()
        held = self._hold_on_new_screenings(shop, 3)
        for response in held:
            sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=response.json()["id"])
        self.assertEqual(self._hold_on_new_screenings(shop, 1)[0].status_code, 201)

    def test_paid_tickets_do_not_count(self):
        shop = self.shop()
        held = self._hold_on_new_screenings(shop, 3)
        self.assertEqual(shop.pay(held[0].json()["id"]).status_code, 200)
        self.assertEqual(self._hold_on_new_screenings(shop, 1)[0].status_code, 201)

    def test_limits_are_per_customer(self):
        busy, other = self.shop(), self.shop()
        self._hold_on_new_screenings(busy, 3)
        self.assertEqual(self._hold_on_new_screenings(other, 1)[0].status_code, 201)

    def test_unpaid_seats_for_one_screening_are_capped(self):
        hall, screening = self.venue()
        shop = self.shop()
        seats = hall["seat_ids"]
        self.assertEqual(shop.book(screening, seats[0:5]).status_code, 201)
        over = shop.book(screening, seats[5:9])                      # 5 held + 4 more = 9 > 8
        self.assertEqual(over.status_code, 409)
        self.assertIn("at most 8", over.json()["detail"])
        self.assertEqual(shop.book(screening, seats[5:8]).status_code, 201)     # exactly 8 is fine

    def test_parallel_requests_cannot_slip_past_the_cap(self):
        for _ in range(2):
            shop = self.shop()
            venues = [self.venue() for _ in range(8)]
            results = run_parallel([lambda sh=shop, h=hall, sc=screening: sh.book(sc, [h["seat_ids"][0]]) for hall, screening in venues])
            codes = sorted(r.status_code for r in results)
            self.assertEqual(codes, [201] * 3 + [409] * 5, [r.text for r in results])
            self.assertEqual(scalar("SELECT count(*) FROM bookings WHERE customer_id = :c AND status = 'PENDING'",
                                    c=shop.user["id"]), 3)

    def test_limits_can_be_configured(self):
        original = settings.max_pending_holds_per_user
        settings.max_pending_holds_per_user = 1
        try:
            codes = [r.status_code for r in self._hold_on_new_screenings(self.shop(), 2)]
        finally:
            settings.max_pending_holds_per_user = original
        self.assertEqual(codes, [201, 409])

class PricingTests(ApiTestCase):
    def test_total_adds_premium_surcharge_per_seat(self):
        hall, screening = self.venue(base_price=30000, surcharge=10000)
        seats = [hall["premium"][0], hall["premium"][1], hall["standard"][0]]
        booking = self.shop().book(screening, seats).json()
        self.assertEqual(money(booking["total_price"]), Decimal(30000 * 3 + 10000 * 2))
        self.assertEqual(booking["seat_count"], 3)

    def test_percentage_promo_is_rounded_down(self):
        code = make_promo(percent=15)
        hall, screening = self.venue(base_price=30001, surcharge=0)
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        priced = shop.price(booking["id"], promo_code=code.lower()).json()      # codes are case-insensitive
        self.assertEqual(money(priced["promotion_discount"]), Decimal(4500))    # floor(30001 * 15 / 100)
        self.assertEqual(money(priced["total_price"]), Decimal(30001 - 4500))

    def test_promo_discount_respects_cap(self):
        code = make_promo(percent=50, max_discount=5000)
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        priced = shop.price(booking["id"], promo_code=code).json()
        self.assertEqual(money(priced["promotion_discount"]), Decimal(5000))
        self.assertEqual(money(priced["total_price"]), Decimal(25000))

    def test_unusable_promos_are_refused(self):
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        for label, code in {
            "unknown": "NOSUCHCODE",
            "inactive": make_promo(active=False),
            "expired": make_promo(ends_in=timedelta(hours=-1)),
            "not started": make_promo(starts_in=timedelta(hours=1)),
            "minimum not met": make_promo(min_order=100000),
        }.items():
            with self.subTest(label):
                self.assertEqual(shop.price(booking["id"], promo_code=code).status_code, 422)

    def test_used_up_promo_is_refused(self):
        code = make_promo(usage_limit=1)
        sql("UPDATE promotions SET usage_count = 1 WHERE code = :c", c=code)
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(shop.price(booking["id"], promo_code=code).status_code, 422)

    def test_points_are_capped_at_half_the_price(self):
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop(points=10_000)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()           # max = 30000 / (2 * 100) = 150 points
        self.assertEqual(shop.price(booking["id"], points=151).status_code, 422)
        priced = shop.price(booking["id"], points=150).json()
        self.assertEqual(money(priced["points_discount_amount"]), Decimal(15000))
        self.assertEqual(money(priced["total_price"]), Decimal(15000))

    def test_cannot_redeem_more_points_than_available(self):
        hall, screening = self.venue()
        shop = self.shop(points=40)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(shop.price(booking["id"], points=41).status_code, 422)

    def test_points_apply_after_the_promo_discount(self):
        code = make_promo(percent=50)
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop(points=10_000)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()           # 15 000 after promo -> max 75 points
        self.assertEqual(shop.price(booking["id"], promo_code=code, points=76).status_code, 422)
        self.assertEqual(money(shop.price(booking["id"], promo_code=code, points=75).json()["total_price"]), Decimal(7500))

    def test_repricing_replaces_the_reservation_instead_of_stacking(self):
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop(points=1000)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.price(booking["id"], points=100)
        self.assertEqual(shop.points(), (1000, 100))
        shop.price(booking["id"], points=50)
        self.assertEqual(shop.points(), (1000, 50))
        shop.price(booking["id"], points=0)
        self.assertEqual(shop.points(), (1000, 0))

    def test_points_reserved_for_one_booking_are_not_available_to_another(self):
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop(points=100)
        first = shop.book(screening, [hall["seat_ids"][0]]).json()
        second = shop.book(screening, [hall["seat_ids"][1]]).json()
        self.assertEqual(shop.price(first["id"], points=100).status_code, 200)
        self.assertEqual(shop.price(second["id"], points=1).status_code, 422)

class PaymentTests(ApiTestCase):
    def test_successful_payment_confirms_issues_ticket_and_settles_points(self):
        hall, screening = self.venue(base_price=30000, surcharge=10000)
        shop = self.shop(points=1000)
        booking = shop.book(screening, [hall["premium"][0], hall["standard"][0]]).json()    # 70 000 UZS
        shop.price(booking["id"], points=100)                                                # -10 000 -> 60 000
        done = shop.pay(booking["id"])
        self.assertEqual(done.status_code, 200, done.text)
        confirmed = done.json()["booking"]
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["ticket_code"].startswith("PRD-"))
        self.assertIsNone(confirmed["hold_expires_at"])
        self.assertEqual(confirmed["points_earned"], 60)                                     # 60 000 / 1 000
        self.assertEqual(shop.points(), (1000 - 100 + 60, 0))

    def test_wrong_codes_lock_the_attempt_and_leave_the_hold_unpaid(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        started, otp = shop.start_payment(booking["id"])
        pid = started.json()["payment_id"]
        wrong = "0000" if otp != "0000" else "1111"
        self.assertEqual([shop.verify(pid, wrong).status_code for _ in range(4)], [422] * 4)
        self.assertEqual(shop.verify(pid, wrong).status_code, 429)
        self.assertEqual(shop.verify(pid, otp).status_code, 410)                              # even the right code is dead now
        self.assertEqual(sql("SELECT status FROM bookings WHERE id = :i", i=booking["id"])[0][0], "PENDING")

    def test_cannot_pay_for_someone_elses_booking(self):
        hall, screening = self.venue()
        owner, intruder = self.shop(), self.shop()
        booking = owner.book(screening, [hall["seat_ids"][0]]).json()
        started, _ = intruder.start_payment(booking["id"])
        self.assertEqual(started.status_code, 403)

    def test_an_already_paid_booking_cannot_be_paid_again(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(shop.pay(booking["id"]).status_code, 200)
        started, _ = shop.start_payment(booking["id"])
        self.assertEqual(started.status_code, 409)

    def test_card_validation(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        body = {"method": "visa", "booking_id": booking["id"], "card_number": "4111111111111111",
                "cardholder_name": "Test Customer", "expiry_date": "12 / 40", "cvv": "123"}
        for label, change in {"missing cvv": {"cvv": None}, "expired": {"expiry_date": "01 / 20"},
                              "bad month": {"expiry_date": "13 / 40"}, "digits in name": {"cardholder_name": "Bob 3000"},
                              "uzcard with cvv": {"method": "uzcard"}}.items():
            with self.subTest(label):
                resp = self.client.post("/api/payments/create", headers=shop.headers, json={**body, **change})
                self.assertEqual(resp.status_code, 422, resp.text)

class CancellationTests(ApiTestCase):
    def test_customer_cannot_cancel_someone_elses_booking(self):
        hall, screening = self.venue()
        owner, other = self.shop(), self.shop()
        booking = owner.book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(other.set_status(booking["id"], "cancelled").status_code, 403)

    def test_cancelled_booking_cannot_be_revived(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        self.assertEqual(shop.set_status(booking["id"], "cancelled").status_code, 200)
        self.assertEqual(shop.set_status(booking["id"], "confirmed").status_code, 403)    # customers may only cancel

    def test_cancelling_a_pending_booking_releases_reserved_points(self):
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop(points=500)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.price(booking["id"], points=100)
        self.assertEqual(shop.points(), (500, 100))
        self.assertEqual(shop.set_status(booking["id"], "cancelled").status_code, 200)
        self.assertEqual(shop.points(), (500, 0))

    def test_expired_hold_releases_reserved_points(self):
        hall, screening = self.venue(base_price=30000, surcharge=0)
        shop = self.shop(points=500)
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.price(booking["id"], points=100)
        sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=booking["id"])
        self.assertEqual(self.client.get("/api/bookings", headers=shop.headers).status_code, 200)   # any read expires holds
        self.assertEqual(shop.points(), (500, 0))

class CheckInTests(ApiTestCase):
    def _ticket(self, **screening_kwargs):
        hall = make_hall()
        screening = make_screening(hall, **screening_kwargs)
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        return shop, booking, shop.pay(booking["id"]).json()["booking"]["ticket_code"], screening

    def _check_in(self, ticket, token):
        return self.client.post("/api/admin/tickets/check-in", headers=auth(token), json={"ticket_code": ticket})

    def test_valid_ticket_is_admitted_once(self):
        _, _, ticket, _ = self._ticket(starts_in=timedelta(minutes=30))
        admin = make_user(role=Role.ADMIN)["token"]
        self.assertEqual(self._check_in(ticket, admin).status_code, 200)
        self.assertEqual(self._check_in(ticket, admin).status_code, 409)

    def test_entry_opens_two_hours_before_the_screening(self):
        _, _, ticket, _ = self._ticket(starts_in=timedelta(hours=5))
        self.assertEqual(self._check_in(ticket, make_user(role=Role.ADMIN)["token"]).status_code, 422)

    def test_ended_screening_cannot_be_entered(self):
        _, _, ticket, screening = self._ticket(starts_in=timedelta(minutes=30))
        sql("UPDATE screenings SET starts_at = now() - interval '3 hours', ends_at = now() - interval '1 hour' WHERE id = :i", i=screening)
        self.assertEqual(self._check_in(ticket, make_user(role=Role.ADMIN)["token"]).status_code, 410)

    def test_cancelled_ticket_is_not_admitted(self):
        shop, booking, ticket, _ = self._ticket(starts_in=timedelta(minutes=30))
        self.assertEqual(shop.set_status(booking["id"], "cancelled").status_code, 200)
        self.assertEqual(self._check_in(ticket, make_user(role=Role.ADMIN)["token"]).status_code, 409)

    def test_customers_cannot_check_tickets_in(self):
        _, _, ticket, _ = self._ticket(starts_in=timedelta(minutes=30))
        self.assertEqual(self._check_in(ticket, make_user()["token"]).status_code, 403)

    def test_unknown_ticket(self):
        self.assertEqual(self._check_in("PRD-NOSUCHCD", make_user(role=Role.ADMIN)["token"]).status_code, 404)

    def test_checked_in_ticket_cannot_be_cancelled(self):
        shop, booking, ticket, _ = self._ticket(starts_in=timedelta(minutes=30))
        self._check_in(ticket, make_user(role=Role.ADMIN)["token"])
        self.assertEqual(shop.set_status(booking["id"], "cancelled").status_code, 409)
        self.assertEqual(scalar("SELECT count(*) FROM booking_seats WHERE booking_id = :b AND active", b=booking["id"]), 1)

if __name__ == "__main__":
    unittest.main()
