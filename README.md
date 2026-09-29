# Booking System

Mini appointment booking platform for a service business. Customers can browse services and providers, view available times, and manage bookings. Business staff can manage the catalog, availability, and appointments.

## Project progress

### Part 0 — Repository and project plan
- [x] Create project repository locally
- [x] Define implementation parts and completion checklist
- [ ] Publish public GitHub repository

### Part 1 — Backend API
- [ ] Choose and document architecture and database schema
- [ ] Authentication and role-based access (customer, admin/provider)
- [ ] Service and provider management endpoints
- [ ] Weekly availability and exception dates
- [ ] Availability search endpoint
- [ ] Booking creation, status transitions, cancellation, and history
- [ ] Validate input, ownership, business hours, and past dates
- [ ] Prevent overlapping bookings under concurrent requests
- [ ] API documentation

### Part 2 — Frontend booking experience
- [ ] Responsive service and provider discovery
- [ ] Date and available-time selection
- [ ] Sign-up/sign-in and booking confirmation
- [ ] Customer booking history and cancellation
- [ ] Loading, empty, validation, and error states

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

## Development

Setup instructions will be added with the backend and frontend stacks in their respective parts.

## Architecture

To be documented alongside Part 1 once the stack and persistence model are selected.

## AI assistance

AI assistance may be used during implementation. The final documentation will identify the assisted areas, explain the resulting code and design choices, and record how the implementation was reviewed.
