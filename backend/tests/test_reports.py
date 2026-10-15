"""Operator CSV reports: access, content, spreadsheet-injection safety, ranges, time zones and money."""
import csv
import io
import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import Role
from app.reports import BOOKING_COLUMNS, REVENUE_COLUMNS, safe_cell
from tests.support import ApiTestCase, auth, make_hall, make_screening, make_user, scalar, sql

TASHKENT = ZoneInfo("Asia/Tashkent")
DAY = date(2031, 3, 14)               # far from any other test's data

def parse(response):
    assert response.status_code == 200, response.text
    text = response.content.decode("utf-8")
    assert text.startswith("﻿"), "Excel needs the UTF-8 byte-order mark"
    return list(csv.reader(io.StringIO(text[1:])))

def place(screening_id, local: datetime):
    start = local.astimezone(timezone.utc)
    sql("UPDATE screenings SET starts_at = :s, ends_at = :e WHERE id = :i", s=start, e=start + timedelta(hours=2), i=screening_id)

class ReportCase(ApiTestCase):
    def setUp(self):
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")
        self.operator = auth(make_user(role=Role.ADMIN)["token"])

    def at(self, local: datetime, **screening):
        hall = make_hall()
        screening_id = make_screening(hall, surcharge=0, **screening)
        place(screening_id, local)
        return hall, screening_id

    def get(self, name, start=DAY, end=DAY, headers=None, **params):
        return self.client.get(f"/api/admin/reports/{name}.csv", headers=headers or self.operator,
                               params={"from": start.isoformat(), "to": end.isoformat(), **params})

class AccessTests(ReportCase):
    def test_only_operators_can_export(self):
        for name in ("bookings", "revenue"):
            self.assertEqual(self.get(name, headers=auth(make_user()["token"])).status_code, 403)
            self.assertIn(self.client.get(f"/api/admin/reports/{name}.csv", params={"from": "2031-01-01", "to": "2031-01-02"}).status_code, (401, 403))

    def test_downloads_are_private_csv_files(self):
        resp = self.get("bookings")
        self.assertEqual(resp.headers["Content-Type"], "text/csv; charset=utf-8")
        self.assertRegex(resp.headers["Content-Disposition"], r'^attachment; filename="parda-bookings-2031-03-14_2031-03-14\.csv"$')
        self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_each_export_is_audited(self):
        operator = make_user(role=Role.ADMIN)
        self.client.get("/api/admin/reports/revenue.csv", headers=auth(operator["token"]), params={"from": "2031-05-01", "to": "2031-05-31"})
        row = sql("SELECT details FROM audit_log WHERE action = 'report.exported' AND actor_email = :e", e=operator["email"])[0]
        self.assertEqual((row.details["start"], row.details["end"]), ("2031-05-01", "2031-05-31"))

class RangeTests(ReportCase):
    def test_bad_ranges_are_refused(self):
        for params in ({"from": "2031-03-15", "to": "2031-03-14"}, {"from": "2030-01-01", "to": "2031-03-14"}, {"from": "not-a-date", "to": "2031-03-14"}, {"from": "2031-03-14"}, {}):
            for name in ("bookings", "revenue"):
                with self.subTest(params=params, report=name):
                    self.assertEqual(self.client.get(f"/api/admin/reports/{name}.csv", headers=self.operator, params=params).status_code, 422)

    def test_a_full_year_is_allowed(self):
        self.assertEqual(self.get("bookings", date(2031, 1, 1), date(2031, 12, 31)).status_code, 200)

    def test_days_follow_the_business_time_zone_not_utc(self):
        late_hall, late = self.at(datetime(2031, 3, 14, 23, 30, tzinfo=TASHKENT))      # still the 14th in Tashkent (18:30 UTC)
        early_hall, early = self.at(datetime(2031, 3, 15, 0, 30, tzinfo=TASHKENT))     # already the 15th in Tashkent (19:30 UTC on the 14th)
        for screening, hall in ((late, late_hall), (early, early_hall)):
            self.shop().book(screening, [hall["seat_ids"][0]])
        title = lambda screening: scalar("SELECT m.title FROM screenings s JOIN movies m ON m.id = s.movie_id WHERE s.id = :i", i=screening)  # noqa: E731
        titles_14 = {row[4] for row in parse(self.get("bookings", DAY, DAY))[1:]}
        titles_15 = {row[4] for row in parse(self.get("bookings", date(2031, 3, 15), date(2031, 3, 15)))[1:]}
        self.assertIn(title(late), titles_14)
        self.assertNotIn(title(early), titles_14, "19:30 UTC on the 14th is already the 15th in Tashkent")
        self.assertIn(title(early), titles_15)
        self.assertNotIn(title(late), titles_15)

class BookingReportTests(ReportCase):
    def test_columns_rows_and_values(self):
        hall, screening = self.at(datetime(2031, 3, 14, 15, 0, tzinfo=TASHKENT))
        shop = self.shop()
        paid = shop.book(screening, hall["seat_ids"][:2]).json()
        shop.pay(paid["id"])
        outside_hall, outside = self.at(datetime(2031, 3, 20, 15, 0, tzinfo=TASHKENT))
        self.shop().book(outside, [outside_hall["seat_ids"][0]])
        rows = parse(self.get("bookings"))
        self.assertEqual(rows[0], BOOKING_COLUMNS)
        mine = [dict(zip(rows[0], r)) for r in rows[1:] if r[0] == str(paid["id"])]
        self.assertEqual(len(mine), 1)
        row = mine[0]
        self.assertEqual((row["status"], row["seats"], row["seat_count"], float(row["total_uzs"]), row["screening_start"]),
                         ("confirmed", "A1, A2", "2", 60000.0, "2031-03-14 15:00"))
        self.assertEqual((row["customer_email"], row["ticket_code"].startswith("PRD-")), (shop.user["email"], True))
        self.assertNotIn(str(outside), [r[0] for r in rows[1:]], "bookings outside the range must not appear")

    def test_cancelled_bookings_show_their_refund(self):
        hall, screening = self.at(datetime(2031, 3, 14, 15, 0, tzinfo=TASHKENT))
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.pay(booking["id"])
        sql("UPDATE screenings SET starts_at = now() + interval '30 hours', ends_at = now() + interval '32 hours' WHERE id = :i", i=screening)
        shop.set_status(booking["id"], "cancelled")
        place(screening, datetime(2031, 3, 14, 15, 0, tzinfo=TASHKENT))
        rows = parse(self.get("bookings"))
        row = dict(zip(rows[0], next(r for r in rows[1:] if r[0] == str(booking["id"]))))
        self.assertEqual((row["status"], row["refund_percent"], float(row["refund_uzs"]), row["seats"]), ("cancelled", "100", 30000.0, "A1"))

    def test_text_in_other_languages_survives(self):
        hall, screening = self.at(datetime(2031, 3, 14, 12, 0, tzinfo=TASHKENT))
        sql("UPDATE movies SET title = :t WHERE id = (SELECT movie_id FROM screenings WHERE id = :i)", t="Руки Вверх 2! · O‘zbek tilida", i=screening)
        self.shop().book(screening, [hall["seat_ids"][0]])
        self.assertIn("Руки Вверх 2! · O‘zbek tilida", [r[4] for r in parse(self.get("bookings"))[1:]])

    def test_every_booking_is_present_exactly_once_across_stream_chunks(self):
        hall, screening = self.at(datetime(2031, 4, 2, 12, 0, tzinfo=TASHKENT))
        customer = make_user()
        sql("""INSERT INTO bookings (customer_id, screening_id, status, seat_count, total_price, subtotal_price, promotion_discount,
                                     points_redeemed, points_discount_amount, points_earned, archived_by_customer)
               SELECT :c, :s, 'CANCELLED', 1, 1000, 1000, 0, 0, 0, 0, false FROM generate_series(1, 450)""", c=customer["id"], s=screening)
        rows = parse(self.get("bookings", date(2031, 4, 2), date(2031, 4, 2)))[1:]
        ids = [r[0] for r in rows]
        self.assertEqual((len(ids), len(set(ids))), (450, 450))

class InjectionTests(ReportCase):
    PAYLOADS = ['=HYPERLINK("http://e.co","click")', "+cmd|' /C calc'!A0", "-2+3+cmd|' /C calc'!A0", "@SUM(1+1)*cmd|' /C calc'!A0", "\t=1+1", "\r=1+1"]

    def test_safe_cell_prefixes_dangerous_text_and_leaves_the_rest(self):
        for payload in self.PAYLOADS:
            self.assertEqual(safe_cell(payload), "'" + payload)
        for harmless in ("Normal Name", "O‘zbek", "12:30", "", None, "a=b", "x+y"):
            self.assertEqual(safe_cell(harmless), "" if harmless is None else harmless)

    def test_no_cell_in_either_report_can_start_a_formula(self):
        hall, screening = self.at(datetime(2031, 3, 14, 18, 0, tzinfo=TASHKENT))
        customer = self.shop()
        booking = customer.book(screening, [hall["seat_ids"][0]]).json()
        customer.pay(booking["id"])
        evil = self.PAYLOADS
        sql("UPDATE users SET nickname = :n WHERE id = :u", n=evil[0], u=customer.user["id"])
        sql("UPDATE movies SET title = :t WHERE id = (SELECT movie_id FROM screenings WHERE id = :i)", t=evil[1], i=screening)
        sql("UPDATE auditoriums SET cinema_name = :c, name = :h WHERE id = :a", c=evil[2], h=evil[3], a=hall["id"])
        for name in ("bookings", "revenue"):
            rows = parse(self.get(name))
            self.assertGreater(len(rows), 1)
            dangerous = [cell for row in rows for cell in row if cell.startswith(("=", "+", "-", "@", "\t", "\r"))]
            self.assertEqual(dangerous, [], f"{name} report has formula-capable cells")
        rows = parse(self.get("bookings"))
        mine = next(dict(zip(rows[0], r)) for r in rows[1:] if r[0] == str(booking["id"]))
        self.assertEqual((mine["customer_nickname"], mine["movie"]), ("'" + evil[0], "'" + evil[1]))

class RevenueReportTests(ReportCase):
    def test_paid_refunded_and_net_per_day_hall_and_film(self):
        hall, screening = self.at(datetime(2031, 3, 14, 20, 0, tzinfo=TASHKENT))
        kept, refunded, unpaid = self.shop(), self.shop(), self.shop()
        kept_booking = kept.book(screening, [hall["seat_ids"][0]]).json()
        kept.pay(kept_booking["id"])
        gone = refunded.book(screening, [hall["seat_ids"][1]]).json()
        refunded.pay(gone["id"])
        unpaid.book(screening, [hall["seat_ids"][2]])
        sql("UPDATE screenings SET starts_at = now() + interval '30 hours', ends_at = now() + interval '32 hours' WHERE id = :i", i=screening)
        refunded.set_status(gone["id"], "cancelled")                                        # 100% back
        place(screening, datetime(2031, 3, 14, 20, 0, tzinfo=TASHKENT))
        rows = parse(self.get("revenue"))
        self.assertEqual(rows[0], REVENUE_COLUMNS)
        title = scalar("SELECT m.title FROM screenings s JOIN movies m ON m.id = s.movie_id WHERE s.id = :i", i=screening)
        line = dict(zip(rows[0], next(r for r in rows[1:] if r[3] == title)))
        self.assertEqual((line["date"], line["paid_tickets"], line["seats"]), ("2031-03-14", "2", "2"))
        self.assertEqual((float(line["paid_uzs"]), float(line["refunded_uzs"]), float(line["net_uzs"])), (60000.0, 30000.0, 30000.0))

    def test_partial_refunds_leave_the_remainder_as_revenue(self):
        hall, screening = self.at(datetime(2031, 3, 14, 20, 0, tzinfo=TASHKENT))
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        shop.pay(booking["id"])
        sql("UPDATE screenings SET starts_at = now() + interval '5 hours', ends_at = now() + interval '7 hours' WHERE id = :i", i=screening)
        shop.set_status(booking["id"], "cancelled")                                         # 50% back
        place(screening, datetime(2031, 3, 14, 20, 0, tzinfo=TASHKENT))
        title = scalar("SELECT m.title FROM screenings s JOIN movies m ON m.id = s.movie_id WHERE s.id = :i", i=screening)
        rows = parse(self.get("revenue"))
        line = dict(zip(rows[0], next(r for r in rows[1:] if r[3] == title)))
        self.assertEqual((float(line["paid_uzs"]), float(line["refunded_uzs"]), float(line["net_uzs"])), (30000.0, 15000.0, 15000.0))

    def test_days_without_payments_produce_only_a_header(self):
        self.assertEqual(parse(self.get("revenue", date(2031, 8, 1), date(2031, 8, 2))), [REVENUE_COLUMNS])

if __name__ == "__main__":
    unittest.main()
