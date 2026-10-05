ALTER TABLE movies ADD COLUMN IF NOT EXISTS cinematica_id INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_movies_cinematica_id ON movies(cinematica_id) WHERE cinematica_id IS NOT NULL;
