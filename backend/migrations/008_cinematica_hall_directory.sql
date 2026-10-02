ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS source_name VARCHAR(40);
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS external_cinema_id BIGINT;
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS external_hall_id BIGINT;
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS source_url VARCHAR(800);
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS latitude NUMERIC(9, 6);
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS longitude NUMERIC(9, 6);
ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS uq_auditoriums_source_hall
  ON auditoriums(source_name, external_hall_id)
  WHERE source_name IS NOT NULL AND external_hall_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_auditoriums_coordinates
  ON auditoriums(latitude, longitude)
  WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
