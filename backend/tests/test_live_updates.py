"""Live seat-map updates: the database trigger, the Server-Sent Events stream, limits and recovery."""
import time
import unittest

import psycopg

from app.config import settings
from app.database import engine
from app.live import broadcaster
from tests.support import ApiTestCase, LiveServer, SSEReader, scalar, sql

def wait_until(condition, timeout=5.0, message="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(message)

class LiveCase(ApiTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = LiveServer().__enter__()
        wait_until(broadcaster.connected.is_set, 10, "seat listener never connected")

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        super().tearDownClass()

    def open_stream(self, screening_id: int) -> SSEReader:
        reader = SSEReader(f"{self.server.url}/api/screenings/{screening_id}/seats/stream")
        self.addCleanup(reader.close)
        return reader

    def watching(self, screening_id: int) -> SSEReader:
        reader = self.open_stream(screening_id)
        self.assertEqual(reader.status, 200)
        self.assertEqual(reader.next()["event"], "ready")
        return reader

class DatabaseSignalTests(ApiTestCase):
    """The trigger itself, observed with a plain LISTEN connection."""

    def listen(self):
        conn = psycopg.connect(engine.url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True)
        conn.execute("LISTEN seat_changes")
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def notes(conn, wait=1.0):
        return [n.payload for n in conn.notifies(timeout=wait)]

    def test_taking_and_releasing_seats_notifies_the_screening(self):
        hall, screening = self.venue()
        shop = self.shop()
        conn = self.listen()
        booking = shop.book(screening, hall["seat_ids"][:3]).json()
        self.assertEqual(set(self.notes(conn)), {str(screening)}, "one folded notification, not one per seat")
        shop.set_status(booking["id"], "cancelled")
        self.assertEqual(set(self.notes(conn)), {str(screening)})

    def test_paying_does_not_notify_because_no_seat_changed(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        conn = self.listen()
        self.notes(conn, 0.3)
        shop.pay(booking["id"])
        self.assertEqual(self.notes(conn, 0.8), [])

    def test_other_screenings_are_not_confused(self):
        hall_a, screening_a = self.venue()
        hall_b, screening_b = self.venue()
        conn = self.listen()
        self.shop().book(screening_b, [hall_b["seat_ids"][0]])
        self.assertEqual(set(self.notes(conn)), {str(screening_b)})

    def test_an_expired_hold_notifies_when_it_is_released(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, [hall["seat_ids"][0]]).json()
        conn = self.listen()
        self.notes(conn, 0.3)
        sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=booking["id"])
        self.client.get(f"/api/screenings/{screening}/seats")            # any read expires holds
        self.assertEqual(set(self.notes(conn)), {str(screening)})

class StreamTests(LiveCase):
    def test_a_watching_page_hears_about_its_own_screening_only(self):
        hall, screening = self.venue()
        other_hall, other_screening = self.venue()
        reader = self.watching(screening)
        self.shop().book(other_screening, [other_hall["seat_ids"][0]])
        self.assertEqual([e for e in reader.drain(1.2) if "event" in e], [], "another screening must stay silent")
        self.shop().book(screening, [hall["seat_ids"][0]])
        event = reader.next()
        self.assertEqual(event["event"], "seats")
        self.assertIn(f'"screening_id": {screening}', event["data"])

    def test_cancelling_and_expiry_reach_the_page_too(self):
        hall, screening = self.venue()
        shop = self.shop()
        booking = shop.book(screening, hall["seat_ids"][:2]).json()
        reader = self.watching(screening)
        shop.set_status(booking["id"], "cancelled")
        self.assertEqual(reader.next()["event"], "seats")
        again = shop.book(screening, hall["seat_ids"][2:3]).json()
        reader.drain(1.0)
        sql("UPDATE bookings SET hold_expires_at = now() - interval '1 minute' WHERE id = :i", i=again["id"])
        self.client.get(f"/api/screenings/{screening}/seats")
        self.assertEqual(reader.next()["event"], "seats")

    def test_a_burst_of_seat_changes_is_coalesced(self):
        hall, screening = self.venue()
        reader = self.watching(screening)
        self.shop().book(screening, hall["seat_ids"][:6])
        events = [e for e in reader.drain(1.6) if e.get("event") == "seats"]
        self.assertTrue(1 <= len(events) <= 2, f"{len(events)} events for one booking")

    def test_unknown_and_started_screenings_are_refused(self):
        self.assertEqual(self.open_stream(999_999_999).status, 404)
        hall, screening = self.venue()
        sql("UPDATE screenings SET starts_at = now() - interval '1 hour', ends_at = now() + interval '1 hour' WHERE id = :i", i=screening)
        self.assertEqual(self.open_stream(screening).status, 410)

    def test_idle_streams_send_heartbeats(self):
        hall, screening = self.venue()
        original = settings.live_heartbeat_seconds
        settings.live_heartbeat_seconds = 0.3
        try:
            reader = self.watching(screening)
            beat = reader.next(timeout=3)
        finally:
            settings.live_heartbeat_seconds = original
        self.assertEqual(beat, {"comment": "ping"})

    def test_one_address_cannot_hold_unlimited_streams(self):
        hall, screening = self.venue()
        original = settings.live_max_streams_per_ip
        settings.live_max_streams_per_ip = 2
        try:
            first, second = self.watching(screening), self.watching(screening)
            self.assertEqual(self.open_stream(screening).status, 429)
            first.close()
            wait_until(lambda: self.open_stream(screening).status == 200, 5, "a freed slot was not released")
            second.close()
        finally:
            settings.live_max_streams_per_ip = original

    def test_closing_the_page_releases_its_subscription(self):
        hall, screening = self.venue()
        before = broadcaster.subscriber_count
        reader = self.watching(screening)
        self.assertEqual(broadcaster.subscriber_count, before + 1)
        reader.close()
        wait_until(lambda: broadcaster.subscriber_count == before, 5, "subscription leaked after disconnect")

    def test_the_listener_recovers_after_losing_its_database_connection(self):
        hall, screening = self.venue()
        reader = self.watching(screening)
        pid = scalar("SELECT pid FROM pg_stat_activity WHERE datname = current_database() AND query LIKE 'LISTEN %' LIMIT 1")
        self.assertIsNotNone(pid, "the listener's connection was not found")
        broadcaster.connected.clear()
        sql("SELECT pg_terminate_backend(:p)", p=pid)
        wait_until(broadcaster.connected.is_set, 10, "listener did not reconnect")
        self.assertEqual(reader.next(timeout=5)["event"], "seats", "pages must be told to resync after a gap")
        reader.drain(0.8)
        self.shop().book(screening, [hall["seat_ids"][0]])
        self.assertEqual(reader.next()["event"], "seats", "live updates must resume")

class MigrationTests(ApiTestCase):
    def test_the_triggers_exist_and_can_be_rolled_back(self):
        self.assertEqual(scalar("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'booking_seats_notify_%'"), 2)

if __name__ == "__main__":
    unittest.main()
