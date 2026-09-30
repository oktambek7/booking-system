-- The legacy phone field belonged to the removed SMS checkout. Keep it nullable
-- for older deployments, and retain only non-sensitive receipt metadata.
ALTER TABLE payments ADD COLUMN IF NOT EXISTS card_last4 VARCHAR(4);
UPDATE payments SET card_last4 = phone_last4 WHERE card_last4 IS NULL;
ALTER TABLE payments ALTER COLUMN card_last4 SET NOT NULL;
ALTER TABLE payments ALTER COLUMN phone_last4 DROP NOT NULL;

CREATE TABLE IF NOT EXISTS payment_email_challenges (
  id SERIAL PRIMARY KEY,
  payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash VARCHAR(64) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_payment_email_challenges_payment_id ON payment_email_challenges (payment_id);
CREATE INDEX IF NOT EXISTS ix_payment_email_challenges_user_id ON payment_email_challenges (user_id);
CREATE INDEX IF NOT EXISTS ix_payment_email_challenges_expires_at ON payment_email_challenges (expires_at);
