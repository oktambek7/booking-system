<div align="center">

# PARDA

**Book a cinema seat in a few taps, without the queue and without the stress.**

[Open the live site](https://sana-booking.vercel.app/) · [Source code](https://github.com/oktambek7/parda-booking-system)

<img src="docs/screenshots/01-home.png" alt="Parda home page with the featured film carousel" width="900">

</div>

---

## Preview

| Film catalogue | Showtimes and filters |
| :---: | :---: |
| <img src="docs/screenshots/02-catalogue.png" alt="Catalogue of films now showing, with search and favourites" width="440"> | <img src="docs/screenshots/03-showtimes.png" alt="Film page with dates, cinema, hall type, format, language and sorting filters" width="440"> |

| Seat selection | Checkout |
| :---: | :---: |
| <img src="docs/screenshots/04-seat-map.png" alt="Live seat map with free, selected, taken and premium seats" width="440"> | <img src="docs/screenshots/05-checkout.png" alt="Checkout with order summary, hold timer, promo code, points and card form" width="220"> |

---

## 1. What is Parda?

Parda is a web app for booking cinema seats online. You find a film, pick a showtime, choose the exact seats on a live hall map, and confirm. Parda is built to make that path fast: fewer steps, less waiting, and less time spent on payment.

### Who it is for

- **Moviegoers** who want to pick their seats from a phone or laptop instead of standing in line at the box office.
- **Cinema companies** that want a modern, ready-to-run booking platform under their own name. Parda is built to be handed over to a cinema operator, and it includes a staff dashboard for halls, schedules, ticket check-in and daily revenue.

### How it works for a visitor

1. **Create a profile.** Register with an email, a nickname and a profile picture. A 4-digit code sent to that email confirms the account.
2. **Find a film.** Browse what is showing now or coming soon, search by title, and save films you want to watch.
3. **Pick a showtime.** Filter by date, cinema, hall type (Standard or VIP), format (2D, 3D, IMAX) and language, then sort by time or price.
4. **Choose seats.** The hall map shows which seats are free, taken or premium. Once you continue, your seats are held for you for 10 minutes.
5. **Pay.** Enter card details (Uzcard, Humo, Visa or Mastercard) and type in the 4-digit code Parda sends to your email.
6. **Get reminded.** Parda emails you twice before the film: **24 hours** before it starts and again **2 hours** before.

> **About payments:** payment is currently a demonstration. No real money is charged. The card form and email code show how the real flow will work. A licensed payment provider will be connected once Parda is handed over to a cinema company.

### Why choose Parda over other booking platforms

| Advantage | What it means for you |
| --- | --- |
| **Your seats are truly yours** | Seats are held on the server for 10 minutes while you pay, and the database makes sure two people can never buy the same seat. No "sorry, this seat is gone" at the last step. |
| **Fast checkout** | One short page: order summary, a visible hold timer, card details and a 4-digit email code. No redirects to other websites. |
| **Made for Uzbekistan** | Prices in UZS, times in Tashkent time, local cards (Uzcard, Humo) as well as Visa and Mastercard. The interface is available in Uzbek, Russian and English, in light or dark mode. |
| **You never miss the film** | Automatic email reminders 24 hours and 2 hours before the screening, plus a calendar file you can add to Google, Apple or Outlook calendar. |
| **Sold out? Get notified** | Join the waitlist for a full screening and receive an email if seats free up. Save a film and receive an email when its first showtime appears. |
| **Rewards** | Promo codes and Parda Points (1 point = 100 UZS, up to 50% of an order) make returning visits cheaper. |
| **Paperless entry** | Every ticket gets a QR e-ticket that staff scan once at the entrance. |
| **Clear at a glance** | The seat map uses labels and icons, not only colors, so it is easy to read for everyone. The full order summary is shown before you confirm. |

---

## 2. Technical tools

Parda is split into three clear parts: a **frontend** the user sees, a **backend API** that makes every decision, and a **database** that is the single source of truth. Each part has one job, which keeps the system predictable and easy to maintain.

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
| **Background workers** | Run on their own schedule inside the API: send reminders and alerts every minute, refresh showtimes every 10 minutes, refresh film details every 24 hours. |
| **Brevo** (Resend and SMTP also supported) | Delivers sign-up codes, payment codes, ticket confirmations and reminders by email. |
| **Docker + Render** | The API runs in a container, so it behaves the same on a laptop and in production. |

### Database (the single source of truth)

| Tool | Why it is used |
| --- | --- |
| **PostgreSQL 16** | Stores users, halls, seats, seat holds, bookings, payments and the reminder queue. |
| **Row locks and unique indexes** | When two people click the same seat at the same moment, only one booking succeeds. The other person is told immediately. |
| **Exclusion constraint on halls** | Two screenings can never be scheduled in the same hall at overlapping times. |
| **Durable notification queue** | Every reminder is recorded in the database, so a server restart cannot send it twice or lose it. |

### Data sources

| Source | What Parda takes from it |
| --- | --- |
| **Cinematica** | Films now showing and coming soon, posters, age ratings and showtimes. Read-only and cached, so a slow source never slows Parda down. |
| **TMDB** | Extra film details and artwork. Parda uses the TMDB API but is not endorsed or certified by TMDB. |

### How Parda avoids chaos

- **The server decides, not the browser.** Prices, seat availability and booking status are always calculated on the backend, so nobody can change a price or grab a taken seat from their browser.
- **Short seat holds.** A seat is reserved for 10 minutes during checkout. If payment is not finished, the seat is released automatically for other people.
- **No double booking.** The database itself blocks two active bookings for the same seat and the same screening.
- **Caching external data.** Showtimes from Cinematica are cached and refreshed in the background. If the source is briefly unavailable, Parda keeps working from the last good copy.
- **Reliable emails.** Reminders are queued in the database and sent by a background worker, so they go out on time and only once.
- **Card data is not kept.** Only the last four digits of the card are saved on the receipt. The full number, holder name, expiry and CVV are never stored, logged or emailed.

---

## 3. Architecture diagram

<p align="center">
  <img src="docs/architecture.svg" alt="Parda architecture: the moviegoer's browser talks to the React frontend on Vercel, which calls the FastAPI backend on Render. The backend reads films and showtimes from Cinematica and TMDB, stores everything in PostgreSQL, and sends emails through Brevo to the user's inbox." width="100%">
</p>

**How to read it:**

1. The **moviegoer** opens Parda in a browser. The **React frontend** on Vercel shows films, showtimes, the seat map and checkout.
2. Every action (sign in, hold seats, pay) is sent as a request to the **FastAPI backend** on Render.
3. The backend reads films and showtimes from **Cinematica** and film details from **TMDB**, and keeps a cached copy.
4. All accounts, seats, holds, bookings and reminders are stored in **PostgreSQL**, which prevents double booking.
5. The backend sends emails through **Brevo**: the 4-digit codes, the ticket confirmation and the reminders 24 hours and 2 hours before the film, straight to the user's **inbox**.
