CREATE TABLE IF NOT EXISTS catalog_response_cache (
  cache_key VARCHAR(500) PRIMARY KEY,
  payload JSON NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  fresh_until TIMESTAMPTZ NOT NULL,
  stale_until TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_catalog_response_cache_fresh_until
  ON catalog_response_cache (fresh_until);

CREATE INDEX IF NOT EXISTS ix_catalog_response_cache_stale_until
  ON catalog_response_cache (stale_until);
