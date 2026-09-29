# Booking System

Mini appointment booking platform for a service business. Customers can browse services and providers, view available times, and manage bookings. Business staff can manage the catalog, availability, and appointments.

## Project progress

### Part 0 — Repository and project plan
- [x] Create project repository locally
- [x] Define implementation parts and completion checklist
- [x] Publish public GitHub repository

### Part 1 — Backend API
- [x] Choose and document architecture and database schema
- [x] Authentication and role-based access (customer, admin/provider)
- [x] Service and provider management endpoints
- [x] Weekly availability and exception dates
- [x] Availability search endpoint
- [x] Booking creation, status transitions, cancellation, and history
- [x] Validate input, ownership, business hours, and past dates
- [x] Prevent overlapping bookings under concurrent requests
- [x] API documentation (OpenAPI at `/docs`)

### Part 2 — Frontend booking experience
- [x] Responsive service and provider discovery
- [x] Date and available-time selection
- [x] Sign-up/sign-in and booking confirmation
- [x] Customer booking history and cancellation
- [x] Loading, empty, validation, and error states

### Part 3 — Business dashboard
- [ ] Manage services and providers
- [ ] Configure availability and exception dates
- [ ] View and update bookings

### Part 4 — Integration and delivery
- [ ] Connect frontend and backend
- [ ] Seed demo data and document demo credentials
- [ ] Document setup, architecture, tradeoffs, and edge cases
- [ ] Review AI-assisted work and explain key implementation decisions
- [ ] Deploy and add public demo URL

## Booking rules and edge cases

- A provider cannot have overlapping active bookings. Booking creation must enforce this atomically in the database/transaction so simultaneous requests for the same time cannot both succeed.
- Cancelled bookings do not block availability. Pending, confirmed, and completed bookings do.
- A booking must fit completely within provider availability and must not be in the past.
- Duration comes from the selected service; clients cannot override price or duration.
- Booking status transitions are validated, and customers can only view or cancel their own bookings.
- Store timestamps consistently (UTC) and display them in the business/customer timezone. Handle daylight-saving transitions explicitly.
- Reject malformed dates, invalid durations/prices, unavailable providers, and requests for inactive services.

## Run locally (backend)

Prerequisites: Docker Desktop and Docker Compose. From the repository root:

```sh
docker compose up --build
```

The API is at `http://localhost:8000`; interactive API documentation is at `http://localhost:8000/docs`. For anything beyond local development, set a unique high-entropy `JWT_SECRET` in the environment before starting Compose. The local database credentials in Compose are only for development.

## Run locally (frontend)

```sh
cd frontend
npm install
npm run dev
```

Without `VITE_API_URL`, the interface runs in interactive demo mode and stores demo bookings in this browser. To connect the API, copy `frontend/.env.example` to `frontend/.env.local`, set `VITE_API_URL` to the backend origin, and add the frontend origin to the backend `CORS_ORIGINS` value. Build with `npm run build` from `frontend/`. The frontend is a static Vite app and `frontend/vercel.json` handles SPA routes on Vercel.

Create the first admin in another terminal:

```sh
docker compose exec -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD='change-this-to-a-long-password' api python -m app.bootstrap_admin
```

Register customers at `POST /api/auth/register`, then sign in at `POST /api/auth/login`. Use the returned bearer token for protected routes. Admins create services and providers, then set weekly rules with `POST /api/providers/{id}/availability` (`weekday`: Monday=0 through Sunday=6). Customers query `GET /api/availability?service_id=1&provider_id=1&date=2026-10-01` and book with `POST /api/bookings` using an ISO-8601 `starts_at` that includes a timezone offset.

## Backend architecture

FastAPI exposes REST endpoints and generated OpenAPI docs. SQLAlchemy maps users, services, providers, provider/service assignments, weekly availability, and bookings to PostgreSQL. Passwords use Argon2 hashes; signed JWT bearer tokens carry user identity and role. Public reads expose active catalog and available times; catalog and schedule writes require an admin. Customers only access their own booking history and may cancel their own appointments. Providers linked to a user account may manage their own bookings.

Availability uses recurring weekday rules, local wall-clock times, and an IANA timezone per rule. Booking timestamps are stored as timezone-aware instants. Prices and service durations are copied to the booking at creation so later catalog edits do not alter existing appointments. PostgreSQL's GiST exclusion constraint over provider and half-open timestamp ranges is the final concurrency guard; the second simultaneous overlapping insert gets HTTP 409. `[start, end)` allows adjacent appointments. Cancelled bookings release a slot; other statuses continue to block it.

`backend/migrations/001_booking_overlap.sql` documents the required database constraint. The API applies it on startup as well. In production, use a managed PostgreSQL instance, a strong secret, HTTPS, and a controlled schema migration process.

## Edge cases and current scope

- Booking time must be in the future and include an explicit timezone offset.
- A service must be active and assigned to the selected provider; requested duration and price come from the server.
- Slots are offered at 15-minute increments and must fit wholly inside a weekly availability window.
- A database constraint resolves simultaneous requests, including requests from separate API workers.
- Status transitions are restricted: pending → confirmed/cancelled; confirmed → cancelled/completed. Cancelled and completed are terminal.
- Weekly availability is implemented; one-off closures, holidays, and split-shift overlap validation are follow-up work.
- Email notifications, calendar sync, and customer-facing frontend are follow-up parts.

## AI assistance

AI helped draft the initial schemas, API routes, and documentation. The design decisions are described above: PostgreSQL exclusion constraints protect the race condition, JWT roles protect management actions, and price snapshots preserve booking history. Review the code and exercise the OpenAPI flows before using it with real customers.

## Architecture

To be documented alongside Part 1 once the stack and persistence model are selected.

## AI assistance

AI assistance may be used during implementation. The final documentation will identify the assisted areas, explain the resulting code and design choices, and record how the implementation was reviewed.
