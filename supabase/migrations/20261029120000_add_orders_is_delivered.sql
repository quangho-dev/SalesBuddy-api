ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS is_delivered BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS orders_is_delivered_idx ON orders (is_delivered);
