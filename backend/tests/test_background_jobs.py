"""Notification delivery and background jobs when several workers run at once."""
import io
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from unittest import mock

from fastapi.testclient import TestClient

from app import jobs, worker
from app.config import settings
from app.mail import EmailDeliveryError
from app.main import app
from app.notifications import deliver_due_notifications
from tests.support import ApiTestCase, make_hall, make_screening, scalar, sql

class Crash(BaseException):
    """Simulates the process dying mid-batch (not an Exception, so nothing may swallow it)."""

class NotificationTestCase(ApiTestCase):
    def setUp(self):
        sql("UPDATE booking_notifications SET sent_at = now() WHERE sent_at IS NULL")    # isolate from other tests
        patcher = mock.patch("app.api.deliver_due_notifications")                         # no post-payment delivery
        patcher.start()
        self.addCleanup(patcher.stop)

    def tickets(self, count: int) -> list[str]:
        """Confirmed bookings, each with one confirmation notice due now. Returns their ticket codes."""
        codes = []
        for _ in range(count):
            hall = make_hall()
            screening = make_screening(hall)
            shop = self.shop()
            booking = shop.book(screening, [hall["seat_ids"][0]]).json()
            codes.append(shop.pay(booking["id"]).json()["booking"]["ticket_code"])
        return codes

    def notice(self, ticket: str):
        return sql("SELECT n.sent_at IS NOT NULL, n.attempts, n.last_error FROM booking_notifications n "
                   "JOIN bookings b ON b.id = n.booking_id WHERE b.ticket_code = :t AND n.event_type = 'confirmation'",
                   t=ticket)[0]

    def make_due(self, ticket: str, minutes_ago: int = 1):
        sql("UPDATE booking_notifications SET due_at = now() - make_interval(mins => :m) "
            "WHERE event_type = 'confirmation' AND booking_id = (SELECT id FROM bookings WHERE ticket_code = :t)",
            m=minutes_ago, t=ticket)

class DeliveryTests(NotificationTestCase):
    def test_concurrent_workers_take_different_notices_instead_of_queueing(self):
        tickets = self.tickets(6)
        lock, inside, peak, met = threading.Lock(), [0], [0], threading.Event()
        def slow_sender(address, **kw):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
                if inside[0] >= 2:
                    met.set()
            met.wait(5)                  # hold the message until a second worker is also mid-send
            with lock:
                inside[0] -= 1
        with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=slow_sender):
            with ThreadPoolExecutor(3) as pool:
                delivered = sum(f.result(60) for f in [pool.submit(deliver_due_notifications) for _ in range(3)])
        self.assertGreaterEqual(peak[0], 2, "workers serialized behind each other's row locks")
        self.assertEqual(delivered, 6)
        self.assertTrue(all(self.notice(t)[0] for t in tickets))

    def test_each_notice_is_emailed_exactly_once_across_many_workers(self):
        tickets = self.tickets(12)
        sent: dict[str, int] = {}
        lock = threading.Lock()
        def fake(address, **kw):
            time.sleep(0.02)
            with lock:
                sent[kw["ticket_code"]] = sent.get(kw["ticket_code"], 0) + 1
        with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=fake):
            with ThreadPoolExecutor(5) as pool:
                total = sum(f.result(60) for f in [pool.submit(deliver_due_notifications) for _ in range(5)])
        self.assertEqual({t: sent.get(t) for t in tickets}, {t: 1 for t in tickets})
        self.assertEqual(total, 12)

    def test_a_crash_mid_batch_keeps_the_messages_already_recorded_as_sent(self):
        tickets = self.tickets(4)
        for offset, ticket in enumerate(tickets):                      # fixed order: oldest due first
            self.make_due(ticket, minutes_ago=10 - offset)
        calls = []
        def dies_on_third(address, **kw):
            calls.append(kw["ticket_code"])
            if len(calls) == 3:
                raise Crash()
        with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=dies_on_third):
            with self.assertRaises(Crash):
                deliver_due_notifications()
        self.assertEqual([self.notice(t)[0] for t in tickets], [True, True, False, False])

    def test_one_unexpected_error_does_not_stop_or_lose_the_others(self):
        tickets = self.tickets(4)
        for offset, ticket in enumerate(tickets):
            self.make_due(ticket, minutes_ago=10 - offset)
        def explode_on_second(address, **kw):
            if kw["ticket_code"] == tickets[1]:
                raise RuntimeError("template bug")
        with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=explode_on_second):
            delivered = deliver_due_notifications()
        self.assertEqual(delivered, 3)
        sent, attempts, error = self.notice(tickets[1])
        self.assertFalse(sent)
        self.assertEqual(attempts, 1)
        self.assertIn("template bug", error)
        self.assertTrue(all(self.notice(t)[0] for t in (tickets[0], tickets[2], tickets[3])))

class RetryTests(NotificationTestCase):
    def test_permanently_failing_notice_is_abandoned_after_the_cap(self):
        (ticket,) = self.tickets(1)
        calls = []
        def failing(address, **kw):
            calls.append(1)
            raise EmailDeliveryError("mailbox does not exist")
        original = settings.notification_max_attempts
        settings.notification_max_attempts = 3
        try:
            with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=failing):
                for _ in range(6):
                    self.make_due(ticket)
                    deliver_due_notifications()
        finally:
            settings.notification_max_attempts = original
        sent, attempts, error = self.notice(ticket)
        self.assertEqual(len(calls), 3)                                # tried three times, then left alone
        self.assertTrue(sent)
        self.assertEqual(attempts, 3)
        self.assertTrue(error.startswith("Gave up after 3 attempts"), error)

    def test_a_transient_failure_is_retried_later_and_then_delivered(self):
        (ticket,) = self.tickets(1)
        with mock.patch("app.notifications.send_booking_confirmation_email", side_effect=EmailDeliveryError("timeout")):
            self.assertEqual(deliver_due_notifications(), 0)
        sent, attempts, _ = self.notice(ticket)
        self.assertFalse(sent)
        self.assertEqual(attempts, 1)
        self.assertEqual(deliver_due_notifications(), 0)               # not due again yet (retry delay)
        self.make_due(ticket)
        with mock.patch("app.notifications.send_booking_confirmation_email"):
            self.assertEqual(deliver_due_notifications(), 1)
        self.assertTrue(self.notice(ticket)[0])

class JobLockTests(NotificationTestCase):
    def test_a_lock_can_be_held_by_only_one_caller_at_a_time(self):
        with jobs.exclusive(990001) as first:
            with jobs.exclusive(990001) as second:
                with jobs.exclusive(990002) as other_key:
                    self.assertEqual((first, second, other_key), (True, False, True))
        with jobs.exclusive(990001) as again:
            self.assertTrue(again)                                      # released when the holder finished

    def test_cycle_is_skipped_while_another_process_runs_it(self):
        with jobs.exclusive(jobs.LOCK_NOTIFICATIONS) as held:
            self.assertTrue(held)
            self.assertIsNone(jobs.notification_cycle())
        self.assertIsInstance(jobs.notification_cycle(), dict)

    def test_cycle_delivers_what_is_due(self):
        (ticket,) = self.tickets(1)
        with mock.patch("app.notifications.send_booking_confirmation_email") as sender:
            result = jobs.notification_cycle()
        self.assertEqual(result["bookings"], 1)
        sender.assert_called_once()
        self.assertTrue(self.notice(ticket)[0])

class WorkerTests(NotificationTestCase):
    def test_worker_once_runs_each_job_and_exits(self):
        (ticket,) = self.tickets(1)
        out = io.StringIO()
        with mock.patch("app.notifications.send_booking_confirmation_email"), \
                mock.patch("app.jobs.sync_active_cinematica_halls", return_value={"synced": 0}), \
                redirect_stdout(out):
            self.assertEqual(worker.main(["--once"]), 0)
        self.assertIn("'bookings': 1", out.getvalue())
        self.assertTrue(self.notice(ticket)[0])

    def test_worker_once_runs_the_other_jobs_and_fails_the_exit_code_when_one_breaks(self):
        (ticket,) = self.tickets(1)
        out = io.StringIO()
        with mock.patch("app.notifications.send_booking_confirmation_email"),                 mock.patch("app.jobs.sync_active_cinematica_halls", side_effect=RuntimeError("upstream down")),                 redirect_stdout(out):
            self.assertEqual(worker.main(["--once"]), 1)
        self.assertIn("upstream down", out.getvalue())
        self.assertTrue(self.notice(ticket)[0], "the notification job must still have run")

    def test_web_process_runs_the_loops_only_when_enabled(self):
        for enabled, expected_calls in ((True, 1), (False, 0)):
            settings.run_background_jobs = enabled
            try:
                with mock.patch("app.jobs.start_all", return_value=[]) as start:
                    with TestClient(app):
                        pass
            finally:
                settings.run_background_jobs = False
            self.assertEqual(start.call_count, expected_calls, f"run_background_jobs={enabled}")

    def test_schedule_backfill_does_not_duplicate_reminders(self):
        self.tickets(1)
        before = scalar("SELECT count(*) FROM booking_notifications")
        jobs.schedule_missing_reminders()
        jobs.schedule_missing_reminders()
        self.assertEqual(scalar("SELECT count(*) FROM booking_notifications"), before)

if __name__ == "__main__":
    unittest.main()
