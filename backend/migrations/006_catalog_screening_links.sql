CREATE TABLE IF NOT EXISTS catalog_screening_links (
  source_repertory_id INTEGER PRIMARY KEY,
  screening_id INTEGER NOT NULL UNIQUE REFERENCES screenings(id) ON DELETE CASCADE,
  source_name VARCHAR(40) NOT NULL DEFAULT 'cinematica',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
