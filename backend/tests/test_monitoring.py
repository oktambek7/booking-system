"""Optional Sentry reporting and the configurable database pool."""
import unittest
from unittest import mock

from app import database, monitoring
from app.config import settings
from tests.test_config import make

def event() -> dict:
    return {
        "message": "boom",
        "user": {"email": "someone@example.com", "id": "5"},
        "request": {
            "url": "https://parda.example/api/bookings?token=secret&email=a@b.c",
            "query_string": "token=secret&email=a@b.c",
            "cookies": {"parda_refresh": "abc"},
            "data": {"password": "hunter2hunter2"},
            "headers": {"Authorization": "Bearer xyz", "Cookie": "parda_refresh=abc", "X-Forwarded-For": "1.2.3.4",
                        "X-Parda-Signature": "sha256=zzz", "User-Agent": "Mozilla/5.0", "Accept": "*/*"},
        },
    }

class ScrubTests(unittest.TestCase):
    def test_nothing_personal_or_secret_survives(self):
        cleaned = monitoring.scrub_event(event())
        self.assertNotIn("user", cleaned)
        request = cleaned["request"]
        for gone in ("cookies", "data", "query_string"):
            self.assertNotIn(gone, request)
        self.assertEqual(request["url"], "https://parda.example/api/bookings")
        self.assertEqual({k.lower() for k in request["headers"]}, {"user-agent", "accept"})
        flat = repr(cleaned)
        for secret in ("hunter2hunter2", "Bearer xyz", "parda_refresh", "someone@example.com", "1.2.3.4", "token=secret"):
            self.assertNotIn(secret, flat)

    def test_harmless_content_is_kept(self):
        self.assertEqual(monitoring.scrub_event(event())["message"], "boom")

    def test_odd_shaped_events_do_not_break_it(self):
        for odd in ({}, {"request": None}, {"request": {"headers": None}}, {"request": {"url": 5}}, {"request": "text"}):
            monitoring.scrub_event(dict(odd))

class InitTests(unittest.TestCase):
    def test_it_is_off_without_a_dsn(self):
        with mock.patch.object(settings, "sentry_dsn", ""), mock.patch("sentry_sdk.init") as init:
            self.assertFalse(monitoring.init_sentry())
        init.assert_not_called()

    def test_it_starts_without_personal_data_and_with_the_scrubber(self):
        with mock.patch.object(settings, "sentry_dsn", "https://key@o1.ingest.sentry.io/1"), mock.patch("sentry_sdk.init") as init:
            self.assertTrue(monitoring.init_sentry())
        kwargs = init.call_args.kwargs
        self.assertIs(kwargs["send_default_pii"], False)
        self.assertIs(kwargs["before_send"], monitoring.scrub_event)
        self.assertEqual(kwargs["max_request_body_size"], "never")

    def test_a_failure_to_start_never_stops_the_api(self):
        with mock.patch.object(settings, "sentry_dsn", "https://key@o1.ingest.sentry.io/1"), mock.patch("sentry_sdk.init", side_effect=ValueError("bad dsn")):
            self.assertFalse(monitoring.init_sentry())

    def test_production_refuses_a_non_https_dsn(self):
        self.assertTrue(any("SENTRY_DSN" in p for p in make(sentry_dsn="http://key@host/1").production_problems()))
        self.assertEqual(make(sentry_dsn="https://key@o1.ingest.sentry.io/1").production_problems(), [])

class PoolTests(unittest.TestCase):
    def test_pool_settings_come_from_configuration(self):
        with mock.patch.multiple(settings, db_pool_size=3, db_max_overflow=1, db_pool_timeout_seconds=7, db_pool_recycle_seconds=99):
            options = database.engine_options()
        self.assertEqual((options["pool_size"], options["max_overflow"], options["pool_timeout"], options["pool_recycle"]), (3, 1, 7, 99))
        self.assertTrue(options["pool_pre_ping"])

    def test_the_statement_timeout_is_only_set_when_asked_for(self):
        with mock.patch.object(settings, "db_statement_timeout_ms", 0):
            self.assertNotIn("options", database.engine_options()["connect_args"])
        with mock.patch.object(settings, "db_statement_timeout_ms", 15000):
            self.assertEqual(database.engine_options()["connect_args"]["options"], "-c statement_timeout=15000")

    def test_the_running_engine_uses_the_configured_pool(self):
        self.assertEqual(database.engine.pool.size(), settings.db_pool_size)

    def test_a_nonsensical_pool_is_refused_in_production(self):
        self.assertTrue(any("DB_POOL_SIZE" in p for p in make(db_pool_size=0).production_problems()))
        self.assertTrue(any("DB_POOL_SIZE" in p for p in make(db_max_overflow=-1).production_problems()))
