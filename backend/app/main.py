from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from sqlalchemy import text
from . import models
from .api import router
from .database import Base, engine

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
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;"""))
    yield

app = FastAPI(title="Booking System API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}
