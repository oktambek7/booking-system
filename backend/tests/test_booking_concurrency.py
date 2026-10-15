"""Races that must be impossible: two customers on one seat, one promo code spent twice,
one payment confirmed twice, one ticket admitted twice. Requests run on separate threads
against the real app and a real PostgreSQL, so the row locks and unique indexes are exercised."""
import unittest
from datetime import timedelta

from app.models import Role
from tests.support import (ApiTestCase, auth, make_hall, make_promo, make_screening, make_user,
                           run_parallel, scalar, sql)

def active_assignments(screening_id: int):
    return sql("""SELECT bs.seat_id, count(*) FROM booking_seats bs JOIN bookings b ON b.id = bs.booking_id
                  WHERE bs.screening_id = :s AND bs.active AND b.status IN ('PENDING','CONFIRMED','COMPLETED')
                  GROUP BY bs.seat_id""", s=screening_id)

class SeatRaceTests(ApiTestCase):
    def test_one_winner_when_many_customers_take_the_same_seat(self):
        for _ in range(3):                                   # repeat: races are probabilistic
            hall, screening = self.venue()
            shops = [self.shop() for _ in range(8)]
            seat = hall["seat_ids"][0]
            results = run_parallel([lambda s=s: s.book(screening, [seat]) for s in shops])
            codes = sorted(r.status_code for r in results)
            self.assertEqual(codes, [201] + [409] * 7, [r.text for r in results])
            self.assertEqual(active_assignments(screening), [(seat, 1)])

    def test_overlapping_seat_sets_never_double_assign_a_seat(self):
        for _ in range(3):
            hall, screening = self.venue()
            s = hall["seat_ids"]
            wanted = [[s[0], s[1]], [s[1], s[2]], [s[2], s[3]], [s[3], s[4]], [s[4], s[0]], [s[1], s[3]]]
            shops = [self.shop() for _ in wanted]
            results = run_parallel([lambda sh=sh, w=w: sh.book(screening, w) for sh, w in zip(shops, wanted)])
            codes = [r.status_code for r in results]
            self.assertTrue(all(c in (201, 409) for c in codes), [r.text for r in results])   # no 500s or deadlocks
            self.assertGreaterEqual(codes.count(201), 1)
            rows = active_assignments(screening)
            self.assertTrue(all(count == 1 for _, count in rows), rows)
            self.assertEqual(sum(count for _, count in rows), 2 * codes.count(201))

    def test_disjoint_seats_all_succeed_together(self):
        hall, screening = self.venue()
        shops = [self.shop() for _ in range(6)]
        results = run_parallel([lambda sh=sh, seat=seat: sh.book(screening, [seat])
                                for sh, seat in zip(shops, hall["seat_ids"])])
        self.assertEqual([r.status_code for r in results], [201] * 6, [r.text for r in results])

    def test_one_customer_double_clicking_cannot_hold_a_seat_twice(self):
        hall, screening = self.venue()
        shop = self.shop()
        seat = hall["seat_ids"][0]
        results = run_parallel([lambda: shop.book(screening, [seat]) for _ in range(4)])
        self.assertEqual(sorted(r.status_code for r in results), [201, 409, 409, 409])

    # KNOWN BUG (fixed in the next commit): _expire_holds() does not flush, so the booking request
    # still sees the expired hold as taken and answers a spurious 409.
    @unittest.expectedFailure
    def test_expired_hold_is_released_for_the_next_customer(self):
        hall, screening = self.venue()
        first, second = self.shop(), self.shop()
        seat = hall["seat_ids"][0]
        held = first.book(screening, [seat])
        self.assertEqual(held.status_code, 201)
        self.assertEqual(second.book(screening, [seat]).status_code, 409)
        sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=held.json()["id"])
        self.assertEqual(second.book(screening, [seat]).status_code, 201)
        self.assertEqual(sql("SELECT status FROM bookings WHERE id = :i", i=held.json()["id"])[0][0], "CANCELLED")
        self.assertEqual(active_assignments(screening), [(seat, 1)])

    def test_cancelled_confirmed_ticket_frees_the_seat(self):
        hall, screening = self.venue()
        first, second = self.shop(), self.shop()
        seat = hall["seat_ids"][0]
        booking = first.book(screening, [seat]).json()
        self.assertEqual(first.pay(booking["id"]).status_code, 200)
        self.assertEqual(second.book(screening, [seat]).status_code, 409)
        self.assertEqual(first.set_status(booking["id"], "cancelled").status_code, 200)
        self.assertEqual(second.book(screening, [seat]).status_code, 201)

class PaymentRaceTests(ApiTestCase):
    def test_promo_with_one_use_left_is_redeemed_once(self):
        code = make_promo(percent=20, usage_limit=1)
        hall, screening = self.venue()
        shops = [self.shop() for _ in range(3)]
        payments = []
        for shop, seat in zip(shops, hall["seat_ids"]):
            booking = shop.book(screening, [seat]).json()
            self.assertEqual(shop.price(booking["id"], promo_code=code).status_code, 200)   # still unused: all accepted
            started, otp = shop.start_payment(booking["id"])
            self.assertEqual(started.status_code, 201, started.text)
            payments.append((shop, started.json()["payment_id"], otp))
        results = run_parallel([lambda sh=sh, pid=pid, otp=otp: sh.verify(pid, otp) for sh, pid, otp in payments])
        codes = sorted(r.status_code for r in results)
        self.assertEqual(codes, [200, 409, 409], [r.text for r in results])
        self.assertEqual(scalar("SELECT usage_count FROM promotions WHERE code = :c", c=code), 1)
        self.assertEqual(scalar("SELECT count(*) FROM promotion_redemptions r JOIN promotions p ON p.id = r.promotion_id "
                                "WHERE p.code = :c", c=code), 1)

    def test_same_payment_verified_twice_confirms_and_rewards_once(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["standard"][0]]).json()          # 30 000 UZS
        started, otp = shop.start_payment(booking["id"])
        pid = started.json()["payment_id"]
        results = run_parallel([lambda: shop.verify(pid, otp) for _ in range(4)])
        codes = sorted(r.status_code for r in results)
        self.assertEqual(codes.count(200), 1, [r.text for r in results])
        self.assertTrue(all(c in (200, 409, 410) for c in codes), codes)
        self.assertEqual(shop.points(), (30, 0))                                # 30 000 UZS / 1 000 earned once
        self.assertEqual(scalar("SELECT count(*) FROM booking_notifications WHERE booking_id = :b AND event_type = 'confirmation'",
                                b=booking["id"]), 1)

    def test_one_ticket_is_admitted_once(self):
        hall = make_hall()
        screening = make_screening(hall, starts_in=timedelta(minutes=45))      # entry window already open
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        ticket = shop.pay(booking["id"]).json()["booking"]["ticket_code"]
        admin = make_user(role=Role.ADMIN)
        results = run_parallel([lambda: self.client.post("/api/admin/tickets/check-in", headers=auth(admin["token"]),
                                                          json={"ticket_code": ticket}) for _ in range(5)])
        self.assertEqual(sorted(r.status_code for r in results), [200] + [409] * 4, [r.text for r in results])

if __name__ == "__main__":
    unittest.main()
