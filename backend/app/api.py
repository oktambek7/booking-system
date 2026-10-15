"""All HTTP routes, grouped by domain under app/routes/, mounted below /api."""
from fastapi import APIRouter
from .routes import account, admin, auth, bookings, catalog, live, payments, telegram

router = APIRouter(prefix="/api")
for module in (auth, account, catalog, bookings, payments, admin, live, telegram):
    router.include_router(module.router)
