-- Run after the application tables exist. PostgreSQL atomically rejects overlapping
-- active bookings for the same provider, including concurrent insert transactions.
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE bookings
  ADD CONSTRAINT bookings_no_overlap
  EXCLUDE USING gist (
    provider_id WITH =,
    tstzrange(starts_at, ends_at, '[)') WITH &&
  )
  WHERE (status <> 'CANCELLED');
