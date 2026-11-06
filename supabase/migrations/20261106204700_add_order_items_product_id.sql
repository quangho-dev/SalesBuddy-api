ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS order_items_product_id_idx ON order_items (product_id);

UPDATE order_items AS item
SET product_id = matched.product_id
FROM (
    SELECT item.id AS item_id, MIN(product.id::text)::uuid AS product_id
    FROM order_items AS item
    JOIN orders ON orders.id = item.order_id
    JOIN products AS product
        ON product.clerk_id = orders.clerk_id
        AND lower(regexp_replace(btrim(product.name), '\s+', ' ', 'g'))
            = lower(regexp_replace(btrim(item.product_name), '\s+', ' ', 'g'))
    WHERE item.product_id IS NULL
        AND btrim(item.product_name) <> ''
    GROUP BY item.id
    HAVING COUNT(DISTINCT product.id) = 1
) AS matched
WHERE item.id = matched.item_id;
