"""Fast unit coverage for public Cinematica payload normalization.

Database concurrency protection is implemented through PostgreSQL locks and
constraints; these pure tests keep the provider-contract edge cases quick to
check without hitting an upstream service.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cinematica import _show_out, _showtime_starts_at


def sample(**overrides):
    item = {
        "id": 10091963, "date": "02.10.26", "time": "20:00", "cinema": "Tashkent City",
        "cinema_id": 1, "hall": "Зал PEPSI IMAX", "hall_id": 10000014,
        "price": "70000.0", "is_disabled": False, "disable_sales": False,
    }
    item.update(overrides)
    return item


class CinematicaNormalizationTests(unittest.TestCase):
    def test_valid_showtime_keeps_stable_source_ids(self):
        show = _show_out(sample())
        self.assertEqual(show["id"], 10091963)
        self.assertEqual(show["cinema_id"], 1)
        self.assertEqual(show["hall_id"], 10000014)
        self.assertEqual(show["format_type"], "IMAX")

    def test_disabled_or_missing_hall_showtime_is_not_exposed(self):
        self.assertIsNone(_show_out(sample(disable_sales=True)))
        self.assertIsNone(_show_out(sample(hall_id=None)))
        self.assertIsNone(_show_out(sample(cinema="")))

    def test_tashkent_showtime_is_converted_to_utc(self):
        starts_at = _showtime_starts_at(_show_out(sample()))
        self.assertEqual(starts_at, datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc))

