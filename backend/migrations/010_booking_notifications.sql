CREATE TABLE IF NOT EXISTS booking_notifications (
  id SERIAL PRIMARY KEY,
  booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  event_type VARCHAR(32) NOT NULL,
  due_at TIMESTAMPTZ NOT NULL,
  sent_at TIMESTAMPTZ,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error VARCHAR(300),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_booking_notification_event UNIQUE (booking_id, event_type)
);
CREATE INDEX IF NOT EXISTS ix_booking_notifications_due_at
  ON booking_notifications(due_at)
  WHERE sent_at IS NULL;
