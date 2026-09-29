# Parda Cinema

Lightweight cinema discovery and seat booking for moviegoers, with a cinema admin API. Uzbek-first interface, UZS prices, and Asia/Tashkent showtimes. The demo uses fictional sample films and a no-payment checkout; a payment provider can be added later.

## Project checklist

### Part 0 — Project setup
- [x] Public GitHub repository: https://github.com/oktambek7/booking-system
- [x] Product brief and staged delivery plan

### Part 1 — Cinema backend
- [x] Authentication and customer/admin roles
- [x] Manage movies, cinemas, halls, and screenings
- [x] Create seats from an auditorium layout
- [x] Browse screenings by local date, movie, and city
- [x] Read live seat availability and tiered prices
- [x] Place a temporary seat hold, confirm, cancel, and view booking history
- [x] Validate inputs, ownership, future showtimes, and status transitions
- [x] Prevent double booking with row locks and a PostgreSQL partial unique index
- [x] Prevent overlapping screenings in a hall with a PostgreSQL exclusion constraint
- [x] OpenAPI reference at `/docs`

### Part 2 — Customer cinema experience
- [x] Uzbek-first film discovery and date browsing
- [x] Showtime selection and clear auditorium context
- [x] Responsive seat map, explicit seat states, and ticket summary
- [x] Sign-up/sign-in, 10-minute seat hold, and no-payment confirmation
- [x] Booking history, cancellation, and hold-expiry states
- [x] Responsive, loading, empty, error, and seat-conflict states

### Part 3 — Cinema administration
- [x] Demo/admin panel to manage films, create screenings, and review bookings
- [x] Confirm and cancel booking status
- [x] Schedule visibility; hall/seat-layout creation through the admin API

### Part 4 — Delivery and explanation
- [x] Frontend can use the API through `VITE_API_URL`; browser-only demo seed included
- [x] Architecture, edge cases, and AI-assisted work documented
- [x] Production Vercel deployment and public URL

## Booking rules and edge cases

- The server accepts seat IDs and a screening ID; price is always calculated from the screening and each seat's tier.
- A booking starts as `pending` and holds its seats for ten minutes. The customer confirms within that window. Expired holds become cancelled and release their seats while preserving booking history.
- A PostgreSQL partial unique index permits only one active assignment for a `(screening_id, seat_id)`. Sorted row locks serialize competing requests; the uniqueness constraint remains the final guard across API workers. A losing request receives HTTP 409 and must refresh the seat map.
- Duplicate seats, more than eight seats, seats from another hall, started screenings, expired holds, and unauthorized booking access are rejected.
- Cancelling releases seat assignments. Confirmed bookings may be cancelled; completed and cancelled bookings are terminal. The demo has no charge or refund workflow.
- Showtimes are stored as timezone-aware instants. The auditorium timezone controls date filtering and display (default `Asia/Tashkent`). Adjacent screenings can meet at their boundary; overlapping screenings in one hall are rejected by a database exclusion constraint.
- Movie runtime determines the screening end time, so the client cannot submit an inconsistent duration.

## Architecture

FastAPI provides REST endpoints and generated OpenAPI docs. SQLAlchemy maps users, movies, auditoriums, seats, screenings, bookings, and seat assignments to PostgreSQL. Passwords are hashed; signed JWT bearer tokens protect booking and administration endpoints. Movie and screening reads are public, while writes require the admin role. Customers see only their own booking history and can only act on their own seats.

The seat map reports availability at read time; booking always rechecks inside a transaction. This avoids treating stale UI data as a reservation. Holds expire on API reads and booking actions, and the partial index is the authoritative race-condition guard. Production should run the SQL in `backend/migrations/001_cinema_constraints.sql` through a controlled migration process; application startup also ensures the constraints for this demo.

## Run locally

Prerequisites: Docker Desktop and Docker Compose.

```sh
docker compose up --build
```

The API runs at `http://localhost:8000`; interactive documentation is at `http://localhost:8000/docs`. Seed the fictional cinema catalog and screenings:

```sh
docker compose exec api python -m app.seed_demo
```

Create the first administrator:

```sh
docker compose exec -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD='use-a-long-unique-password' api python -m app.bootstrap_admin
```

Set a unique `JWT_SECRET` before any shared deployment. Local database credentials are development-only. Register customers at `POST /api/auth/register`, then sign in at `POST /api/auth/login` and send the returned bearer token to protected endpoints.

### Frontend

```sh
cd frontend
npm install
npm run dev
```

Without `VITE_API_URL`, the frontend provides a local interactive demo and saves demo account/bookings in that browser. To use the API, copy `.env.example` to `.env.local`, set `VITE_API_URL` to the API origin, and configure backend CORS for the frontend origin. Build using `npm run build`. `frontend/vercel.json` routes single-page app paths to the app shell.

The public Vercel preview currently runs this browser-only demo mode: sample bookings are stored in each visitor's browser and are not shared across visitors. The FastAPI/PostgreSQL backend provides shared booking state and the database race-condition guarantees when deployed and connected with `VITE_API_URL`; this repository includes the local Docker setup, but no production database credentials were supplied.

## API outline

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- `GET/POST/PATCH/DELETE /api/movies` (writes require admin)
- `GET/POST /api/cinemas` (writes require admin; create a hall layout)
- `GET /api/screenings?date=YYYY-MM-DD&movie_id=…&city=…`
- `POST /api/screenings` (admin)
- `GET /api/screenings/{id}/seats`
- `POST /api/bookings`, `POST /api/bookings/{id}/confirm`
- `GET /api/bookings`, `PATCH /api/bookings/{id}/status`

## AI-assisted work

AI assistance was used to draft the cinema schema, endpoint flow, interface implementation, and documentation. The implementation is reviewed against the actual SQLAlchemy models, authorization rules, server-side pricing, transaction behavior, and the PostgreSQL constraints. The user-facing checkout has no payment integration: it places and confirms a seat reservation only. The author should be ready to explain why a UI availability check is advisory, how the database resolves concurrent seat claims, and how expiring a hold releases seats without deleting its history.

## Deployment

- GitHub: https://github.com/oktambek7/booking-system
- Public Vercel demo: https://sana-booking.vercel.app (Parda Cinema; public access enabled)
- Payment provider, email notifications, and calendar integrations: future work
