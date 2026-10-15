"""Run or check Alembic migrations.

    python -m app.migrate            # upgrade to the latest revision (default)
    python -m app.migrate current    # print the database's revision
    python -m app.migrate check      # exit 1 unless the database is at the latest revision

Upgrades take a PostgreSQL advisory lock, so several API instances starting together
cannot run the same migration at once; the others wait, then find nothing left to do.
"""
import sys
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .database import engine as default_engine

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOCK_KEY = 0x70617264   # "pard"

def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config

def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()

def current_revision(engine: Engine | None = None) -> str | None:
    with (engine or default_engine).connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()

def is_current(engine: Engine | None = None) -> bool:
    return current_revision(engine) == head_revision()

def assert_schema_current(engine: Engine | None = None) -> None:
    if not is_current(engine):
        raise RuntimeError("The database schema is not at the latest revision. "
                           "Run `python -m app.migrate` (or start the API with AUTO_MIGRATE=true) first.")

def upgrade_to_head(engine: Engine | None = None) -> None:
    config = alembic_config()
    with (engine or default_engine).connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
        conn.commit()
        try:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            conn.commit()
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            conn.commit()

def main(argv: list[str]) -> int:
    action = argv[0] if argv else "upgrade"
    if action == "upgrade":
        upgrade_to_head()
        print(f"Database is at revision {current_revision()}")
    elif action == "current":
        print(current_revision() or "(no revision: empty database)")
    elif action == "check":
        ok = is_current()
        print("up to date" if ok else f"behind: database {current_revision()}, latest {head_revision()}")
        return 0 if ok else 1
    else:
        print(__doc__)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
