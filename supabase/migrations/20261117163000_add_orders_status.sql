ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'official';

ALTER TABLE orders
    DROP CONSTRAINT IF EXISTS orders_status_check;

ALTER TABLE orders
    ADD CONSTRAINT orders_status_check
    CHECK (status IN ('official', 'cancelled', 'paused'));

UPDATE orders
SET status = 'official'
WHERE status IS NULL OR btrim(status) = '';
