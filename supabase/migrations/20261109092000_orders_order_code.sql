ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS order_code TEXT NOT NULL DEFAULT '';

WITH numbered AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY clerk_id
            ORDER BY created_at, id
        ) AS sequence_number
    FROM orders
    WHERE btrim(order_code) = ''
)
UPDATE orders
SET order_code = 'DH-' || lpad(numbered.sequence_number::text, 5, '0')
FROM numbered
WHERE orders.id = numbered.id;

CREATE UNIQUE INDEX IF NOT EXISTS orders_clerk_order_code_unique_idx
    ON orders (clerk_id, lower(btrim(order_code)))
    WHERE btrim(order_code) <> '';
