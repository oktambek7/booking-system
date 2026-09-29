from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from . import models
from .api import router
from .database import Base, engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        conn.execute(text("""DO $$ BEGIN
          ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
          EXCLUDE USING gist (provider_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
          WHERE (status <> 'CANCELLED');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;"""))
    yield

app = FastAPI(title="Booking System API", version="0.1.0", lifespan=lifespan)
app.include_router(router)

@app.get("/health")
def health():
    return {"status": "ok"}
