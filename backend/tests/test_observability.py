"""Request ids, security headers, structured logs, health checks and the client-address diagnostics."""
import json
import logging
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from app import observability
from app.config import settings
from app.main import app
from app.models import Role
from app.observability import JsonFormatter, configure_logging, request_id_var
from app.ratelimit import client_ip
from tests.support import ApiTestCase, auth, make_user

class RequestIdTests(ApiTestCase):
    def test_a_request_id_is_generated_and_returned(self):
        resp = self.client.get("/health/live")
        self.assertRegex(resp.headers["X-Request-ID"], r"^[0-9a-f]{32}$")
        self.assertNotEqual(resp.headers["X-Request-ID"], self.client.get("/health/live").headers["X-Request-ID"])

    def test_a_valid_incoming_id_is_kept_so_a_trace_spans_services(self):
        resp = self.client.get("/health/live", headers={"X-Request-ID": "front-end.trace_123"})
        self.assertEqual(resp.headers["X-Request-ID"], "front-end.trace_123")

    def test_malformed_ids_are_replaced_not_echoed(self):
        for bad in ("short", "x" * 200, "has space in it", "inject\tvalue123", "<script>alert(1)</script>"):
            with self.subTest(bad=bad[:20]):
                try:
                    resp = self.client.get("/health/live", headers={"X-Request-ID": bad})
                except Exception:           # the HTTP client itself may refuse some header values
                    continue
                self.assertNotEqual(resp.headers["X-Request-ID"], bad)
                self.assertRegex(resp.headers["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_errors_and_missing_routes_carry_the_id_too(self):
        for resp in (self.client.get("/api/nope"), self.client.post("/api/auth/login", json={})):
            self.assertIn("X-Request-ID", resp.headers)

    def test_the_access_log_line_carries_the_same_id(self):
        with self.assertLogs("parda.access", level="INFO") as captured:
            resp = self.client.get("/api/movies")
        record = captured.records[-1]
        self.assertEqual(record.request_id, resp.headers["X-Request-ID"])
        self.assertEqual((record.method, record.path, record.status), ("GET", "/api/movies", resp.status_code))
        self.assertGreaterEqual(record.duration_ms, 0)

    def test_health_probes_do_not_flood_the_info_log(self):
        with self.assertNoLogs("parda.access", level="INFO"):
            self.client.get("/health/live")
            self.client.get("/health")

    def test_an_unexpected_error_returns_a_safe_500_with_the_id(self):
        def boom():
            raise RuntimeError("secret internal detail")
        app.add_api_route("/__boom", boom)
        try:
            with self.assertLogs("parda.access", level="ERROR") as captured:
                resp = self.client.get("/__boom")
        finally:
            app.router.routes.pop()
        self.assertEqual(resp.status_code, 500)
        body = resp.json()
        self.assertEqual(body["detail"], "Internal server error")
        self.assertEqual(body["request_id"], resp.headers["X-Request-ID"])
        self.assertNotIn("secret", resp.text)
        self.assertTrue(any("secret internal detail" in (r.exc_text or "") or r.exc_info for r in captured.records))

class SecurityHeaderTests(ApiTestCase):
    def test_every_response_has_the_hardening_headers(self):
        for resp in (self.client.get("/health/live"), self.client.get("/api/nope")):
            self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
            self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
            self.assertIn("geolocation=()", resp.headers["Permissions-Policy"])

    def test_authenticated_responses_are_never_cached(self):
        token = make_user()["token"]
        self.assertEqual(self.client.get("/api/auth/me", headers=auth(token)).headers["Cache-Control"], "no-store")
        self.assertNotIn("no-store", self.client.get("/health/live").headers.get("Cache-Control", ""))

    def test_hsts_only_in_production(self):
        self.assertNotIn("Strict-Transport-Security", self.client.get("/health/live").headers)
        settings.app_environment = "production"
        try:
            self.assertIn("max-age=31536000", self.client.get("/health/live").headers["Strict-Transport-Security"])
        finally:
            settings.app_environment = "development"

    def test_the_browser_can_read_the_request_id_across_origins(self):
        origin = settings.cors_origins.split(",")[0]
        resp = self.client.get("/health/live", headers={"Origin": origin})
        self.assertIn("X-Request-ID", resp.headers["Access-Control-Expose-Headers"])

class HealthTests(ApiTestCase):
    def test_health_reports_a_reachable_database(self):
        resp = self.client.get("/health")
        self.assertEqual((resp.status_code, resp.json()), (200, {"status": "ok", "database": "ok"}))

    def test_health_fails_fast_without_leaking_when_the_database_is_down(self):
        with mock.patch("app.main.health_engine.connect", side_effect=RuntimeError("password=hunter2 host=db.internal")):
            resp = self.client.get("/health")
            live = self.client.get("/health/live")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json(), {"status": "unavailable", "database": "unreachable"})
        self.assertNotIn("hunter2", resp.text)
        self.assertEqual(live.status_code, 200, "liveness must not depend on the database")

    def test_a_database_that_stops_answering_cannot_hang_the_health_check(self):
        def never_answers():
            time.sleep(1.5)
        started = time.monotonic()
        with mock.patch("app.main.HEALTH_TIMEOUT_SECONDS", 0.3), mock.patch("app.main._ping_database", side_effect=never_answers):
            resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 503)
        self.assertLess(time.monotonic() - started, 1.2, "the answer must not wait for the stuck ping")

class ClientAddressTests(ApiTestCase):
    def test_only_admins_can_see_the_diagnostics(self):
        self.assertEqual(self.client.get("/api/admin/diagnostics/client-ip", headers=auth(make_user()["token"])).status_code, 403)
        self.assertIn(self.client.get("/api/admin/diagnostics/client-ip").status_code, (401, 403))

    def test_diagnostics_show_the_forwarded_headers_and_the_resolved_address(self):
        admin = make_user(role=Role.ADMIN)["token"]
        settings.client_ip_header = "x-forwarded-for"
        try:
            resp = self.client.get("/api/admin/diagnostics/client-ip", headers={
                **auth(admin), "X-Forwarded-For": "203.0.113.7, 76.76.21.9", "X-Real-IP": "203.0.113.7"})
        finally:
            settings.client_ip_header = ""
        body = resp.json()
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(body["resolved_ip"], "203.0.113.7")            # first entry = the customer, not the proxy
        self.assertEqual(body["configured_header"], "x-forwarded-for")
        self.assertEqual(body["headers"]["x-forwarded-for"], "203.0.113.7, 76.76.21.9")
        self.assertIsNone(body["headers"]["cf-connecting-ip"])

    def test_forwarded_for_uses_the_first_valid_entry(self):
        settings.client_ip_header = "x-forwarded-for"
        try:
            request = lambda value: SimpleNamespace(headers={"x-forwarded-for": value}, client=SimpleNamespace(host="10.9.9.9"))  # noqa: E731
            self.assertEqual(client_ip(request("198.51.100.4, 70.41.3.18")), "198.51.100.4")
            self.assertEqual(client_ip(request("2001:db8::1, 70.41.3.18")), "2001:db8::1")
            self.assertEqual(client_ip(request("not-an-ip, 70.41.3.18")), "10.9.9.9")   # garbage falls back to the socket
        finally:
            settings.client_ip_header = ""

class LoggingTests(unittest.TestCase):
    def test_json_lines_are_valid_and_carry_context(self):
        token = request_id_var.set("req-abcdef123")
        try:
            record = logging.getLogger("t").makeRecord("t", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
            record.request_id = request_id_var.get()
            record.status = 429
            line = JsonFormatter().format(record)
        finally:
            request_id_var.reset(token)
        entry = json.loads(line)
        self.assertEqual((entry["level"], entry["message"], entry["request_id"], entry["status"]),
                         ("WARNING", "hello world", "req-abcdef123", 429))

    def test_exceptions_are_included_in_json_lines(self):
        try:
            raise ValueError("bad thing")
        except ValueError:
            import sys
            record = logging.getLogger("t").makeRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
        self.assertIn("ValueError: bad thing", json.loads(JsonFormatter().format(record))["exception"])

    def test_configure_logging_is_idempotent_and_uses_the_right_format(self):
        root = logging.getLogger()
        original = (settings.log_format, list(root.handlers))
        try:
            configure_logging()
            configure_logging()
            ours = [h for h in root.handlers if getattr(h, "_parda", False)]
            self.assertEqual(len(ours), 1)
            self.assertNotIsInstance(ours[0].formatter, JsonFormatter)          # development defaults to readable text
            settings.log_format = "json"
            configure_logging()
            self.assertIsInstance(ours[0].formatter, JsonFormatter)
        finally:
            settings.log_format = original[0]
            configure_logging()

    def test_records_get_the_request_id_from_any_logger(self):
        token = request_id_var.set("req-from-context")
        try:
            record = logging.getLogger("some.library").makeRecord("some.library", logging.INFO, __file__, 1, "x", (), None)
            self.assertEqual(observability._record_factory("n", logging.INFO, __file__, 1, "x", (), None).request_id, "req-from-context")
            self.assertIsNotNone(record)
        finally:
            request_id_var.reset(token)

if __name__ == "__main__":
    unittest.main()
