ALTER TABLE users ADD COLUMN IF NOT EXISTS parda_points INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reserved_points INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS subtotal_price NUMERIC(12,2);
UPDATE bookings SET subtotal_price = total_price WHERE subtotal_price IS NULL;
ALTER TABLE bookings ALTER COLUMN subtotal_price SET NOT NULL;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS promotion_code VARCHAR(40);
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS promotion_discount NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS points_redeemed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS points_discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS points_earned INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS promotions (
  id SERIAL PRIMARY KEY,
  code VARCHAR(40) NOT NULL UNIQUE,
  label VARCHAR(120) NOT NULL,
  percent_off INTEGER NOT NULL CHECK (percent_off BETWEEN 1 AND 100),
  min_order_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  max_discount_amount NUMERIC(12,2),
  usage_limit INTEGER CHECK (usage_limit IS NULL OR usage_limit > 0),
  usage_count INTEGER NOT NULL DEFAULT 0,
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS promotion_redemptions (
  id SERIAL PRIMARY KEY,
  promotion_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE RESTRICT,
  booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
  customer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  discount_amount NUMERIC(12,2) NOT NULL,
  redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_promotion_redemptions_customer_id ON promotion_redemptions(customer_id);
