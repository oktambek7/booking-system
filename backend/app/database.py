from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
# connect_timeout: a database that is down must fail requests (and health checks) quickly, not hang them.
# Keepalives let a connection to a vanished database host fail instead of waiting on a dead socket.
def engine_options() -> dict:
    """Pool and connection settings for the main engine, all from configuration (see DB_* in .env.example)."""
    connect_args = {"connect_timeout": 10, "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}
    if settings.db_statement_timeout_ms > 0:
        connect_args["options"] = f"-c statement_timeout={int(settings.db_statement_timeout_ms)}"
    return {"pool_pre_ping": True, "pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout_seconds, "pool_recycle": settings.db_pool_recycle_seconds,
            "connect_args": connect_args}

engine = create_engine(database_url, **engine_options())
# Health checks get their own single connection so a stuck probe can neither starve the request pool
# nor pile up: while one is stuck the next one fails at checkout after a second.
health_engine = create_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=1,
                              connect_args={"connect_timeout": 3})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
