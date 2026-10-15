"""Factories and helpers shared by the database-backed tests."""
import itertools
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from sqlalchemy import text

from app.database import SessionLocal, engine
from app.main import app
from app.models import Auditorium, Movie, Promotion, Role, Screening, Seat, User
from app.security import hash_password, make_token

_counter = itertools.count(1)

def db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

def make_user(*, points: int = 0, role: Role = Role.CUSTOMER) -> dict:
    tag = f"{next(_counter)}{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        user = User(email=f"bk-{tag}@example.com", name=f"bk{tag}"[:30], nickname=f"bk{tag}"[:30], role=role,
                    password_hash=hash_password("correct-horse-battery"), active=True, email_verified=True,
                    parda_points=points)
        db.add(user)
        db.commit()
        return {"id": user.id, "email": user.email, "token": make_token(user)}

def make_hall(*, rows: int = 3, cols: int = 6, premium_rows: int = 1) -> dict:
    """A hall whose first `premium_rows` rows are premium. Seat ids are ordered by row, then number."""
    with SessionLocal() as db:
        hall = Auditorium(name=f"Test hall {uuid.uuid4().hex[:6]}", cinema_name="Test cinema")
        hall.seats = [Seat(row_label=chr(65 + r), seat_number=n, seat_type="premium" if r < premium_rows else "standard")
                      for r in range(rows) for n in range(1, cols + 1)]
        db.add(hall)
        db.commit()
        seats = sorted(hall.seats, key=lambda s: (s.row_label, s.seat_number))
        return {"id": hall.id, "seat_ids": [s.id for s in seats],
                "premium": [s.id for s in seats if s.seat_type == "premium"],
                "standard": [s.id for s in seats if s.seat_type != "premium"]}

def make_screening(hall: dict, *, starts_in: timedelta = timedelta(hours=5), minutes: int = 120,
                   base_price: int = 30000, surcharge: int = 10000) -> int:
    with SessionLocal() as db:
        movie = Movie(title=f"Test film {uuid.uuid4().hex[:6]}", duration_minutes=minutes)
        db.add(movie)
        db.flush()
        start = datetime.now(timezone.utc) + starts_in
        screening = Screening(movie_id=movie.id, auditorium_id=hall["id"], starts_at=start,
                              ends_at=start + timedelta(minutes=minutes), base_price=Decimal(base_price),
                              premium_surcharge=Decimal(surcharge))
        db.add(screening)
        db.commit()
        return screening.id

def make_promo(*, percent: int = 10, usage_limit: int | None = None, min_order: int = 0,
               max_discount: int | None = None, active: bool = True,
               starts_in: timedelta | None = None, ends_in: timedelta | None = None) -> str:
    code = f"T{uuid.uuid4().hex[:8]}".upper()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(Promotion(code=code, label="Test promo", percent_off=percent, usage_limit=usage_limit,
                         min_order_amount=Decimal(min_order), active=active,
                         max_discount_amount=None if max_discount is None else Decimal(max_discount),
                         starts_at=None if starts_in is None else now + starts_in,
                         ends_at=None if ends_in is None else now + ends_in))
        db.commit()
    return code

def sql(statement: str, **params):
    """Run one statement in its own transaction; returns all rows for a SELECT."""
    with engine.begin() as conn:
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None

def scalar(statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()

def run_parallel(calls):
    """Run callables on separate threads released together by a barrier; results keep call order."""
    barrier = threading.Barrier(len(calls))
    def wrap(fn):
        barrier.wait(timeout=15)
        return fn()
    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(wrap, calls))

@contextmanager
def captured_payment_codes():
    """Collect the 4-digit codes the API would e-mail during checkout (mock mode never returns them)."""
    codes: list[str] = []
    def fake(address, code, **kwargs):
        codes.append(code)
        return True
    with mock.patch("app.api.send_payment_verification_email", side_effect=fake):
        yield codes

class Shop:
    """Thin wrapper over the HTTP API for one customer."""
    def __init__(self, client, user: dict):
        self.client, self.user, self.headers = client, user, auth(user["token"])

    def book(self, screening_id: int, seat_ids: list[int]):
        return self.client.post("/api/bookings", headers=self.headers,
                                json={"screening_id": screening_id, "seat_ids": seat_ids})

    def price(self, booking_id: int, promo_code: str | None = None, points: int = 0):
        return self.client.post(f"/api/bookings/{booking_id}/pricing", headers=self.headers,
                                json={"promo_code": promo_code, "points_to_redeem": points})

    def start_payment(self, booking_id: int, method: str = "uzcard"):
        """Returns (response, code) where code is the e-mailed 4-digit code (or None)."""
        with captured_payment_codes() as codes:
            resp = self.client.post("/api/payments/create", headers=self.headers, json={
                "method": method, "booking_id": booking_id, "card_number": "8600123412341234",
                "cardholder_name": "Test Customer", "expiry_date": "12 / 40", "cvv": None})
        return resp, (codes[-1] if codes else None)

    def verify(self, payment_id: int, code: str):
        return self.client.post(f"/api/payments/{payment_id}/verify", headers=self.headers, json={"code": code})

    def pay(self, booking_id: int):
        """Full demo checkout. Returns the verify response."""
        started, code = self.start_payment(booking_id)
        assert started.status_code == 201, started.text
        return self.verify(started.json()["payment_id"], code)

    def set_status(self, booking_id: int, status: str):
        return self.client.patch(f"/api/bookings/{booking_id}/status", headers=self.headers, json={"status": status})

    def points(self) -> tuple[int, int]:
        row = sql("SELECT parda_points, reserved_points FROM users WHERE id = :i", i=self.user["id"])[0]
        return row[0], row[1]


@unittest.skipUnless(db_available(), "PostgreSQL not reachable")
class ApiTestCase(unittest.TestCase):
    """Starts the real app (lifespan, migrations, constraints) once per test class."""
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def shop(self, **user_kwargs) -> Shop:
        return Shop(self.client, make_user(**user_kwargs))

    def venue(self, **screening_kwargs) -> tuple[dict, int]:
        hall = make_hall()
        return hall, make_screening(hall, **screening_kwargs)
