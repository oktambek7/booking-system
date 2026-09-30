ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS hall_type VARCHAR(12) NOT NULL DEFAULT 'standard';

CREATE TABLE IF NOT EXISTS email_otp_challenges (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash VARCHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_email_otp_challenges_user_id ON email_otp_challenges (user_id);
CREATE INDEX IF NOT EXISTS ix_email_otp_challenges_expires_at ON email_otp_challenges (expires_at);
