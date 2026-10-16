"""Clearing the notification list: delivered notices go, pending ones are hidden but still sent."""
import unittest
from unittest import mock

from app.notifications import deliver_due_notifications
from tests.support import NotificationTestCase, make_hall, make_screening, sql

class ClearNotificationsTests(NotificationTestCase):
    def customer_with_notices(self):
        """A paid ticket (confirmation queued, not yet sent) plus one delivered and one retrying notice."""
        hall = make_hall()
        shop = self.shop()
        booking = shop.book(make_screening(hall), [hall["seat_ids"][0]]).json()
        shop.pay(booking["id"])
        for event, sent, attempts in (("refund", "now()", 0), ("reminder_2h", "NULL", 2)):
            sql(f"INSERT INTO booking_notifications (booking_id, event_type, due_at, sent_at, attempts) "
                f"VALUES (:b, '{event}', now() - interval '1 minute', {sent}, :a)", b=booking["id"], a=attempts)
        return shop, booking

    def listing(self, shop):
        return self.client.get("/api/notifications", headers=shop.headers).json()

    def test_clearing_empties_the_list_even_when_some_notices_are_still_pending(self):
        shop, _ = self.customer_with_notices()
        self.assertEqual(len(self.listing(shop)), 3)
        response = self.client.delete("/api/notifications", headers=shop.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"cleared_count": 1, "hidden_count": 2})
        self.assertEqual(self.listing(shop), [])

    def test_a_cleared_pending_notice_is_still_delivered_and_stays_out_of_the_list(self):
        shop, booking = self.customer_with_notices()
        self.client.delete("/api/notifications", headers=shop.headers)
        sql("UPDATE booking_notifications SET due_at = now() - interval '1 minute' WHERE booking_id = :b AND event_type = 'confirmation'", b=booking["id"])
        with mock.patch("app.notifications.send_booking_confirmation_email") as sender:
            deliver_due_notifications()
        sender.assert_called_once()                       # clearing never cancels the confirmation e-mail
        self.assertEqual(self.listing(shop), [])
        again = self.client.delete("/api/notifications", headers=shop.headers).json()
        # the confirmation (now delivered) and the legacy reminder the worker retired are removed for good
        self.assertEqual((again["cleared_count"], again["hidden_count"]), (2, 0))

    def test_clearing_one_customers_list_leaves_everyone_elses_alone(self):
        mine, _ = self.customer_with_notices()
        theirs, _ = self.customer_with_notices()
        self.client.delete("/api/notifications", headers=mine.headers)
        self.assertEqual(len(self.listing(theirs)), 3)

    def test_clearing_an_empty_list_is_a_harmless_no_op(self):
        shop = self.shop()
        response = self.client.delete("/api/notifications", headers=shop.headers)
        self.assertEqual((response.status_code, response.json()), (200, {"cleared_count": 0, "hidden_count": 0}))

    def test_clearing_requires_a_signed_in_customer(self):
        self.assertIn(self.client.delete("/api/notifications").status_code, (401, 403))

if __name__ == "__main__":
    unittest.main()
