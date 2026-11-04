ALTER TABLE quotes
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'unset';

ALTER TABLE quotes
    DROP CONSTRAINT IF EXISTS quotes_status_check;

ALTER TABLE quotes
    ADD CONSTRAINT quotes_status_check
    CHECK (status IN ('converted', 'failed', 'unset'));

UPDATE quotes
SET status = CASE
    WHEN conversion_error <> '' THEN 'failed'
    WHEN converted_to_order
        OR EXISTS (
            SELECT 1
            FROM orders
            WHERE orders.quote_id = quotes.id
        ) THEN 'converted'
    ELSE 'unset'
END;
