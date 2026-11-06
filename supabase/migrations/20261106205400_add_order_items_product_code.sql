ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS product_code TEXT NOT NULL DEFAULT '';

UPDATE order_items AS item
SET product_code = btrim(product.product_code)
FROM products AS product
WHERE item.product_id = product.id
    AND btrim(item.product_code) = ''
    AND btrim(product.product_code) <> '';
