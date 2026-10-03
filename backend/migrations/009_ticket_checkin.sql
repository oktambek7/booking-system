ALTER TABLE bookings ADD COLUMN IF NOT EXISTS ticket_code VARCHAR(16);
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_ticket_code
  ON bookings(ticket_code)
  WHERE ticket_code IS NOT NULL;
