-- Frozen baseline schema for Alembic revision 0001: the models as they stood when Alembic was adopted.
-- Idempotent (IF NOT EXISTS), so it builds a fresh database and is a no-op on one a pre-Alembic release made.
-- Generated from SQLAlchemy metadata with CreateTable/CreateIndex; do NOT regenerate or edit. Later schema
-- changes belong in new Alembic revisions. Statements are separated by a marker line (see app/legacy_schema.py).
-- Types and tables. Indexes live in baseline_indexes.sql and run after the legacy column additions.
DO $$ BEGIN CREATE TYPE bookingstatus AS ENUM ('PENDING', 'CONFIRMED', 'CANCELLED', 'COMPLETED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$
-- ;;
DO $$ BEGIN CREATE TYPE role AS ENUM ('CUSTOMER', 'ADMIN'); EXCEPTION WHEN duplicate_object THEN NULL; END $$
-- ;;
CREATE TABLE IF NOT EXISTS auditoriums (
	id SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	cinema_name VARCHAR(140) NOT NULL, 
	city VARCHAR(100) NOT NULL, 
	address VARCHAR(300) NOT NULL, 
	timezone VARCHAR(64) NOT NULL, 
	formats JSON NOT NULL, 
	hall_type VARCHAR(12) NOT NULL, 
	active BOOLEAN NOT NULL, 
	source_name VARCHAR(40), 
	external_cinema_id BIGINT, 
	external_hall_id BIGINT, 
	source_url VARCHAR(800), 
	latitude NUMERIC(9, 6), 
	longitude NUMERIC(9, 6), 
	last_synced_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)
-- ;;
CREATE TABLE IF NOT EXISTS catalog_response_cache (
	cache_key VARCHAR(500) NOT NULL, 
	payload JSON NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	fresh_until TIMESTAMP WITH TIME ZONE NOT NULL, 
	stale_until TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (cache_key)
)
-- ;;
CREATE TABLE IF NOT EXISTS movies (
	id SERIAL NOT NULL, 
	title VARCHAR(180) NOT NULL, 
	synopsis TEXT NOT NULL, 
	duration_minutes INTEGER, 
	genre VARCHAR(100) NOT NULL, 
	age_rating VARCHAR(12) NOT NULL, 
	language VARCHAR(60) NOT NULL, 
	poster_url VARCHAR(800) NOT NULL, 
	backdrop_url VARCHAR(800) NOT NULL, 
	tmdb_id INTEGER, 
	cinematica_id INTEGER, 
	release_date DATE, 
	vote_average NUMERIC(3, 1), 
	cast_names JSON NOT NULL, 
	trailer_key VARCHAR(100), 
	catalog_status VARCHAR(20) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_movie_duration_positive CHECK (duration_minutes IS NULL OR duration_minutes > 0)
)
-- ;;
CREATE TABLE IF NOT EXISTS promotions (
	id SERIAL NOT NULL, 
	code VARCHAR(40) NOT NULL, 
	label VARCHAR(120) NOT NULL, 
	percent_off INTEGER NOT NULL, 
	min_order_amount NUMERIC(12, 2) NOT NULL, 
	max_discount_amount NUMERIC(12, 2), 
	usage_limit INTEGER, 
	usage_count INTEGER NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_promotions_percent_off CHECK (percent_off BETWEEN 1 AND 100), 
	CONSTRAINT ck_promotions_usage_limit CHECK (usage_limit IS NULL OR usage_limit > 0)
)
-- ;;
CREATE TABLE IF NOT EXISTS rate_limit_buckets (
	key VARCHAR(160) NOT NULL, 
	window_start TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	hits INTEGER NOT NULL, 
	PRIMARY KEY (key)
)
-- ;;
CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	nickname VARCHAR(40) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role role NOT NULL, 
	active BOOLEAN NOT NULL, 
	phone VARCHAR(20), 
	phone_verified BOOLEAN NOT NULL, 
	email_verified BOOLEAN NOT NULL, 
	avatar_data TEXT, 
	parda_points INTEGER NOT NULL, 
	reserved_points INTEGER NOT NULL, 
	token_version INTEGER DEFAULT 0 NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
)
-- ;;
CREATE TABLE IF NOT EXISTS email_otp_challenges (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	code_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS movie_watchlists (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	movie_id INTEGER NOT NULL, 
	alert_sent_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_movie_watchlist_user_movie UNIQUE (user_id, movie_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(movie_id) REFERENCES movies (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS password_reset_challenges (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	code_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS screenings (
	id SERIAL NOT NULL, 
	movie_id INTEGER NOT NULL, 
	auditorium_id INTEGER NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	base_price NUMERIC(12, 2) NOT NULL, 
	premium_surcharge NUMERIC(12, 2) NOT NULL, 
	format_type VARCHAR(8) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_screening_time_range CHECK (starts_at < ends_at), 
	CONSTRAINT ck_screening_price_nonnegative CHECK (base_price >= 0 AND premium_surcharge >= 0), 
	FOREIGN KEY(movie_id) REFERENCES movies (id), 
	FOREIGN KEY(auditorium_id) REFERENCES auditoriums (id)
)
-- ;;
CREATE TABLE IF NOT EXISTS seats (
	id SERIAL NOT NULL, 
	auditorium_id INTEGER NOT NULL, 
	row_label VARCHAR(5) NOT NULL, 
	seat_number INTEGER NOT NULL, 
	seat_type VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_auditorium_seat UNIQUE (auditorium_id, row_label, seat_number), 
	CONSTRAINT ck_seat_number_positive CHECK (seat_number > 0), 
	FOREIGN KEY(auditorium_id) REFERENCES auditoriums (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS bookings (
	id SERIAL NOT NULL, 
	customer_id INTEGER NOT NULL, 
	screening_id INTEGER NOT NULL, 
	status bookingstatus NOT NULL, 
	seat_count INTEGER NOT NULL, 
	total_price NUMERIC(12, 2) NOT NULL, 
	subtotal_price NUMERIC(12, 2) NOT NULL, 
	promotion_code VARCHAR(40), 
	promotion_discount NUMERIC(12, 2) NOT NULL, 
	points_redeemed INTEGER NOT NULL, 
	points_discount_amount NUMERIC(12, 2) NOT NULL, 
	points_earned INTEGER NOT NULL, 
	hold_expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	archived_by_customer BOOLEAN NOT NULL, 
	ticket_code VARCHAR(16), 
	checked_in_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(customer_id) REFERENCES users (id), 
	FOREIGN KEY(screening_id) REFERENCES screenings (id)
)
-- ;;
CREATE TABLE IF NOT EXISTS catalog_screening_links (
	source_repertory_id SERIAL NOT NULL, 
	screening_id INTEGER NOT NULL, 
	source_name VARCHAR(40) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (source_repertory_id), 
	FOREIGN KEY(screening_id) REFERENCES screenings (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS movie_watchlist_notifications (
	id SERIAL NOT NULL, 
	watchlist_id INTEGER NOT NULL, 
	screening_id INTEGER NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	attempts INTEGER NOT NULL, 
	last_error VARCHAR(300), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_movie_watchlist_first_notice UNIQUE (watchlist_id), 
	FOREIGN KEY(watchlist_id) REFERENCES movie_watchlists (id) ON DELETE CASCADE, 
	FOREIGN KEY(screening_id) REFERENCES screenings (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS screening_waitlist (
	id SERIAL NOT NULL, 
	screening_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	seat_count INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_waitlist_screening_user UNIQUE (screening_id, user_id), 
	CONSTRAINT ck_waitlist_seat_count CHECK (seat_count BETWEEN 1 AND 8), 
	FOREIGN KEY(screening_id) REFERENCES screenings (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS booking_notifications (
	id SERIAL NOT NULL, 
	booking_id INTEGER NOT NULL, 
	event_type VARCHAR(32) NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	attempts INTEGER NOT NULL, 
	last_error VARCHAR(300), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_booking_notification_event UNIQUE (booking_id, event_type), 
	FOREIGN KEY(booking_id) REFERENCES bookings (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS booking_seats (
	id SERIAL NOT NULL, 
	booking_id INTEGER NOT NULL, 
	screening_id INTEGER NOT NULL, 
	seat_id INTEGER NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(booking_id) REFERENCES bookings (id) ON DELETE CASCADE, 
	FOREIGN KEY(screening_id) REFERENCES screenings (id), 
	FOREIGN KEY(seat_id) REFERENCES seats (id)
)
-- ;;
CREATE TABLE IF NOT EXISTS payments (
	id SERIAL NOT NULL, 
	booking_id INTEGER NOT NULL, 
	reference VARCHAR(40) NOT NULL, 
	method VARCHAR(20) NOT NULL, 
	card_last4 VARCHAR(4) NOT NULL, 
	phone_last4 VARCHAR(4), 
	amount NUMERIC(12, 2) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	provider VARCHAR(24) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(booking_id) REFERENCES bookings (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS promotion_redemptions (
	id SERIAL NOT NULL, 
	promotion_id INTEGER NOT NULL, 
	booking_id INTEGER NOT NULL, 
	customer_id INTEGER NOT NULL, 
	discount_amount NUMERIC(12, 2) NOT NULL, 
	redeemed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(promotion_id) REFERENCES promotions (id) ON DELETE RESTRICT, 
	FOREIGN KEY(booking_id) REFERENCES bookings (id) ON DELETE CASCADE, 
	FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS waitlist_notifications (
	id SERIAL NOT NULL, 
	waitlist_entry_id INTEGER NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	attempts INTEGER NOT NULL, 
	last_error VARCHAR(300), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_waitlist_availability_notice UNIQUE (waitlist_entry_id), 
	FOREIGN KEY(waitlist_entry_id) REFERENCES screening_waitlist (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS otp_challenges (
	id SERIAL NOT NULL, 
	payment_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	phone VARCHAR(20) NOT NULL, 
	code_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
-- ;;
CREATE TABLE IF NOT EXISTS payment_email_challenges (
	id SERIAL NOT NULL, 
	payment_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	code_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
