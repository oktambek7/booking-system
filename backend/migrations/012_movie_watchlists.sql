CREATE TABLE IF NOT EXISTS movie_watchlists (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
  alert_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_movie_watchlist_user_movie UNIQUE (user_id, movie_id)
);
CREATE INDEX IF NOT EXISTS ix_movie_watchlists_pending_alert ON movie_watchlists (movie_id) WHERE alert_sent_at IS NULL;

CREATE TABLE IF NOT EXISTS movie_watchlist_notifications (
  id SERIAL PRIMARY KEY,
  watchlist_id INTEGER NOT NULL REFERENCES movie_watchlists(id) ON DELETE CASCADE,
  screening_id INTEGER NOT NULL REFERENCES screenings(id) ON DELETE CASCADE,
  due_at TIMESTAMPTZ NOT NULL,
  sent_at TIMESTAMPTZ,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error VARCHAR(300),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_movie_watchlist_first_notice UNIQUE (watchlist_id)
);
CREATE INDEX IF NOT EXISTS ix_movie_watchlist_notifications_due ON movie_watchlist_notifications (due_at) WHERE sent_at IS NULL;
