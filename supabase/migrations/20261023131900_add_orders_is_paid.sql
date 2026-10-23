ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS is_paid BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS orders_is_paid_idx ON orders (is_paid);
