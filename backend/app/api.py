"""All HTTP routes, grouped by domain under app/routes/, mounted below /api."""
from fastapi import APIRouter
from .routes import account, admin, auth, bookings, catalog, checkout, live, payments, privacy, reports, telegram

router = APIRouter(prefix="/api")
for module in (auth, account, privacy, catalog, bookings, payments, checkout, admin, reports, live, telegram):
    router.include_router(module.router)
