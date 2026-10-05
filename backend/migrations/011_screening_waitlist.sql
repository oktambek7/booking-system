CREATE TABLE IF NOT EXISTS screening_waitlist (
  id SERIAL PRIMARY KEY,
  screening_id INTEGER NOT NULL REFERENCES screenings(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  seat_count INTEGER NOT NULL DEFAULT 1 CHECK (seat_count BETWEEN 1 AND 8),
  status VARCHAR(20) NOT NULL DEFAULT 'waiting',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_waitlist_screening_user UNIQUE (screening_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_waitlist_waiting ON screening_waitlist (screening_id) WHERE status = 'waiting';

CREATE TABLE IF NOT EXISTS waitlist_notifications (
  id SERIAL PRIMARY KEY,
  waitlist_entry_id INTEGER NOT NULL REFERENCES screening_waitlist(id) ON DELETE CASCADE,
  due_at TIMESTAMPTZ NOT NULL,
  sent_at TIMESTAMPTZ,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error VARCHAR(300),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_waitlist_availability_notice UNIQUE (waitlist_entry_id)
);
CREATE INDEX IF NOT EXISTS ix_waitlist_notifications_due ON waitlist_notifications (due_at) WHERE sent_at IS NULL;
