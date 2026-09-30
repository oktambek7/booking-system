# Parda Cinema

Parda is an Uzbek-first cinema discovery and seat-booking app. The React/Vite frontend uses a FastAPI backend and PostgreSQL. Prices are in UZS and showtimes use `Asia/Tashkent`.

- **Public demo:** https://sana-booking.vercel.app/
- **API docs:** https://parda-cinema-api.onrender.com/docs
- **Source:** https://github.com/oktambek7/booking-system

> The public site is a portfolio/demo deployment. Some sample cinema and screening records may be present. They are not confirmation of a real cinema partnership or current operator inventory. Production card checkout is disabled; do not use the site to purchase tickets.

## Delivery state

- [x] PostgreSQL models for accounts, movies, halls, seats, showtimes, seat holds, bookings, and verification attempts
- [x] Four-digit email verification flow with expiring, limited-attempt hashed codes
- [x] TMDB region-aware current/upcoming catalog; configurable multi-page import of original titles, cast, posters, trailers, and release dates
- [x] Background TMDB refresh every 24 hours when a server token is configured
- [x] Explicit Standard/VIP auditorium types and schedule filtering
- [x] Seat selection, ten-minute pending holds, booking history, cancellation, and status transitions
- [x] PostgreSQL protection against concurrent double booking and overlapping hall schedules
- [x] Uzbek/English/Russian UI, light/dark themes, accessible date chips, and responsive cinema artwork
- [ ] Configure production SMTP sender and deliverability
- [ ] Load verified cinema/operator hall layouts, prices, and showtimes
- [ ] Complete merchant onboarding and payment-provider callback integration
- [ ] Exercise checkout, refunds/cancellation policy, and concurrent reservations in staging

**This is not production-ready ticketing yet.** Parda never collects card numbers, expiry dates, or CVV in its own forms. Card-brand choices are displayed, but the selected provider must collect card data on a hosted checkout page. In production, the current demo payment endpoint returns 503 rather than recording a simulated payment as successful.

TMDB provides movie metadata, not theater schedules or seat inventory. Only an authorized cinema operator can provide real showtimes and seats. Do not present sample schedules as confirmed public inventory.

## Run locally

Requires Python 3.12+, Node.js, and Docker Desktop.

```sh
docker compose up --build
```

The API runs at `http://localhost:8000`; docs: `http://localhost:8000/docs`. Copy `backend/.env.example` to `backend/.env`, set strong random `JWT_SECRET` and `OTP_SECRET` values, and set `EMAIL_MODE=mock` with `APP_ENVIRONMENT=development` for local signup verification. The mock OTP is returned only in this local mode.

Create `frontend/.env.local` with `VITE_API_URL=http://localhost:8000`. Then:

```sh
cd frontend
npm install
npm run dev
npm run build
```

A local admin can be created with:

```sh
docker compose exec -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD='use-a-long-unique-password' api python -m app.bootstrap_admin
```

## Deployment

### Render API

Deploy from `render.yaml`, attach PostgreSQL, and set these private values in the service environment:

- `DATABASE_URL`, `TMDB_READ_TOKEN`, `JWT_SECRET`, `OTP_SECRET`
- `CORS_ORIGINS` to the exact production frontend origin
- `EMAIL_MODE=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`
- `APP_ENVIRONMENT=production`

`TMDB_MAX_PAGES` sets the number of pages imported per category (default 5); `TMDB_SYNC_INTERVAL_HOURS` sets the refresh interval (default 24). TMDB tokens must remain server-side. Public signup needs a working SMTP sender.

Bootstrap the admin with `ADMIN_EMAIL` and a unique `ADMIN_PASSWORD` of at least 12 characters. Configure real, operator-provided cinema halls, seat plans, prices, and screening schedules through the admin tools.

### Vercel frontend

Set `VITE_API_URL` to the API origin and redeploy. Set the API `CORS_ORIGINS` to the exact Vercel site origin.

## Booking and data safeguards

- Passwords are hashed. Email/SMS code digests are HMAC-protected, expire, and have attempt limits.
- API validates seat ownership and availability and calculates prices from current screening/seat data. A pending booking holds seats for ten minutes.
- Row locks and a partial unique index on active `(screening_id, seat_id)` assignments prevent competing bookings from taking the same seat. Collisions return HTTP 409.
- A PostgreSQL exclusion constraint prevents overlapping screenings in one hall. Cancelled and expired holds release seats while retaining booking history.
- Duplicate, foreign, past-screening, and excessive seat selections are rejected. Customers can only cancel their own eligible bookings.
- A production payment provider must verify signed callbacks and transaction amount/order before a booking can be confirmed. The present mock SMS payment route is disabled in production.

## TMDB attribution

Movie metadata and artwork are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. See [TMDB API documentation](https://developer.themoviedb.org/docs).

## Architecture and AI use

The React client presents catalog, schedule, hall, and seat inventory. FastAPI owns authentication, validation, catalog synchronization, pricing, inventory, holds, and booking status. PostgreSQL is the source of truth for visitor and booking records. TMDB is a metadata source only.

AI tools helped draft and revise UI, API/data-model scaffolding, and edge-case documentation. Review the implementation and provider behavior before production; verify real callbacks and concurrent seat reservations against staging data.