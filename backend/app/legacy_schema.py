"""The schema as it stood before Alembic, applied idempotently.

Phantora used to build its schema at every start-up: `create_all()` for the tables, then
additive SQL files. The Alembic baseline (revision 0001) runs the same thing, but with the
tables frozen into alembic/baseline_tables.sql and baseline_indexes.sql instead of read from the live models, so one
code path builds a brand-new database *and* upgrades a production database left by any
earlier release, and later model changes cannot leak into it. Nothing here may change:
add new schema changes as new Alembic revisions.
"""
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import Connection

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
BASELINE_TABLES = BACKEND_DIR / "alembic" / "baseline_tables.sql"
BASELINE_INDEXES = BACKEND_DIR / "alembic" / "baseline_indexes.sql"
STATEMENT_SEPARATOR = "-- ;;"

# 001_cinema_constraints.sql holds a PL/pgSQL block that must not be split on semicolons;
# its exclusion constraint is installed separately below.
LEGACY_SQL_FILES = (
    "002_persistent_product_data.sql", "003_email_verification_and_hall_type.sql",
    "004_booking_history_archive.sql", "005_demo_card_payments.sql", "006_catalog_screening_links.sql",
    "007_password_reset.sql", "008_cinematica_hall_directory.sql", "009_ticket_checkin.sql",
    "010_booking_notifications.sql", "011_screening_waitlist.sql", "012_movie_watchlists.sql",
    "013_cinematica_movie_identity.sql", "014_promotions_and_parda_pass.sql",
    "015_cinematica_response_cache.sql", "016_user_profile_avatar.sql", "017_rate_limit_buckets.sql",
    "018_token_version.sql",
)

def _run_script(conn: Connection, path: Path, separator: str) -> None:
    for statement in path.read_text(encoding="utf-8").split(separator):
        if statement.strip():
            conn.exec_driver_sql(statement)

def apply_legacy_schema(conn: Connection) -> None:
    # Order matters on a database from an older release: tables first (existing ones are left
    # alone), then the SQL files that add the columns they lack, and only then the indexes,
    # some of which cover those columns. This mirrors the old create_all() + SQL start-up.
    _run_script(conn, BASELINE_TABLES, STATEMENT_SEPARATOR)
    for name in LEGACY_SQL_FILES:
        _run_script(conn, MIGRATIONS_DIR / name, ";")
    _run_script(conn, BASELINE_INDEXES, STATEMENT_SEPARATOR)
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    conn.execute(text("""DO $$ BEGIN
      ALTER TABLE screenings ADD CONSTRAINT screenings_no_overlap
      EXCLUDE USING gist (auditorium_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
      WHERE (status = 'scheduled');
    EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL; END $$;"""))
