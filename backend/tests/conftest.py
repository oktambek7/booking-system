"""Run the suite against a throwaway PostgreSQL database.

The tests create halls, bookings and users, so they must never touch a real
database. Before the app is imported, create `parda_test_<random>` on the server
named by DATABASE_URL and point the app at it; drop it again afterwards. If the
server is unreachable (or the role cannot create databases) the database-backed
tests skip themselves, exactly as before.
"""
import os
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DEFAULT_URL = "postgresql+psycopg://booking:booking@localhost:5432/booking"
_created: dict = {}

def _normalise(url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url

def pytest_configure(config):
    os.environ["RUN_BACKGROUND_JOBS"] = "false"      # no network refreshes or e-mail loops in tests
    os.environ.pop("CLIENT_IP_HEADER", None)
    base = make_url(_normalise(os.environ.get("DATABASE_URL") or DEFAULT_URL))
    name = f"parda_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception:
        admin.dispose()
        os.environ["DATABASE_URL"] = base.render_as_string(hide_password=False)
        return
    _created.update(admin=admin, name=name)
    os.environ["DATABASE_URL"] = base.set(database=name).render_as_string(hide_password=False)

def pytest_unconfigure(config):
    if not _created:
        return
    if "app.database" in sys.modules:
        sys.modules["app.database"].engine.dispose()
    try:
        with _created["admin"].connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_created["name"]}" WITH (FORCE)'))
    finally:
        _created["admin"].dispose()
