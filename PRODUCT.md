# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: React/Vite client, FastAPI REST API, PostgreSQL persistence, and Vercel static hosting were already established in this repository.

## Users

Moviegoers use a phone or desktop to find a film, compare screening times, choose exact seats, and keep their tickets. Cinema administrators maintain the film catalogue, halls, screenings, and bookings.

## Product Purpose

Let a moviegoer reserve a small group of seats for a specific screening with a clear, low-friction flow. Success means the viewer can tell what film, time, hall, seats, and total price they are confirming before the seats are held.

## Positioning

The core mechanism is a live seat map backed by short server-side seat holds, so the selected seat is protected from another customer while the booking is confirmed.

## Operating Context

This is a web app for cinemas in Uzbekistan. The default interface is Uzbek, prices are UZS, and screening times display in Asia/Tashkent. Customers can register or sign in, select up to eight seats, review a booking, and see booking history. Cinema staff use admin access to manage content and schedules.

## Capabilities and Constraints

- Films have runtime, genre, age rating, language, synopsis, and poster.
- Screenings belong to a film and an auditorium and have a start time and per-seat price.
- Seats have stable row/number labels and may carry a price category.
- One seat can have only one active assignment for a screening. Pending holds expire after ten minutes.
- Booking status values are pending, confirmed, cancelled, and completed. Cancelling or expiring releases seats while preserving booking history.
- This project has no connected payment processor. Demo confirmation must not imply a real charge.
- Sample film titles and screenings are fictional demo content, not a live cinema catalogue.
- “Parda Cinema” is a fictional demo label; no production cinema chain or catalogue was supplied.
- The payment provider is undecided and intentionally absent from demo checkout.

## Evidence on Hand

The user supplied the booking-system requirements and asked for a cinema seat-booking adaptation. There are no licensed film posters, cinema contracts, payment credentials, or production catalogue supplied. Illustrative sample imagery and data must be identified as demo content.

## Product Principles

- Show the full booking summary before the customer confirms.
- Keep seat status visible and understandable at a glance.
- Recheck seats on the server at confirmation; the seat map alone is not a reservation.
- Preserve customer booking history when a hold expires or a booking is cancelled.

## Accessibility & Inclusion

Seat state must use labels in addition to color. Seat controls are keyboard reachable, have accessible names, and distinguish selected, available, premium, and unavailable states.
