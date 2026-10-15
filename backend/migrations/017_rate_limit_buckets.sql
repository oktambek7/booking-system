CREATE TABLE IF NOT EXISTS rate_limit_buckets (
  key VARCHAR(160) PRIMARY KEY,
  window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_rate_limit_buckets_window ON rate_limit_buckets (window_start)
