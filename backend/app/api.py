"""All HTTP routes, grouped by domain under app/routes/, mounted below /api."""
from fastapi import APIRouter
from .routes import account, admin, auth, bookings, catalog, checkout, live, operators, payments, privacy, reports, telegram, two_factor

router = APIRouter(prefix="/api")
for module in (auth, account, privacy, catalog, bookings, payments, checkout, admin, operators, reports, live, telegram, two_factor):
    router.include_router(module.router)
