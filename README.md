# Parda Cinema

An Uzbek-first cinema discovery and seat-booking demo. Visitors browse TMDB movie and cast details, choose a Tashkent screening, select seats, and place a ten-minute hold before completing a clearly labeled no-charge payment simulation. The Vite/React frontend uses a FastAPI backend and hosted PostgreSQL. Prices are in UZS; showtimes use Asia/Tashkent.

**Live demo:** https://sana-booking.vercel.app/  
**API and interactive docs:** https://parda-cinema-api.onrender.com/docs  
**Source:** https://github.com/oktambek7/booking-system

> Portfolio/demo only. SMS verification is in mock mode and displays the demo OTP in the checkout page. Payment methods are simulated; no card number or CVV is requested and no money is collected. A real SMS gateway and payment provider are not connected.

## Delivery checklist

### Product and API
- [x] Public GitHub repository and public Vercel demo
- [x] Registration with unique nickname/email, password hashing, and bearer authentication
- [x] TMDB current and upcoming catalog with posters, cast, ratings, release dates, and trailers
- [x] Cinema/hall administration, seat layout, showtimes, and 2D/3D/IMAX formats
- [x] Date-based Tashkent showtimes, live seat availability, premium pricing, and responsive seat selection
- [x] Ten-minute pending holds, cancellation, booking history, and pending/confirmed/cancelled/completed statuses
- [x] Hosted PostgreSQL persistence for users, screenings, seat holds/bookings, and payment/OTP attempts
- [x] Four-digit demo SMS OTP flow with expiry and attempt limits
- [x] Uzcard, Humo, Visa, and Mastercard demo choices; no charge is made
- [x] Admin tools for TMDB sync, cinema/halls, schedules, and booking status management
- [x] Light/dark theme, API documentation, and setup instructions
- [x] Render API and Vercel frontend configured; public catalog and seat map loaded from the hosted API
- [ ] Configure and verify a real SMS gateway before sending real OTP messages
- [ ] Connect a payment provider before accepting real payments

### Current hosted demo data
- [x] TMDB token is configured on the API server; movie catalog is synced into PostgreSQL
- [x] Demo cinema, 80-seat hall, and Oct 1, 2026 screenings published in 2D, 3D, and IMAX
- [x] Public visitor page shows screening times and the live seat map
- [ ] Verify full customer checkout with a newly registered visitor account

## Run locally

Requires Python 3.12+, Node.js, and Docker Desktop.

```sh
docker compose up --build
```

The API runs at http://localhost:8000 and its docs at http://localhost:8000/docs. Copy backend/.env.example to backend/.env and set strong random JWT_SECRET and OTP_SECRET values. In another terminal:

```sh
cd frontend
npm install
```

Create frontend/.env.local with VITE_API_URL=http://localhost:8000, then run npm run dev. Run npm run build to create the frontend production bundle.

Create a local admin account with:

```sh
docker compose exec -e ADMIN_EMAIL=admin@example.com -e ADMIN_PASSWORD='use-a-long-unique-password' api python -m app.bootstrap_admin
```

The default SMS_MODE=mock shows the four-digit OTP in the checkout response/UI for development. To send real messages, configure the supported SMS gateway credentials and set SMS_MODE=eskiz. TMDB and SMS credentials belong only in server-side environment variables; never commit them.

## Hosted setup

1. Create a managed PostgreSQL database and keep its connection URL private.
2. Deploy the API from render.yaml. Configure DATABASE_URL, TMDB_READ_TOKEN, CORS_ORIGINS, and SMS settings in the Render service environment. Keep JWT_SECRET and OTP_SECRET strong and private.
3. For the portfolio demo, set SMS_MODE=mock. Configure an approved SMS sender and credentials before changing it to a real gateway mode.
4. Set Vercel VITE_API_URL to the API origin and allow the exact Vercel origin in CORS_ORIGINS.
5. Bootstrap an administrator, create the cinema/hall and seat plan, publish screening schedules, then sync the TMDB catalog from the admin interface.

The free Render instance may sleep between visits, so the first API request can take longer while it wakes. Its data remains in PostgreSQL.

## Architecture and booking safeguards

- PostgreSQL stores accounts, films, cinemas, auditoriums, seat inventory, screenings, bookings, seat assignments, and payment/OTP attempt records. Passwords are hashed; OTP values are stored as HMAC digests with expiry and attempt limits.
- FastAPI validates requests and derives ticket prices from the screening and seat type. The browser cannot set a booking's final price or another user's booking status.
- Booking checks current seat availability and holds chosen seats for ten minutes. PostgreSQL row locks and a partial unique constraint on active (screening, seat) assignments prevent two concurrent users from holding the same seat. A conflict returns HTTP 409 so the client can refresh the seat map.
- A hall time-range constraint prevents overlapping screenings. Expired/cancelled holds release seats while preserving booking history. Invalid, duplicate, foreign, or excessive seat selections and invalid status transitions are rejected.
- The payment step is explicitly simulated. An OTP-confirmed booking is marked successful in demo mode; this is not evidence that funds were transferred.
- A film with no known runtime cannot be scheduled until its duration is supplied; the system does not guess an end time.

## Original brief mapped to cinema

| Booking brief | Cinema implementation |
| --- | --- |
| Services and price/duration | Films and priced screenings with runtime |
| Providers/employees | Cinemas and auditoriums |
| Availability | Screening times, hall formats, and seat inventory |
| View available times | Date-filtered showtimes in Asia/Tashkent |
| Make a booking | Authenticated seat hold followed by OTP confirmation |
| Booking statuses/history | Pending, confirmed, cancelled, completed, with customer history |
| Prevent double booking | Database locks and unique active seat assignments |
| Backend API and authentication | FastAPI, JWT authentication, validation, PostgreSQL |

## TMDB attribution

Movie metadata and artwork are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. See https://www.themoviedb.org/ and https://developer.themoviedb.org/docs.

## AI assistance

AI tools helped draft and revise API/data-model scaffolding, UI copy, integration code, and edge-case documentation. The implementation uses database constraints and server-side validation for booking correctness. Before using this as a commercial service, connect a real SMS provider and payment processor, exercise checkout and concurrent booking on staging, and review operational/security requirements.
