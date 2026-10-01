CREATE TABLE IF NOT EXISTS password_reset_challenges (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash VARCHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_password_reset_challenges_user_id ON password_reset_challenges(user_id);
CREATE INDEX IF NOT EXISTS ix_password_reset_challenges_expires_at ON password_reset_challenges(expires_at);
