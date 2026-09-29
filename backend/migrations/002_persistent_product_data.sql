-- Additive migration for persistent accounts, current catalog fields, and screening formats.
ALTER TABLE users ADD COLUMN IF NOT EXISTS nickname VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE users SET nickname = LOWER(REGEXP_REPLACE(COALESCE(NULLIF(name, ''), 'guest'), '[^A-Za-z0-9_.-]', '', 'g')) || '-' || id
WHERE nickname IS NULL OR nickname = '';
ALTER TABLE users ALTER COLUMN nickname SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_nickname ON users (nickname);

ALTER TABLE movies ADD COLUMN IF NOT EXISTS backdrop_url VARCHAR(800) NOT NULL DEFAULT '';
ALTER TABLE movies ADD COLUMN IF NOT EXISTS tmdb_id INTEGER;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS release_date DATE;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS vote_average NUMERIC(3,1);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS cast_names JSON NOT NULL DEFAULT '[]';
ALTER TABLE movies ADD COLUMN IF NOT EXISTS trailer_key VARCHAR(100);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS catalog_status VARCHAR(20) NOT NULL DEFAULT 'now_playing';
ALTER TABLE movies ALTER COLUMN duration_minutes DROP NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ix_movies_tmdb_id ON movies (tmdb_id);

ALTER TABLE auditoriums ADD COLUMN IF NOT EXISTS formats JSON NOT NULL DEFAULT '["2D"]';
ALTER TABLE screenings ADD COLUMN IF NOT EXISTS format_type VARCHAR(8) NOT NULL DEFAULT '2D';

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_screening_seat
  ON booking_seats (screening_id, seat_id) WHERE active IS TRUE;
