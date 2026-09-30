# Parda Cinema

Parda is an Uzbek-first cinema discovery and seat-booking app. The React/Vite frontend uses a FastAPI backend and PostgreSQL. Prices are in UZS and showtimes use `Asia/Tashkent`.

- **Public demo:** https://sana-booking.vercel.app/
- **API docs:** https://parda-cinema-api.onrender.com/docs
- **Source:** https://github.com/oktambek7/booking-system

> Parda reads Cinematica's public film and repertory feeds only for discovery and schedule previews. Parda never forwards customers to an external checkout. Its own managed sessions use Parda's PostgreSQL seats, holds, bookings, and demo payment flow.

## Delivery state

- [x] PostgreSQL models for accounts, movies, halls, seats, showtimes, seat holds, bookings, and verification attempts
- [x] Four-digit email verification flow with expiring, limited-attempt hashed codes
- [x] TMDB region-aware current/upcoming catalog; configurable multi-page import of original titles, cast, posters, trailers, and release dates
- [x] Cinematica live now-playing/upcoming movie catalog with age marks, posters, audio language, format, and read-only repertory previews
- [x] Film-first discovery: compact paginated posters, animated current-film carousel, and movie-specific dates/hall filters
- [x] Background TMDB refresh every 24 hours when a server token is configured
- [x] Explicit Standard/VIP auditorium types and schedule filtering
- [x] Seat selection, ten-minute pending holds, booking history, cancellation, and status transitions
- [x] Customer history clearing for cancelled/completed bookings (soft-archived; audit rows and active bookings are retained)
- [x] In-app demo card payment: Uzcard, Humo, Visa, and Mastercard test credentials, booking summary, email code verification, expiry, resend limits, and no real charge
- [x] PostgreSQL protection against concurrent double booking and overlapping hall schedules
- [x] Uzbek/English/Russian UI, light/dark themes, accessible date chips, and responsive cinema artwork
- [ ] Configure production SMTP sender and deliverability for payment verification emails
- [ ] Load verified cinema/operator hall layouts, prices, and showtimes
- [ ] Complete merchant onboarding and payment-provider callback integration
- [ ] Exercise checkout, refunds/cancellation policy, and concurrent reservations in staging

## Demo checkout

The checkout is intentionally a **demo payment**. It validates only the published test credentials, emails a four-digit confirmation code, and then marks the Parda booking as confirmed. No processor is contacted and no money moves.

| Method | Demo card | CVV |
| --- | --- | --- |
| Uzcard | `8600 0000 0000 0001` | Not used |
| Humo | `9860 0000 0000 0001` | Not used |
| Visa | `4242 4242 4242 4242` | `123` |
| Mastercard | `5555 5555 5555 4444` | `123` |

The app accepts a card number, holder name, expiry, and (where relevant) CVV only to validate this one demo attempt. It stores only the last four card digits on the payment receipt. It never stores, logs, returns, or emails a card number, holder name, expiry, or CVV. Payment email codes are HMAC digests, expire after five minutes, allow five attempts, and have resend limits.

TMDB provides movie metadata, not theater schedules or seat inventory. Cinematica's public data is cached for discovery only. It does not give Parda authority to lock source seats, sell source tickets, or guarantee the source feed. A real release needs operator-owned halls/schedules and a licensed payment provider with hosted or tokenized card entry.

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

- Passwords and email-code digests are HMAC-protected, expire, and have attempt limits.
- API validates seat ownership and availability and calculates prices from current screening/seat data. A pending booking holds seats for ten minutes.
- Row locks and a partial unique index on active `(screening_id, seat_id)` assignments prevent competing bookings from taking the same seat. Collisions return HTTP 409.
- A PostgreSQL exclusion constraint prevents overlapping screenings in one hall. Cancelled and expired holds release seats while retaining booking history.
- Duplicate, foreign, past-screening, and excessive seat selections are rejected. Customers can only cancel their own eligible bookings.
- Demo payment attempts are bound to the authenticated booking and server-calculated total. A production payment provider must verify signed callbacks and transaction amount/order before a booking can be confirmed.
- Customer history clearing archives only cancelled and completed rows. Upcoming active holds/tickets remain visible; users cancel eligible bookings first.

## TMDB attribution

Movie metadata and artwork are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. See [TMDB API documentation](https://developer.themoviedb.org/docs).

## Architecture and AI use

The React client presents a read-only public catalog alongside Parda-managed sessions. FastAPI proxies and caches discovery routes for five minutes. Parda's PostgreSQL models are the source of truth for Parda accounts, seats, holds, bookings, payments, and payment email challenges. TMDB remains a metadata/import source for the admin-managed catalog.

AI tools helped draft and revise UI, API/data-model scaffolding, and edge-case documentation. Review the implementation and provider behavior before production; verify real callbacks and concurrent seat reservations against staging data.
