# Parda Cinema

Parda is an Uzbek-first cinema discovery and seat-booking app. The React/Vite frontend uses a FastAPI backend and PostgreSQL. Prices are in UZS and showtimes use `Asia/Tashkent`.

- **Public demo:** https://parda-booking.vercel.app/
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
- [x] Seat selection, ten-minute pending holds, booking history, customer cancellation, and status transitions
- [x] Customer history clearing for cancelled/completed bookings (soft-archived; audit rows and active bookings are retained)
- [x] In-app card-form checkout: Uzcard, Humo, Visa, and Mastercard choices, booking summary, email code verification, current expiry validation, resend limits, and no real charge
- [x] Rolling Parda-owned demo sessions when the managed calendar has no future schedule
- [x] PostgreSQL protection against concurrent double booking and overlapping hall schedules
- [x] Uzbek/English/Russian UI, light/dark themes, accessible date chips, and responsive cinema artwork
- [x] Brevo transactional email delivery for signup verification, payment codes, and password resets
- [x] Booking confirmation emails plus durable 24-hour and 2-hour screening reminders
- [x] Full-screening waitlist with one-time email availability alerts and self-service withdrawal
- [x] Persistent saved-film list with one-time first-showtime email alerts
- [x] In-app notification center for ticket confirmation, reminder, waitlist, and saved-film delivery state
- [x] Operator-managed promo campaigns with expiry, spend rules, usage limits, and checkout revalidation
- [x] Parda Pass points: balance, reservation during checkout, redemption, and confirmed-ticket rewards
- [x] Live Cinematica programme discovery with five-minute refreshes and a bounded stale-cache fallback
- [x] Self-contained card checkout flow for Uzcard, Humo, Visa, and Mastercard with email-code confirmation
- [x] Customer cancellation, booking-history archival, expiring seat holds, and PostgreSQL protection against competing seat requests
- [x] Cinematica hall-directory sync keyed by public cinema and hall IDs, with traceable source URL and sync time
- [ ] Ticketon live cinema feed requires provider-approved cloud access; Ticketon currently returns HTTP 403 to the deployed Render service
- [x] Movie-detail cinema, format, language, Standard/VIP, and price filters
- [x] User-triggered nearest-cinema sorting using verified hall coordinates only
- [x] Protected catalog sync, sync-status, nearby-hall, and hall-coordinate API endpoints
- [x] Role-gated cinema operator dashboard for daily session capacity, ticket activity, confirmed revenue, hall inventory, schedule creation, and TMDB catalog refresh
- [x] QR e-tickets with opaque server-issued codes and a one-time operator check-in flow
- [x] Downloadable `.ics` calendar events from e-tickets, compatible with Google Calendar, Apple Calendar, and Outlook

## Assignment requirement mapping

The original assignment describes appointments. Parda applies the same booking model to a cinema: a **movie** is the service, an **auditorium/cinema operator** is the provider, and a **screening** is the dated availability window.

| Requirement | Parda implementation |
| --- | --- |
| Service name, description, duration, price | Admin can create films with title, synopsis, duration, genre, age mark, language, and poster. The screening form sets the server-owned ticket price. |
| Provider / employee | Admin creates cinema auditoriums with seat plans, timezone, formats, and Standard/VIP category. A cinema operator manages the associated schedules. |
| Availability | Admin schedules a film in an auditorium. The API rejects past times and overlapping hall intervals. |
| Users see available times and book | The film page fetches date, hall, format, price, and available-seat data before seat selection. |
| Pending, confirmed, cancelled, completed | `BookingStatus` supports all four states. A hold starts as pending; a verified demo payment confirms it; customers can cancel eligible tickets; admins complete finished screenings. |
| No double booking | PostgreSQL row locks plus the partial unique active-seat index return a conflict to competing seat requests. |
| Backend API, auth, validation, history | FastAPI endpoints are documented at `/docs`; JWT auth, Pydantic validation, email verification, booking history, soft history clearing, and role-gated administration are included. |
| Timezone, email, dashboard, Docker, docs | `Asia/Tashkent` is stored with halls, Brevo sends OTP email, the cinema operator dashboard manages films, halls, schedules, capacity and ticket states, Docker Compose and API docs are supplied. |

### Edge cases addressed

- A seat hold expires after ten minutes; expiry releases its seat assignments while preserving the audit record.
- A visitor can join a full screening’s waitlist for one to eight seats. A later release creates a durable one-time email alert, but never reserves seats or bypasses the normal first-come booking transaction.
- Saved films are scoped to the signed-in account. Parda queues one durable email when the film first receives a future Parda-managed screening; removing the saved film deletes any unsent alert.
- To stop seat hoarding, one customer can have at most 3 unpaid holds at once and at most 8 unpaid seats for any one screening (`MAX_PENDING_HOLDS_PER_USER`, `MAX_PENDING_SEATS_PER_SCREENING`). Expired, cancelled and paid bookings do not count, and a customer's holds are admitted one at a time under an account row lock so parallel requests cannot exceed the cap. A refused request explains what to do and how long the oldest hold has left.
- Two customers selecting the same seat are serialized by the database. One booking succeeds, and the other receives HTTP 409 with current availability on refresh.
- A user cannot book a past screening, choose a seat outside that auditorium, submit duplicate or more than eight seats. Customers can cancel any unused ticket; expired tickets are automatically hidden from their history on cancellation while the audit record remains. Admins can release an unused future booking while preserving its audit record.
- A second payment verification attempt cannot confirm someone else’s booking. Codes are hashed, expire, limit attempts, and are rate limited for resend.
- A paid ticket receives a non-personal, unique `PRD-` code. Check-in accepts it only once, only while the screening entry window is open, and never admits cancelled, pending, or already-used tickets.
- External discovery data is never the seat source of truth. Cinematica’s read-only programme is cached fresh for five minutes and can serve a bounded stale result for up to 24 hours when its upstream service is temporarily unreachable.
- New and returning unverified accounts resume the same verification flow without creating duplicate users; password resets are restricted to verified accounts.

## Demo checkout

The checkout is intentionally a **demo payment**. It accepts a syntactically valid card number, holder name, current or future expiry date, and CVV for Visa or Mastercard, then emails a four-digit confirmation code and marks the Parda booking as confirmed. No processor is contacted and no money moves.

On startup, Parda fills the next seven days of missing managed demo slots from its existing active films and halls. Existing screenings and conflicting slots are preserved.

The app accepts card details only to validate this one demo attempt. It stores only the last four card digits on the payment receipt. It never stores, logs, returns, or emails a card number, holder name, expiry, or CVV. Payment email codes are HMAC digests, expire after five minutes, allow five attempts, and have resend limits. A successful ticket queues one confirmation email and, when the showtime permits, reminders 24 hours and 2 hours before the screening. Each notification is recorded in PostgreSQL so a service restart cannot duplicate it.

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
- `EMAIL_MODE=brevo`, `BREVO_API_KEY`, `BREVO_FROM` (recommended for production)
- `APP_ENVIRONMENT=production`

`TMDB_MAX_PAGES` sets the number of pages imported per category (default 5); `TMDB_SYNC_INTERVAL_HOURS` sets the refresh interval (default 24). `NOTIFICATION_POLL_SECONDS` controls the reminder queue polling interval (default 60). TMDB tokens must remain server-side. Public signup needs a transactional email sender. The application supports Brevo's HTTPS API, Resend, and SMTP. For Brevo, register and verify the sender email address, create an API key, and keep both values only in the deployment environment. A custom sending domain improves delivery reputation but is not required for initial sender-email verification.

Bootstrap the admin with `ADMIN_EMAIL` and a unique `ADMIN_PASSWORD` of at least 12 characters. Configure real, operator-provided cinema halls, seat plans, prices, and screening schedules through the admin tools.

To grant the existing project owner a one-time operator role, set
`OPERATOR_BOOTSTRAP_NICKNAME` to that user's exact nickname, deploy once, and
then remove the variable. This bootstrap only promotes an existing account;
public users cannot self-assign roles.

### Vercel frontend

Set `VITE_API_URL` to the API origin and redeploy. Set the API `CORS_ORIGINS` to the exact Vercel site origin.

`frontend/vercel.json` also sets the browser security headers: a strict Content-Security-Policy (scripts only from the site itself, no inline script or `eval`, no framing, no plugins; images from any HTTPS host because film posters come from Cinematica and TMDB), HSTS, `nosniff`, `X-Frame-Options: DENY`, a referrer policy, a permissions policy that allows only geolocation (for "cinemas near me"), and long-lived caching for hashed `/assets`. `npm test` runs the session unit tests (Vitest) and `npm run check:headers` (run in CI after the build) fails if the policy is loosened or if the built page needs inline script. If a feature needs a new origin (an analytics host, an embedded player, a camera), add exactly that origin to the matching directive and re-test in a browser; the policy was verified against the catalogue, film page, sign-in dialog and seat map with no violations.

## Operations: health, logs, headers

- `GET /health` is readiness: it answers 200 only while the database responds and 503 within three seconds otherwise (it uses its own one-connection pool, so a stuck database cannot hang it or starve requests). Point hosting health checks here. `GET /health/live` is liveness only and never touches the database; the Docker `HEALTHCHECK` uses it so a database outage does not get a healthy process killed.
- Every response carries `X-Request-ID` (a valid incoming one is kept, otherwise one is generated). The same id is on every log line written while the request runs and in the body of unexpected 500 errors, so a customer's report can be matched to the logs. Logs are JSON in production (`LOG_FORMAT=json|text`, `LOG_LEVEL`), one `parda.access` line per request with method, path, status and duration; health probes log at DEBUG.
- All API responses send `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a restrictive `Permissions-Policy`; responses to authenticated requests are `Cache-Control: no-store`; production adds HSTS.
- The container runs as an unprivileged user.
- **Client addresses and rate limits.** In production the browser talks to Vercel, which rewrites `/api/*` to Render, so the API sees Vercel's address unless a header carries the customer's. `CLIENT_IP_HEADER` names that header (`x-forwarded-for`, first entry, by default in `render.yaml`). Check it after each deploy: sign in as an operator and open `/api/admin/diagnostics/client-ip` on the live site. `resolved_ip` must be your own address; if it is a Vercel/Render address, every customer shares one rate-limit bucket and the header setting needs to change.

## Sessions

Signing in returns a short-lived access token (`expires_in` seconds, `JWT_EXPIRE_MINUTES`) and sets a **refresh token in an `httpOnly` cookie** (`parda_refresh`: `SameSite=Strict`, `Secure` in production, path `/api/auth`) that page scripts cannot read. `POST /api/auth/refresh` trades the cookie for a new access token and **rotates** the cookie; only a SHA-256 hash of each refresh token is stored. If a token that was already rotated is presented again after `REFRESH_REUSE_GRACE_SECONDS` (default 10, which covers two tabs refreshing at once), it was copied: the whole sign-in is revoked, an `auth.refresh_reuse_detected` audit entry is written, and the user must sign in again. Sessions last `REFRESH_TOKEN_DAYS` (30) from last use and at most `REFRESH_FAMILY_MAX_DAYS` (90) from sign-in. `POST /api/auth/logout` ends this browser's session; "sign out of all devices" and a password reset end every session. Refresh and logout also refuse requests from origins outside `CORS_ORIGINS`.

### Browser session handling

The access token is kept only in memory (`frontend/src/session.ts`), never in `localStorage`. On load the page asks `/api/auth/refresh` (using the httpOnly cookie) for a token, so a reload or a new tab stays signed in; the token is renewed in the background a minute before it expires, and a request that still gets a 401 triggers one shared refresh and a retry. If the session has really ended (signed out elsewhere, cookie revoked or expired) the app returns to the signed-out state with a message; a network failure never signs anyone out. Every API call goes through `apiFetch`. Visitors signed in with the old `localStorage` token before this change are signed out once.

## Audit log

Operator and security-relevant actions are recorded in `audit_log`: film, hall, screening and promotion changes, catalogue syncs, operator booking-status changes, ticket check-ins, password resets, "sign out of all devices" and detected refresh-token replay. Each entry has the actor, action, target, a small details object (never secrets or card data), the request id (so it ties to the server logs) and the caller's address. Entries are written in the same transaction as the action, so a failed action leaves no entry, and the table is append-only: a database trigger rejects every `UPDATE` and `DELETE` except clearing the actor link when an account is deleted (the actor's email stays on the entry). Operators read it with `GET /api/admin/audit-log?limit=&before_id=&action=&actor_id=` (newest first; pass `next_before_id` as `before_id` for the next page). There is no automatic deletion; archive old rows with a scheduled job if the table grows large.

## Background jobs and scaling

Booking and waitlist e-mails, reminders and the Cinematica/TMDB refreshes run as scheduled jobs (`backend/app/jobs.py`).

- **Single service (default):** the API runs the jobs itself (`RUN_BACKGROUND_JOBS=true`). This is what a one-instance Render deploy uses.
- **Several API instances:** every job takes a PostgreSQL advisory lock for its pass, so instances never run the same job twice, and each e-mail is claimed with `FOR UPDATE SKIP LOCKED` and committed on its own. Nothing is sent twice, and a crash can lose track of at most the one message in flight.
- **Dedicated worker:** set `RUN_BACKGROUND_JOBS=false` on the web services and run `python -m app.worker` as a separate process (on Render, a Background Worker service with the same image/root directory). `python -m app.worker --once` runs every job once and exits non-zero if any failed, for use as a cron job.
- A notification that keeps failing is retried every `NOTIFICATION_RETRY_MINUTES` and abandoned after `NOTIFICATION_MAX_ATTEMPTS` (default 8); the last error stays on the row.

## Database migrations (Alembic)

The schema is versioned with Alembic (`backend/alembic/`). Revision `0001` is a frozen baseline: it builds a fresh database and brings a database left by any earlier release up to date (idempotent, `IF NOT EXISTS`). Every later schema change is a new revision.

```sh
cd backend
python -m app.migrate            # upgrade to the latest revision
python -m app.migrate current    # show the database's revision
python -m app.migrate check      # exit 1 if the database is behind
alembic revision -m "add thing"  # new revision: write explicit, tested SQL/ops in alembic/versions/
```

- `AUTO_MIGRATE=true` (default) upgrades the database when the API starts, under a PostgreSQL advisory lock so several instances starting together cannot collide. This is what keeps Render's free plan working, since it has no pre-deploy command.
- Once migrations run as their own release step (for example Render's `preDeployCommand: python -m app.migrate` on a paid plan), set `AUTO_MIGRATE=false`: the API then refuses to start on an out-of-date schema instead of altering it.
- Always change the models and add the revision in the same commit. A test builds a database from the migrations and fails if a model defines a table or column that no migration creates.
- Never edit `baseline_tables.sql`, `baseline_indexes.sql` or `migrations/*.sql`: they describe the schema existing databases already have.

## Booking and data safeguards

- Passwords and email-code digests are HMAC-protected, expire, and have attempt limits.
- Access tokens carry a per-account `token_version`. A password reset or `POST /api/auth/logout-all` ("Sign out of all devices" in the profile drawer) bumps it and immediately revokes every earlier token; deactivated accounts are rejected on the next request. Tokens issued before versioning remain valid until they expire.
- Sign-in, registration, verification-code and password-reset endpoints are rate limited with PostgreSQL-backed counters (shared across API instances). Repeated wrong passwords lock an account/address pair for 15 minutes (HTTP 429 with `Retry-After`); code guessing is capped per account. Set `CLIENT_IP_HEADER` (Render: `cf-connecting-ip`) so limits use the real caller address; leave it empty when the API is not behind a proxy that overwrites that header.
- API validates seat ownership and availability and calculates prices from current screening/seat data. A pending booking holds seats for ten minutes.
- Row locks and a partial unique index on active `(screening_id, seat_id)` assignments prevent competing bookings from taking the same seat. Collisions return HTTP 409.
- A PostgreSQL exclusion constraint prevents overlapping screenings in one hall. Cancelled and expired holds release seats while retaining booking history.
- Duplicate, foreign, past-screening, and excessive seat selections are rejected. Customers can only cancel their own eligible bookings.
- Demo payment attempts are bound to the authenticated booking and server-calculated total. A production payment provider must verify signed callbacks and transaction amount/order before a booking can be confirmed.
- Customer history clearing archives only cancelled and completed rows. Upcoming active holds/tickets remain visible; users cancel eligible bookings first.

## Backend layout

`backend/app/api.py` mounts the HTTP routes under `/api`; they live in `backend/app/routes/` grouped by domain: `auth` (registration, verification, sign-in, password reset, profile), `account` (loyalty balance, saved films, notifications), `catalog` (films, cinemas, screenings, seat maps, waitlist), `bookings` (holds, pricing, history, status changes), `payments` (demo checkout) and `admin` (operator dashboard, promotions, catalogue sync, ticket check-in, diagnostics). Logic used by more than one of them (seat-hold expiry, account locking, promo maths, serializers) is in `backend/app/services.py`. Background work is in `jobs.py`/`worker.py`, schema history in `alembic/`.

## Cinema catalogue architecture

```mermaid
flowchart LR
  C[Cinematica public catalogue] -->|read-only, cached| S[FastAPI catalogue adapter]
  S -->|source IDs, URL, sync time| D[(PostgreSQL hall directory)]
  D --> A[Admin: verify address and coordinates]
  S --> F[Movie detail / showtime filters]
  F --> B[Parda seat map and booking]
  B --> D2[(Parda bookings, holds, receipts)]
```

### Data policy and synchronization

- Cinematica is used only as a public discovery source. Parda does not access source checkout, source customer data, or source seat inventory.
- The sync reads current public movie repertory, rejects disabled, malformed, started, and expired rows, then upserts halls by `source_name + external_hall_id`. It stores the source cinema ID, hall ID, source URL, and `last_synced_at`.
- A scheduled Parda session is hidden when its managed inventory is sold out. A source time that clashes with a managed session in the same imported hall is also hidden before a customer can enter the seat map.
- Source payloads have a five-minute fresh cache and a 24-hour bounded stale fallback for read-only discovery. A source failure does not block Parda bookings that already exist.
- Cinematica-imported locations are deliberately blank until a cinema operator supplies verified address and latitude/longitude through the protected hall update endpoint. The UI never estimates a distance.

### Tashkent cinema sources

The movie detail page derives cinema filter choices from only the source sessions
returned for that film and date. This avoids a visitor selecting an operator
that has no matching time. `Tashkent City` comes from the existing Cinematica
public feed.

The code includes a narrow Ticketon adapter for CinemaPlex, Next Cinema,
Compass Cinema, Riviera Cinema, Parus Cinema, Magic Cinema, Sergeli Cinema,
Premier Cinema — Park in Mall, and O‘zbekiston Milliy kino san’ati saroyi. It
uses Ticketon’s public session API and accepts only future `on_sale` responses.
Ticketon currently returns HTTP 403 to the Render cloud service, so it does not
show an incomplete or invented programme in production. Provider-approved API
credentials or an allow-listed service IP are required before enabling that
live source. When available, the source is revalidated when a visitor selects
a time; a removed or off-sale time returns an unavailable response.

### Nearby cinemas and privacy

The site asks for browser location only after the visitor presses **Find cinemas near me**. It calculates a Haversine distance only for halls with verified map coordinates, and keeps the browser location in client memory. A live source venue can remain selectable without coordinates; it is simply not assigned a made-up distance. The API also supports server-side distance sorting through `GET /api/cinemas/nearby?lat=&lng=` for clients that need it.

### Directory and sync API

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `GET /api/cinematica/movies/{id}/screenings` | Public | Current valid source showtimes for one movie |
| `POST /api/cinematica/movies/{id}/ticketon/{session_id}/ticketing` | Public | Re-validates an on-sale Ticketon time then creates Parda's owned seat map |
| `GET /api/cinemas?city=Tashkent` | Public | Active Parda and imported halls |
| `GET /api/cinemas/nearby?lat=&lng=` | Public | Halls with verified coordinates, ordered by distance |
| `PATCH /api/cinemas/{id}` | Admin | Verify address, coordinates, formats, hall type, or disable a hall |
| `GET /api/admin/dashboard?date=YYYY-MM-DD` | Admin | Date-scoped session occupancy, booking activity, and confirmed-revenue dashboard |
| `GET /api/admin/cinemas` | Admin | Complete hall inventory, including disabled halls, for the operator workspace |
| `POST /api/admin/tickets/check-in` | Admin | Validate a confirmed e-ticket code once during the screening entry window |
| `POST /api/screenings/{id}/waitlist` | Signed-in customer | Request a one-time email when a full screening has enough seats again |
| `GET`, `PUT`, `DELETE /api/watchlist` | Signed-in customer | Read, save, or remove personal movies and their showtime alerts |
| `DELETE /api/screenings/{id}/waitlist` | Signed-in customer | Leave a screening waitlist request |
| `POST /api/admin/catalog-sync` | Admin | Run the idempotent source hall-directory sync |
| `GET /api/admin/catalog-sync/status` | Admin | Inspect imported hall count and most recent sync time |

## Verification

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request: backend lint (`ruff`) and tests against a PostgreSQL 16 service, frontend type-check and production build, and a Docker build of the API image. To run the same checks locally:

```sh
cd backend && pip install -r requirements-dev.txt
ruff check .
DATABASE_URL=postgresql+psycopg://booking:booking@localhost:5432/booking pytest -q
# the suite creates and drops its own throwaway database on that server (needs CREATEDB);
# database-backed tests skip if PostgreSQL is unreachable
cd ../frontend && npm ci && npm run build
```

The unit checks cover source-showtime normalization, source IDs, disabled/malformed rejection, and Asia/Tashkent-to-UTC conversion. PostgreSQL is responsible for active-seat uniqueness and hall-time exclusion; run concurrent booking checks against the configured PostgreSQL staging database before a commercial release.

## Known source limits

The public Cinematica feed currently provides cinema/hall labels, session time, price, and source identifiers. It does not provide verified street addresses, coordinates, physical capacities, cancellation state, or source seat counts. Parda therefore does not invent those fields. Complete operator verification and a licensed payment provider remain required before taking real money.

## TMDB attribution

Movie metadata and artwork are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. See [TMDB API documentation](https://developer.themoviedb.org/docs).

## Architecture and AI use

The React client presents a read-only public catalog alongside Parda-managed sessions. FastAPI proxies and caches discovery routes for five minutes. Parda's PostgreSQL models are the source of truth for Parda accounts, seats, holds, bookings, payments, and payment email challenges. TMDB remains a metadata/import source for the admin-managed catalog.

AI tools helped draft and revise UI, API/data-model scaffolding, and edge-case documentation. Review the implementation and provider behavior before production; verify real callbacks and concurrent seat reservations against staging data.
