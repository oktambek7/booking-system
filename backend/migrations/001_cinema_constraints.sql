-- Required Postgres constraints. Application startup installs the screening
-- exclusion constraint too; keep this migration for controlled production deploys.
CREATE EXTENSION IF NOT EXISTS btree_gist;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'screenings_no_overlap') THEN
    ALTER TABLE screenings ADD CONSTRAINT screenings_no_overlap
      EXCLUDE USING gist (
        auditorium_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
      ) WHERE (status = 'scheduled');
  END IF;
END $$;

-- Active seat assignments are unique within a screening. Cancelled/expired
-- bookings deactivate their assignments, preserving history while freeing seats.
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_screening_seat
  ON booking_seats (screening_id, seat_id) WHERE active IS TRUE;
