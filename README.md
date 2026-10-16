<div align="center">

# PHANTORA

**Book a cinema seat in a few taps, without the queue and without the stress.**

[Open the live site](https://sana-booking.vercel.app/) · [Source code](https://github.com/oktambek7/parda-booking-system)

<img src="docs/screenshots/01-home.png" alt="Phantora home page with the featured film carousel" width="900">

</div>

---

## Preview

| Film catalogue | Showtimes and filters |
| :---: | :---: |
| <img src="docs/screenshots/02-catalogue.png" alt="Catalogue of films now showing, with search and favourites" width="440"> | <img src="docs/screenshots/03-showtimes.png" alt="Film page with dates, cinema, hall type, format, language and sorting filters" width="440"> |

| Seat selection | Checkout |
| :---: | :---: |
| <img src="docs/screenshots/04-seat-map.png" alt="Live seat map with free, selected, taken and premium seats" width="440"> | <img src="docs/screenshots/05-checkout.png" alt="Checkout with order summary, hold timer, promo code, points and card form" width="220"> |

| Light theme | On a phone |
| :---: | :---: |
| <img src="docs/screenshots/06-home-light.png" alt="Phantora home page in the light Ivory theme" width="440"> | <img src="docs/screenshots/07-phone.png" alt="Phantora on a phone: home, showtimes and the seat map" width="440"> |

Colours, type and the logo follow the Phantora brand kit; the design system is documented in [`DESIGN.md`](DESIGN.md).

---

## 1. What is Phantora?

Phantora is a web app for booking cinema seats online. You find a film, pick a showtime, choose the exact seats on a live hall map, and confirm. Phantora is built to make that path fast: fewer steps, less waiting, and less time spent on payment.

### Who it is for

- **Moviegoers** who want to pick their seats from a phone or laptop instead of standing in line at the box office.
- **Cinema companies** that want a modern, ready-to-run booking platform under their own name. Phantora is built to be handed over to a cinema operator, and it includes a staff dashboard for halls, schedules, ticket check-in and daily revenue.

### How it works for a visitor

1. **Create a profile.** Register with an email, a nickname and a profile picture. A 4-digit code sent to that email confirms the account.
2. **Find a film.** Browse what is showing now or coming soon, search by title, and save films you want to watch.
3. **Pick a showtime.** Filter by date, cinema, hall type (Standard or VIP), format (2D, 3D, IMAX) and language, then sort by time or price.
4. **Choose seats.** The hall map shows which seats are free, taken or premium. Once you continue, your seats are held for you for 10 minutes.
5. **Pay.** Enter card details (Uzcard, Humo, Visa or Mastercard) and type in the 4-digit code Phantora sends to your email.
6. **Keep your ticket.** Your QR ticket is emailed to you, stays in the app, and works offline at the cinema door.

> **About payments:** payment is currently a demonstration. No real money is charged. The card form and email code show how the real flow will work. A licensed payment provider will be connected once Phantora is handed over to a cinema company.

### Why choose Phantora over other booking platforms

| Advantage | What it means for you |
| --- | --- |
| **Your seats are truly yours** | Seats are held on the server for 10 minutes while you pay, and the database makes sure two people can never buy the same seat. No "sorry, this seat is gone" at the last step. |
| **Fast checkout** | One short page: order summary, a visible hold timer, card details and a 4-digit email code. No redirects to other websites. |
| **Made for Uzbekistan** | Prices in UZS, times in Tashkent time, local cards (Uzcard, Humo) as well as Visa and Mastercard. The interface is available in Uzbek, Russian and English, in light or dark mode. |
| **You never lose your ticket** | An emailed confirmation, a QR ticket that works offline, and a calendar file you can add to Google, Apple or Outlook calendar. |
| **Sold out? Get notified** | Join the waitlist for a full screening and receive an email if seats free up. Save a film and receive an email when its first showtime appears. |
| **Rewards** | Promo codes and Phantora Points (1 point = 100 UZS, up to 50% of an order) make returning visits cheaper. |
| **Paperless entry** | Every ticket gets a QR e-ticket that staff scan once at the entrance. |
| **Clear at a glance** | The seat map uses labels and icons, not only colors, so it is easy to read for everyone. The full order summary is shown before you confirm. |

---

## 2. Technical tools

Phantora is split into three clear parts: a **frontend** the user sees, a **backend API** that makes every decision, and a **database** that is the single source of truth. Each part has one job, which keeps the system predictable and easy to maintain.

### Frontend (what the user sees)

| Tool | Why it is used |
| --- | --- |
| **React 19** | Builds the interface from small reusable components (catalogue, seat map, checkout). |
| **TypeScript** | Catches mistakes before the code runs, so data from the API is always used in the right shape. |
| **Vite** | Very fast development server and an optimized production build. |
| **Lucide icons**, **Manrope** and **Unbounded** fonts | A consistent, clean visual style. |
| **qrcode.react** | Draws the QR code on every e-ticket. |
| **Vercel** | Hosts the site on a global CDN, so pages load quickly, and forwards `/api` calls to the backend. |

### Backend (where the rules live)

| Tool | Why it is used |
| --- | --- |
| **Python 3.12 + FastAPI** | A fast, modern API framework with automatic API documentation. |
| **Pydantic** | Checks every incoming request (seat numbers, card format, dates) before it is processed, so bad data never reaches the database. |
| **SQLAlchemy + psycopg** | Talks to the database safely and consistently. |
| **JWT + Argon2** | Secure sign-in tokens, and passwords stored with a strong one-way hash. |
| **Hashed, expiring email codes** | The 4-digit codes expire after a few minutes, allow only a limited number of attempts, and are never stored in plain text. |
| **Background workers** | Run on their own schedule inside the API: send confirmations and alerts every minute, refresh showtimes every 10 minutes, refresh film details every 24 hours. |
| **Brevo** (Resend and SMTP also supported) | Delivers sign-up codes, payment codes, ticket confirmations by email. |
| **Docker + Render** | The API runs in a container, so it behaves the same on a laptop and in production. |

### Database (the single source of truth)

| Tool | Why it is used |
| --- | --- |
| **PostgreSQL 16** | Stores users, halls, seats, seat holds, bookings, payments and the notification queue. |
| **Row locks and unique indexes** | When two people click the same seat at the same moment, only one booking succeeds. The other person is told immediately. |
| **Exclusion constraint on halls** | Two screenings can never be scheduled in the same hall at overlapping times. |
| **Durable notification queue** | Every confirmation and alert is recorded in the database, so a server restart cannot send it twice or lose it. |

### Data sources

| Source | What Phantora takes from it |
| --- | --- |
| **Cinematica** | Films now showing and coming soon, posters, age ratings and showtimes. Read-only and cached, so a slow source never slows Phantora down. |
| **TMDB** | Extra film details and artwork. Phantora uses the TMDB API but is not endorsed or certified by TMDB. |

### How Phantora avoids chaos

- **The server decides, not the browser.** Prices, seat availability and booking status are always calculated on the backend, so nobody can change a price or grab a taken seat from their browser.
- **Short seat holds.** A seat is reserved for 10 minutes during checkout. If payment is not finished, the seat is released automatically for other people.
- **No double booking.** The database itself blocks two active bookings for the same seat and the same screening.
- **Caching external data.** Showtimes from Cinematica are cached and refreshed in the background. If the source is briefly unavailable, Phantora keeps working from the last good copy.
- **Reliable emails.** Confirmations and alerts are queued in the database and sent by a background worker, so they go out on time and only once.
- **Card data is not kept.** Only the last four digits of the card are saved on the receipt. The full number, holder name, expiry and CVV are never stored, logged or emailed.

---

## 3. Architecture diagram

<p align="center">
  <img src="docs/architecture.svg" alt="Phantora architecture: the moviegoer's browser talks to the React frontend on Vercel, which calls the FastAPI backend on Render. The backend reads films and showtimes from Cinematica and TMDB, stores everything in PostgreSQL, and sends emails through Brevo to the user's inbox." width="100%">
</p>

**How to read it:**

1. The **moviegoer** opens Phantora in a browser. The **React frontend** on Vercel shows films, showtimes, the seat map and checkout.
2. Every action (sign in, hold seats, pay) is sent as a request to the **FastAPI backend** on Render.
3. The backend reads films and showtimes from **Cinematica** and film details from **TMDB**, and keeps a cached copy.
4. All accounts, seats, holds, bookings and notifications are stored in **PostgreSQL**, which prevents double booking.
5. The backend sends emails through **Brevo**: the 4-digit codes, the ticket confirmation and refund notices, straight to the user's **inbox**.

---

# Technical reference

Everything below is the developer and operations documentation: behaviour guarantees, configuration, security, payments, and the production checklist.


Phantora is an Uzbek-first cinema discovery and seat-booking app. The React/Vite frontend uses a FastAPI backend and PostgreSQL. Prices are in UZS and showtimes use `Asia/Tashkent`.

- **Public demo:** https://parda-booking.vercel.app/
- **API docs:** https://parda-cinema-api.onrender.com/docs
- **Source:** https://github.com/oktambek7/booking-system

> Phantora reads Cinematica's public film and repertory feeds only for discovery and schedule previews. Phantora never forwards customers to an external checkout. Its own managed sessions use Phantora's PostgreSQL seats, holds, bookings, and demo payment flow.

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
- [x] Rolling Phantora-owned demo sessions when the managed calendar has no future schedule
- [x] PostgreSQL protection against concurrent double booking and overlapping hall schedules
- [x] Uzbek/English/Russian UI, light/dark themes, accessible date chips, and responsive cinema artwork
- [x] Brevo transactional email delivery for signup verification, payment codes, and password resets
- [x] Durable booking confirmation emails (screening reminders were removed; reminders already queued are deleted unsent)
- [x] Full-screening waitlist with one-time email availability alerts and self-service withdrawal
- [x] Persistent saved-film list with one-time first-showtime email alerts
- [x] In-app notification center for ticket confirmation, waitlist, and saved-film delivery state
- [x] Operator-managed promo campaigns with expiry, spend rules, usage limits, and checkout revalidation
- [x] Phantora Pass points: balance, reservation during checkout, redemption, and confirmed-ticket rewards
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

The original assignment describes appointments. Phantora applies the same booking model to a cinema: a **movie** is the service, an **auditorium/cinema operator** is the provider, and a **screening** is the dated availability window.

| Requirement | Phantora implementation |
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
- Saved films are scoped to the signed-in account. Phantora queues one durable email when the film first receives a future Phantora-managed screening; removing the saved film deletes any unsent alert.
- To stop seat hoarding, one customer can have at most 3 unpaid holds at once and at most 8 unpaid seats for any one screening (`MAX_PENDING_HOLDS_PER_USER`, `MAX_PENDING_SEATS_PER_SCREENING`). Expired, cancelled and paid bookings do not count, and a customer's holds are admitted one at a time under an account row lock so parallel requests cannot exceed the cap. A refused request explains what to do and how long the oldest hold has left.
- Two customers selecting the same seat are serialized by the database. One booking succeeds, and the other receives HTTP 409 with current availability on refresh.
- A user cannot book a past screening, choose a seat outside that auditorium, submit duplicate or more than eight seats. Customers can cancel any unused ticket; expired tickets are automatically hidden from their history on cancellation while the audit record remains. Admins can release an unused future booking while preserving its audit record.
- A second payment verification attempt cannot confirm someone else’s booking. Codes are hashed, expire, limit attempts, and are rate limited for resend.
- A paid ticket receives a non-personal, unique `PRD-` code. Check-in accepts it only once, only while the screening entry window is open, and never admits cancelled, pending, or already-used tickets.
- External discovery data is never the seat source of truth. Cinematica’s read-only programme is cached fresh for five minutes and can serve a bounded stale result for up to 24 hours when its upstream service is temporarily unreachable.
- New and returning unverified accounts resume the same verification flow without creating duplicate users; password resets are restricted to verified accounts.

## Demo checkout

The checkout is intentionally a **demo payment**. It accepts a syntactically valid card number, holder name, current or future expiry date, and CVV for Visa or Mastercard, then emails a four-digit confirmation code and marks the Phantora booking as confirmed. No processor is contacted and no money moves.

That is the default (`PAYMENT_PROVIDER=demo`). See **Payment providers** below for the hosted-checkout path that a real gateway plugs into.

On startup, Phantora fills the next seven days of missing managed demo slots from its existing active films and halls. Existing screenings and conflicting slots are preserved.

The app accepts card details only to validate this one demo attempt. It stores only the last four card digits on the payment receipt. It never stores, logs, returns, or emails a card number, holder name, expiry, or CVV. Payment email codes are HMAC digests, expire after five minutes, allow five attempts, and have resend limits. A successful ticket queues one confirmation email. Each notification is recorded in PostgreSQL so a service restart cannot duplicate it.

TMDB provides movie metadata, not theater schedules or seat inventory. Cinematica's public data is cached for discovery only. It does not give Phantora authority to lock source seats, sell source tickets, or guarantee the source feed. A real release needs operator-owned halls/schedules and a licensed payment provider with hosted or tokenized card entry.

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

`TMDB_MAX_PAGES` sets the number of pages imported per category (default 5); `TMDB_SYNC_INTERVAL_HOURS` sets the refresh interval (default 24). `NOTIFICATION_POLL_SECONDS` controls the notification queue polling interval (default 60). TMDB tokens must remain server-side. Public signup needs a transactional email sender. The application supports Brevo's HTTPS API, Resend, and SMTP. For Brevo, register and verify the sender email address, create an API key, and keep both values only in the deployment environment. A custom sending domain improves delivery reputation but is not required for initial sender-email verification.

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

### Error reporting and the database pool

- **Sentry (optional).** Set `SENTRY_DSN` (an `https://` URL; `SENTRY_RELEASE` and `SENTRY_TRACES_SAMPLE_RATE` are optional) and unhandled errors are reported. Nothing personal leaves the server: default PII is off and `app/monitoring.py` removes cookies, authorization and client-address headers, request bodies, query strings and the user from every event. Without a DSN nothing is sent, and a failure to start Sentry never stops the API. Match a report with the logs by the `X-Request-ID` shown in the 500 response.
- **Connection pool.** Each API process opens at most `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections (5 + 10 by default), recycled after `DB_POOL_RECYCLE_SECONDS`. Keep that total, times the number of processes (the web service and the worker each count), below the database plan's connection limit; a free Render Postgres allows few connections, so lower the values there before adding a worker. `DB_STATEMENT_TIMEOUT_MS` (0 = off) stops a runaway query; do not set it below the time a CSV export of a long date range needs.

## Operator reports (CSV)

The operator panel's **Hisobotlar** tab downloads two CSV files for a date range of at most 366 days, by screening date in the business time zone (`GET /api/admin/reports/bookings.csv?from=&to=` and `revenue.csv`): the **bookings** list (one row per booking with film, hall, seats, totals, promo, refund, ticket code and check-in time) and the **revenue** report (per day, hall and film: paid tickets, seats, money paid, refunded and net, counting cancelled and refunded tickets correctly). Files are UTF-8 with a byte-order mark so Excel reads Uzbek and Russian text, are streamed row by row (a large range cannot exhaust memory), are limited to 30 exports per operator per hour, and every export is written to the audit log. Because customer nicknames and film titles can start with `=`, `+`, `-` or `@` and a spreadsheet would run them as formulas, every text cell that starts that way is prefixed with an apostrophe (CSV injection); a test plants such values in every text column and checks that no cell can start a formula.

## Your data: export and deletion

In the profile drawer a customer can **download everything the system holds about them** (`GET /api/account/export`: account, bookings, payments, refunds, notifications, saved films, waitlist, loyalty, Telegram link status, active sessions and their own activity log as JSON; never password or token hashes, never anyone else's data; limited to 5 per hour) or **delete the account** (`DELETE /api/account`; needs the password again and an explicit acknowledgement; 5 attempts per hour).

Deletion **anonymizes** instead of removing the row, because bookings, payments and refunds are financial records that have to be kept: the account becomes `deleted-user-<id>@deleted.invalid` with no name, avatar, phone or password, sessions end at once, points are forfeited, unpaid holds are released (seats freed), and every personal side record is erased (Telegram link, saved films, waitlist entries, verification and reset codes, refresh tokens). The e-mail address and nickname can be registered again. It is refused while the customer has an **upcoming paid ticket** (cancel it for the refund first) and for operator accounts (another operator must remove the role first). Audit-log entries stay but their e-mail becomes the tombstone and their address is cleared; the log's append-only trigger permits exactly those two changes and nothing else. A confirmation e-mail goes to the old address.

## Telegram notifications

Customers can get the same messages (ticket confirmation, refunds, waitlist and saved-film alerts) in Telegram. It is **off until you create a bot**: talk to @BotFather, then set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` (without the @) and a random `TELEGRAM_WEBHOOK_SECRET` (16+ characters), deploy, and register the webhook once with `python -m app.telegram_setup https://<your-api-host>/api/telegram/webhook`. A customer then presses **Connect Telegram** in their profile, taps Start in the bot, and the page shows "connected".

How it stays safe: the link token is single-use, expires in 15 minutes and only its hash is stored; the webhook accepts only requests carrying the secret registered with Telegram (compared in constant time, `403` otherwise); a chat can belong to one account only; link requests are rate-limited; messages are plain text (a film title cannot inject formatting); Telegram is sent only after the e-mail succeeded, never blocks or fails it, and a chat that blocked the bot is unlinked automatically. Only the chat id is stored, and `/stop` in the bot, the Disconnect button or deleting the account removes it. Production start-up refuses a bot token without a username and webhook secret.

## Ticket scanner

In the operator panel's **Chiptalar** tab, "Kamera bilan skanerlash" opens the camera and checks tickets in from their QR codes (the e-ticket QR carries the ticket code). Decoding uses [jsQR](https://github.com/cozmo/jsQR) (Apache-2.0), loaded only when the scanner opens, so it works on every browser including iOS Safari. A ticket is submitted once each time it comes into view and again only after it has left the frame, so a steady hand does not repeat the request; QR codes that are not Phantora tickets are ignored; the page keeps scanning between guests, and if the camera is denied or missing the manual code field still works. Camera access needs `camera=(self)` in the Permissions-Policy header (set in `frontend/vercel.json` and enforced by `npm run check:headers`) and HTTPS.

## Payment providers

`app/payment_providers.py` defines what a gateway must do: create a hosted checkout, authenticate its own webhooks, and refund. Phantora ships the `demo` checkout and a `sandbox` provider that behaves like a real gateway (redirect out, signed webhook back, refund API) without any merchant account, so the whole path is tested end to end. **No real gateway (Payme, Click, Uzum, Stripe ...) is implemented yet: that needs merchant credentials and the gateway's documentation; it is one more class in that file plus an entry in `get_provider`.**

Flow with a provider: `POST /api/payments/checkout {booking_id}` (optional `Idempotency-Key` header) creates a payment in `awaiting_provider` and returns the hosted page URL; the browser goes there; the provider calls `POST /api/payments/webhook/{provider}`; only that signed callback confirms the booking (`app/checkout.py`). The browser is sent back to `/?payment=<reference>` and the app polls `GET /api/payments/by-reference/{reference}` until the webhook has landed.

What the webhook handler guarantees: the signature (HMAC-SHA256 over `timestamp.body`, constant-time compare) and a five-minute replay window are checked before anything is read; every event id is recorded in `payment_events` in the same transaction as its effects, so a redelivery, even a simultaneous one, is applied once; a reported amount that differs from the payment, or is missing, never confirms a booking and is audited; a payment whose booking was cancelled or expired meanwhile is refunded automatically (or flagged `paid_unfulfilled` in the audit log if the refund call fails); a pending booking whose hold has only just lapsed still owns its seats, so it is confirmed; and the price the customer paid is honoured even if the promotion has lapsed since. The same idempotency key from the same customer returns the same payment instead of a second one, and returning to checkout resumes an open payment. Cancelling a paid ticket calls the provider's refund first with a stable idempotency key; if the provider refuses, nothing is cancelled and the customer keeps the ticket (`502`).

`PAYMENT_PROVIDER=sandbox` lets anyone approve their own payment, so the production validator refuses it, and any provider other than `demo` needs a `PAYMENT_WEBHOOK_SECRET` of at least 32 characters. Provider calls currently run inside the request's database transaction, which keeps the logic simple; a slow gateway would justify moving refunds to a background job.

## Installable app and offline tickets

Phantora is a Progressive Web App: `manifest.webmanifest` plus 192/512/maskable icons make it installable ("Add to Home Screen"), and `public/sw.js` keeps the app shell and its hashed build assets available without a connection. Pages are network-first (an online visitor always gets the newest build), build assets are cache-first with an 80-entry cap, and the worker never touches `/api`, `/health`, non-GET requests or other origins (film posters), so no personal data enters the browser cache. The worker is registered in production builds only and is served with `Cache-Control: max-age=0, must-revalidate`.

For the cinema door, the app keeps the customer's upcoming confirmed tickets in `localStorage` (`phantora_offline_tickets`): film, hall, time, seats and ticket code only, with no e-mail, name or payment data, at most 20 tickets, dropped three hours after the film ends. If the app cannot reach the server at start-up it shows an offline banner whose button opens those tickets with their QR codes, drawn on the device; when the connection returns the page reloads and signs the customer back in. The wallet is wiped on sign-out and when the session ends. `npm run check:headers` also validates the manifest, its icons and the worker's cache header.

## Live seat map

An open seat map updates by itself when someone else takes or releases a seat, and drops seats you had selected that someone just took (with a message). A database trigger sends a PostgreSQL `NOTIFY` whenever a seat's availability changes (every source: new holds, cancellations, hold expiry), each API process keeps one `LISTEN` connection, and `GET /api/screenings/{id}/seats/stream` (Server-Sent Events) pings the browsers watching that screening; the page then refetches the normal seat list, so nothing new is exposed. Bursts are coalesced, idle streams get a heartbeat, one address may hold `LIVE_MAX_STREAMS_PER_IP` (10) streams and a process `LIVE_MAX_STREAMS` (2000), and the listener reconnects with backoff and tells pages to resync after a gap. If a proxy will not keep a stream open the page falls back to refreshing every 15 seconds; nothing is fetched while its tab is hidden. `LIVE_UPDATES_ENABLED=false` turns the stream off. Behind Vercel's rewrite the stream passes through a proxy whose streaming limits are outside this repository, so check it on the live site; the polling fallback keeps the map current either way.

## Cancellations and refunds

A customer who cancels a **paid** ticket is refunded a share of the price that depends on how far away the screening is: 100% from `REFUND_FULL_HOURS` (24) before it starts, `REFUND_PARTIAL_PERCENT` (50%) from `REFUND_PARTIAL_HOURS` (2) before, and nothing after that. An operator cancelling a ticket always refunds in full. The amount is rounded down to a whole sum. The Phantora Points spent on the booking come back in the same proportion and the points it earned are taken back in the same proportion (never below zero). Unpaid holds have nothing to refund. Promo-code usage is not restored.

`GET /api/bookings/{id}/cancellation-quote` previews the result (the app shows it before the customer confirms) and `GET /api/refund-policy` publishes the policy. Refunds are recorded in a ledger with one row per payment (a unique index makes a second refund impossible), in the same transaction as the cancellation; the payment becomes `refunded_demo` or `partially_refunded_demo`, the customer gets a refund email, the operator dashboard totals the money returned, and each refund is in the audit log. Demo payments move no money; a payment made through a payment provider is refunded through that provider (see **Payment providers**).

## Sessions

Signing in returns a short-lived access token (`expires_in` seconds, `JWT_EXPIRE_MINUTES`) and sets a **refresh token in an `httpOnly` cookie** (`parda_refresh`: `SameSite=Strict`, `Secure` in production, path `/api/auth`) that page scripts cannot read. `POST /api/auth/refresh` trades the cookie for a new access token and **rotates** the cookie; only a SHA-256 hash of each refresh token is stored. If a token that was already rotated is presented again after `REFRESH_REUSE_GRACE_SECONDS` (default 10, which covers two tabs refreshing at once), it was copied: the whole sign-in is revoked, an `auth.refresh_reuse_detected` audit entry is written, and the user must sign in again. Sessions last `REFRESH_TOKEN_DAYS` (30) from last use and at most `REFRESH_FAMILY_MAX_DAYS` (90) from sign-in. `POST /api/auth/logout` ends this browser's session; "sign out of all devices" and a password reset end every session. Refresh and logout also refuse requests from origins outside `CORS_ORIGINS`.

### Browser session handling

The access token is kept only in memory (`frontend/src/session.ts`), never in `localStorage`. On load the page asks `/api/auth/refresh` (using the httpOnly cookie) for a token, so a reload or a new tab stays signed in; the token is renewed in the background a minute before it expires, and a request that still gets a 401 triggers one shared refresh and a retry. If the session has really ended (signed out elsewhere, cookie revoked or expired) the app returns to the signed-out state with a message; a network failure never signs anyone out. Every API call goes through `apiFetch`. Visitors signed in with the old `localStorage` token before this change are signed out once.

## Operator accounts and per-cinema access

There are two kinds of operator (role `admin`). An **owner** manages everything. An operator **limited to some cinemas** (`users.cinema_scoped`, with the cinemas in `cinema_operators`, matched on the hall's cinema name) sees and changes only those cinemas: the halls list, the day's dashboard, the booking list, cancellation quotes and cancellations (with their refunds), ticket check-in, scheduling screenings, editing or adding halls inside their cinemas, and the CSV reports. A booking or ticket from another cinema answers `404` (it does not reveal that it exists); a hall or screening in another cinema answers `403`. What is global stays owner-only: the film catalogue, promotions, catalogue syncs, the audit log, diagnostics and operator accounts. The operator panel hides those tabs for a limited operator, but the server is what enforces it (`app/operators.py`, tested in `tests/test_operator_scope.py`).

Owners manage operators from the **Operatorlar** tab or the API: `GET /api/admin/operators`, `PUT /api/admin/operators {email, cinemas}` (a list limits the account to those cinemas, `null` makes an owner; the account must exist, be active and have a verified e-mail) and `DELETE /api/admin/operators/{user_id}` (back to an ordinary customer, signed out everywhere). Every change is audited. Two safeguards keep the system from locking itself out: nobody can change or remove their own access, and operator changes are serialised and re-check the acting owner after taking the lock, so two owners cannot remove each other at the same moment. Scoping is an explicit flag rather than "has rows", so removing a limited operator's last cinema leaves them with access to nothing, never owner rights. Existing operators (including the bootstrap `ADMIN_EMAIL` account) stay owners.

## Two-step verification

Any account can turn on two-step verification from the profile panel: Phantora shows a QR code (and the key) for an authenticator app, confirms the first 6-digit code, then shows ten single-use recovery codes once. After that, signing in with the right password answers with a short-lived challenge instead of a session, and the session starts only after `POST /api/auth/login/2fa` accepts a current code or a recovery code. Turning it on also ends every other sign-in of the account; turning it off (or replacing the recovery codes) needs the password and a current code.

What it guarantees: codes are standard TOTP (RFC 6238, SHA-1, 30 s, one step of clock drift, checked against the RFC test vectors); an accepted code cannot be used again (the last accepted time step is stored); wrong codes are limited to five per account per 15 minutes, across sign-in, disabling and recovery-code changes together; the shared secret is encrypted at rest (Fernet, key from `TOTP_ENCRYPTION_KEY`, else `OTP_SECRET`) and recovery codes are stored only as keyed hashes; the sign-in challenge is a different kind of token and is refused as an access token; and every refresh of a session keeps the record of whether it passed the second step.

`REQUIRE_OPERATOR_2FA=true` makes operator powers depend on it: operator endpoints, and operator behaviour on the shared booking endpoints, work only with an access token from a sign-in that included the second step (`security.acts_as_operator`); an operator who has not enrolled is treated as an ordinary customer until they do, and operators cannot turn it off. It is off by default so that turning this release on cannot lock an existing operator out: enrol every operator first, then set it. Losing both the phone and the recovery codes needs a database-level reset (delete that user's rows from `user_totp`).

## Audit log

Operator and security-relevant actions are recorded in `audit_log`: film, hall, screening and promotion changes, catalogue syncs, operator booking-status changes, ticket check-ins, password resets, "sign out of all devices" and detected refresh-token replay. Each entry has the actor, action, target, a small details object (never secrets or card data), the request id (so it ties to the server logs) and the caller's address. Entries are written in the same transaction as the action, so a failed action leaves no entry, and the table is append-only: a database trigger rejects every `UPDATE` and `DELETE` except clearing the actor link when an account is deleted (the actor's email stays on the entry). Operators read it with `GET /api/admin/audit-log?limit=&before_id=&action=&actor_id=` (newest first; pass `next_before_id` as `before_id` for the next page). There is no automatic deletion; archive old rows with a scheduled job if the table grows large.

## Background jobs and scaling

Booking and waitlist e-mails and the Cinematica/TMDB refreshes run as scheduled jobs (`backend/app/jobs.py`).

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
- Demo payment attempts are bound to the authenticated booking and server-calculated total. A payment provider's callbacks are verified by signature, replay window and amount/reference before a booking can be confirmed (see **Payment providers**).
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
  F --> B[Phantora seat map and booking]
  B --> D2[(Phantora bookings, holds, receipts)]
```

### Data policy and synchronization

- Cinematica is used only as a public discovery source. Phantora does not access source checkout, source customer data, or source seat inventory.
- The sync reads current public movie repertory, rejects disabled, malformed, started, and expired rows, then upserts halls by `source_name + external_hall_id`. It stores the source cinema ID, hall ID, source URL, and `last_synced_at`.
- A scheduled Phantora session is hidden when its managed inventory is sold out. A source time that clashes with a managed session in the same imported hall is also hidden before a customer can enter the seat map.
- Source payloads have a five-minute fresh cache and a 24-hour bounded stale fallback for read-only discovery. A source failure does not block Phantora bookings that already exist.
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
| `POST /api/cinematica/movies/{id}/ticketon/{session_id}/ticketing` | Public | Re-validates an on-sale Ticketon time then creates Phantora's owned seat map |
| `GET /api/cinemas?city=Tashkent` | Public | Active Phantora and imported halls |
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

## Production checklist and backups

Before taking real customers, in this order:

1. **Secrets and config.** `JWT_SECRET`, `OTP_SECRET` (different), `EMAIL_MODE` other than `mock`, exact `CORS_ORIGINS`, real `DATABASE_URL`: the API refuses to start in production otherwise (`app/config.py`, tested). Set `TOTP_ENCRYPTION_KEY` once and never change it.
2. **Client addresses.** Deploy, then open `GET /api/admin/diagnostics/client-ip` as an owner and confirm `resolved_ip` is your own address, not the proxy's; adjust `CLIENT_IP_HEADER` if not. Rate limits depend on it.
3. **Two-step verification.** Have every operator enrol in the profile panel, then set `REQUIRE_OPERATOR_2FA=true`. Keep the recovery codes somewhere safe.
4. **Operators.** Give each cinema's staff a limited operator account from the Operatorlar tab; keep owners to the people who run the whole business.
5. **Payments.** The demo checkout moves no money. A real gateway needs an adapter in `app/payment_providers.py` (see **Payment providers**) and `PAYMENT_PROVIDER` plus `PAYMENT_WEBHOOK_SECRET`; do not enable `sandbox`.
6. **Monitoring.** Point the host's health check at `/health`, set `SENTRY_DSN`, and look at the JSON logs once after deploy.
7. **Backups (below), and a restore test.**

**Backups.** The database is the only state that matters (tickets, payments, accounts, the audit log); the app and frontend are rebuilt from the repository. Use the host's automated backups with point-in-time recovery if the plan has them (Render's paid Postgres plans do; the free plan does not keep backups and expires), and additionally take a logical dump on a schedule you control:

```
pg_dump --format=custom --no-owner --file=phantora-$(date +%F).dump "$DATABASE_URL"
```

Store dumps outside the database host, encrypted, and delete them on the retention you promise customers: they contain e-mail addresses and booking history, and deleted accounts reappear in old dumps. **A backup that was never restored is a hope, not a backup**: periodically restore the latest dump into a scratch database and check that the app starts against it:

```
createdb phantora_restore_check
pg_restore --no-owner --dbname=phantora_restore_check phantora-YYYY-MM-DD.dump
DATABASE_URL=postgresql+psycopg://.../phantora_restore_check python -m app.migrate     # reports the revision, applies anything newer
```

`python -m app.migrate` is also how a restored (older) dump is brought up to the current schema. The audit log is append-only by trigger, so a restore keeps it intact; the e-mail of a deleted account in it is already a tombstone.

## Known source limits

The public Cinematica feed currently provides cinema/hall labels, session time, price, and source identifiers. It does not provide verified street addresses, coordinates, physical capacities, cancellation state, or source seat counts. Phantora therefore does not invent those fields. Complete operator verification and a licensed payment provider remain required before taking real money.

## TMDB attribution

Movie metadata and artwork are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. See [TMDB API documentation](https://developer.themoviedb.org/docs).

## Architecture and AI use

The React client presents a read-only public catalog alongside Phantora-managed sessions. FastAPI proxies and caches discovery routes for five minutes. Phantora's PostgreSQL models are the source of truth for Phantora accounts, seats, holds, bookings, payments, and payment email challenges. TMDB remains a metadata/import source for the admin-managed catalog.

AI tools helped draft and revise UI, API/data-model scaffolding, and edge-case documentation. Review the implementation and provider behavior before production; verify real callbacks and concurrent seat reservations against staging data.
