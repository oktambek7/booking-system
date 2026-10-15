"""Alembic: fresh installs, upgrades of pre-Alembic databases, drift, and concurrent start-up.

Each test migrates its own throwaway database on the same server as the suite's database."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import migrate
from app.database import Base
from tests.support import db_available

@contextmanager
def scratch_engine():
    base = make_url(os.environ["DATABASE_URL"])
    name = f"parda_mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()

def scalar(engine, statement, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()

@unittest.skipUnless(db_available(), "PostgreSQL not reachable")
class MigrationTests(unittest.TestCase):
    def test_fresh_database_reaches_head_and_is_stable(self):
        with scratch_engine() as engine:
            self.assertIsNone(migrate.current_revision(engine))
            migrate.upgrade_to_head(engine)
            self.assertEqual(migrate.current_revision(engine), migrate.head_revision())
            self.assertTrue(migrate.is_current(engine))
            migrate.upgrade_to_head(engine)                                  # running again changes nothing
            self.assertEqual(scalar(engine, "SELECT count(*) FROM alembic_version"), 1)

    def test_fresh_database_has_the_database_level_safeguards(self):
        with scratch_engine() as engine:
            migrate.upgrade_to_head(engine)
            self.assertEqual(scalar(engine, "SELECT count(*) FROM pg_constraint WHERE conname = 'screenings_no_overlap'"), 1)
            self.assertIsNotNone(scalar(engine, "SELECT to_regclass('public.rate_limit_buckets')"))
            self.assertEqual(scalar(engine, "SELECT count(*) FROM information_schema.columns "
                                            "WHERE table_name = 'users' AND column_name = 'token_version'"), 1)

    def test_database_built_before_alembic_is_upgraded_without_losing_data(self):
        with scratch_engine() as engine:
            migrate.upgrade_to_head(engine)
            # Put it back into the state an earlier release left it in: the baseline schema (every later
            # revision rolled back by its own downgrade), no Alembic bookkeeping table, and none of the
            # objects the baseline itself replaced since (the rate-limit table and token column).
            config = migrate.alembic_config()
            with engine.connect() as conn:
                config.attributes["connection"] = conn
                command.downgrade(config, "0001")
                conn.commit()
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO users (email, name, nickname, password_hash, role, active, email_verified, "
                                  "phone_verified, parda_points, reserved_points) VALUES ('old@example.com', 'old', 'old', 'x', "
                                  "'CUSTOMER', true, true, false, 120, 0)"))
                conn.execute(text("DROP TABLE alembic_version"))
                conn.execute(text("DROP TABLE rate_limit_buckets"))
                conn.execute(text("ALTER TABLE users DROP COLUMN token_version"))
            self.assertFalse(migrate.is_current(engine))
            migrate.upgrade_to_head(engine)
            self.assertTrue(migrate.is_current(engine))
            self.assertEqual(scalar(engine, "SELECT parda_points FROM users WHERE email = 'old@example.com'"), 120)
            self.assertEqual(scalar(engine, "SELECT token_version FROM users WHERE email = 'old@example.com'"), 0)
            self.assertIsNotNone(scalar(engine, "SELECT to_regclass('public.rate_limit_buckets')"))
            self.assertIsNotNone(scalar(engine, "SELECT to_regclass('public.audit_log')"))
            self.assertIsNotNone(scalar(engine, "SELECT to_regclass('public.refresh_tokens')"))

    def test_every_revision_can_be_rolled_back_and_applied_again(self):
        with scratch_engine() as engine:
            migrate.upgrade_to_head(engine)
            config = migrate.alembic_config()

            def downgrade(target):
                with engine.connect() as conn:
                    config.attributes["connection"] = conn
                    command.downgrade(config, target)
                    conn.commit()

            downgrade("0002")
            self.assertEqual(migrate.current_revision(engine), "0002")
            self.assertIsNone(scalar(engine, "SELECT to_regclass('public.refresh_tokens')"))
            self.assertIsNotNone(scalar(engine, "SELECT to_regclass('public.audit_log')"))
            downgrade("0001")
            self.assertEqual(migrate.current_revision(engine), "0001")
            self.assertIsNone(scalar(engine, "SELECT to_regclass('public.audit_log')"))
            self.assertEqual(scalar(engine, "SELECT count(*) FROM pg_proc WHERE proname = 'audit_log_guard'"), 0)
            migrate.upgrade_to_head(engine)
            self.assertTrue(migrate.is_current(engine))
            self.assertIsNotNone(scalar(engine, "SELECT to_regclass('public.refresh_tokens')"))
            self.assertEqual(scalar(engine, "SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_log_guard'"), 1)

    def test_models_and_migrations_have_not_drifted(self):
        """Adding a model or column without a migration must fail here, not in production."""
        with scratch_engine() as engine:
            migrate.upgrade_to_head(engine)
            with engine.connect() as conn:
                diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        def flatten(items):
            for item in items:
                if isinstance(item, list):
                    yield from flatten(item)
                else:
                    yield item
        missing = [d for d in flatten(diffs) if d[0] in ("add_table", "add_column")]
        self.assertEqual(missing, [], "models define schema that no migration creates")

    def test_schema_check_detects_an_unmigrated_database(self):
        with scratch_engine() as engine:
            with self.assertRaises(RuntimeError):
                migrate.assert_schema_current(engine)
            migrate.upgrade_to_head(engine)
            migrate.assert_schema_current(engine)

    def test_instances_starting_together_do_not_collide(self):
        with scratch_engine() as engine:
            with ThreadPoolExecutor(4) as pool:
                futures = [pool.submit(migrate.upgrade_to_head, engine) for _ in range(4)]
                for future in futures:
                    future.result(60)                                        # re-raises any failure
            self.assertTrue(migrate.is_current(engine))
            self.assertEqual(scalar(engine, "SELECT count(*) FROM alembic_version"), 1)

if __name__ == "__main__":
    unittest.main()
