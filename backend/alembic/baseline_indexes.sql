-- Frozen baseline schema for Alembic revision 0001: the models as they stood when Alembic was adopted.
-- Idempotent (IF NOT EXISTS), so it builds a fresh database and is a no-op on one a pre-Alembic release made.
-- Generated from SQLAlchemy metadata with CreateTable/CreateIndex; do NOT regenerate or edit. Later schema
-- changes belong in new Alembic revisions. Statements are separated by a marker line (see app/legacy_schema.py).
CREATE INDEX IF NOT EXISTS ix_auditoriums_external_cinema_id ON auditoriums (external_cinema_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_auditoriums_external_hall_id ON auditoriums (external_hall_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_catalog_response_cache_fresh_until ON catalog_response_cache (fresh_until)
-- ;;
CREATE INDEX IF NOT EXISTS ix_catalog_response_cache_stale_until ON catalog_response_cache (stale_until)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movies_cinematica_id ON movies (cinematica_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movies_title ON movies (title)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_movies_tmdb_id ON movies (tmdb_id)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_promotions_code ON promotions (code)
-- ;;
CREATE INDEX IF NOT EXISTS ix_rate_limit_buckets_window_start ON rate_limit_buckets (window_start)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_nickname ON users (nickname)
-- ;;
CREATE INDEX IF NOT EXISTS ix_email_otp_challenges_expires_at ON email_otp_challenges (expires_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_email_otp_challenges_user_id ON email_otp_challenges (user_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movie_watchlists_movie_id ON movie_watchlists (movie_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movie_watchlists_user_id ON movie_watchlists (user_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_password_reset_challenges_expires_at ON password_reset_challenges (expires_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_password_reset_challenges_user_id ON password_reset_challenges (user_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_screenings_auditorium_id ON screenings (auditorium_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_screenings_movie_id ON screenings (movie_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_screenings_starts_at ON screenings (starts_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_seats_auditorium_id ON seats (auditorium_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_bookings_customer_id ON bookings (customer_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_bookings_hold_expires_at ON bookings (hold_expires_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_bookings_screening_id ON bookings (screening_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_bookings_status ON bookings (status)
-- ;;
CREATE INDEX IF NOT EXISTS ix_bookings_ticket_code ON bookings (ticket_code)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_catalog_screening_links_screening_id ON catalog_screening_links (screening_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movie_watchlist_notifications_due_at ON movie_watchlist_notifications (due_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movie_watchlist_notifications_screening_id ON movie_watchlist_notifications (screening_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_movie_watchlist_notifications_watchlist_id ON movie_watchlist_notifications (watchlist_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_screening_waitlist_screening_id ON screening_waitlist (screening_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_screening_waitlist_status ON screening_waitlist (status)
-- ;;
CREATE INDEX IF NOT EXISTS ix_screening_waitlist_user_id ON screening_waitlist (user_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_booking_notifications_booking_id ON booking_notifications (booking_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_booking_notifications_due_at ON booking_notifications (due_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_booking_seats_booking_id ON booking_seats (booking_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_booking_seats_screening_id ON booking_seats (screening_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_booking_seats_seat_id ON booking_seats (seat_id)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_screening_seat ON booking_seats (screening_id, seat_id) WHERE active IS TRUE
-- ;;
CREATE INDEX IF NOT EXISTS ix_payments_booking_id ON payments (booking_id)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_reference ON payments (reference)
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_payment_per_booking ON payments (booking_id) WHERE status = 'awaiting_verification'
-- ;;
CREATE UNIQUE INDEX IF NOT EXISTS ix_promotion_redemptions_booking_id ON promotion_redemptions (booking_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_promotion_redemptions_customer_id ON promotion_redemptions (customer_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_promotion_redemptions_promotion_id ON promotion_redemptions (promotion_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_waitlist_notifications_due_at ON waitlist_notifications (due_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_waitlist_notifications_waitlist_entry_id ON waitlist_notifications (waitlist_entry_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_otp_challenges_expires_at ON otp_challenges (expires_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_otp_challenges_payment_id ON otp_challenges (payment_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_otp_challenges_user_id ON otp_challenges (user_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_payment_email_challenges_expires_at ON payment_email_challenges (expires_at)
-- ;;
CREATE INDEX IF NOT EXISTS ix_payment_email_challenges_payment_id ON payment_email_challenges (payment_id)
-- ;;
CREATE INDEX IF NOT EXISTS ix_payment_email_challenges_user_id ON payment_email_challenges (user_id)
