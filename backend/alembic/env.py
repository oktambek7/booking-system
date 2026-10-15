from alembic import context
from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.database import Base, engine

target_metadata = Base.metadata

def run_migrations_online() -> None:
    # app.migrate hands in a connection that already holds the advisory lock.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
    else:
        with engine.connect() as connection:
            _run(connection)

def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    raise RuntimeError("Offline (SQL script) migrations are not supported; run against a database")
run_migrations_online()
