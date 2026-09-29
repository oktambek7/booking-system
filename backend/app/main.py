from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from . import models
from .api import router
from .config import settings
from .database import Base, SessionLocal, engine
from .models import Role, User
from .security import hash_password

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        migration = Path(__file__).resolve().parent.parent / "migrations" / "002_persistent_product_data.sql"
        for statement in migration.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                conn.exec_driver_sql(statement)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        conn.execute(text("""DO $$ BEGIN
          ALTER TABLE screenings ADD CONSTRAINT screenings_no_overlap
          EXCLUDE USING gist (auditorium_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
          WHERE (status = 'scheduled');
        EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL; END $$;"""))
    _ensure_initial_admin()
    yield

def _ensure_initial_admin() -> None:
    if not settings.admin_email and not settings.admin_password:
        return
    if not settings.admin_email or not settings.admin_password:
        raise RuntimeError("ADMIN_EMAIL and ADMIN_PASSWORD must be set together")
    if len(settings.admin_password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters")

    email = settings.admin_email.strip().lower()
    nickname = settings.admin_nickname.strip().lower()
    valid_nickname = nickname.replace("_", "").replace("-", "").replace(".", "").isalnum()
    if not nickname or len(nickname) > 40 or not valid_nickname:
        raise RuntimeError("ADMIN_NICKNAME must use letters, numbers, dot, dash, or underscore")

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            if existing.role != Role.ADMIN:
                raise RuntimeError("ADMIN_EMAIL already belongs to a non-admin account")
            return
        if db.scalar(select(User).where(User.nickname == nickname)):
            raise RuntimeError("ADMIN_NICKNAME is already in use")
        db.add(User(email=email, name=nickname, nickname=nickname,
                    password_hash=hash_password(settings.admin_password), role=Role.ADMIN,
                    active=True, phone_verified=False))
        db.commit()

app = FastAPI(title="Booking System API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}
