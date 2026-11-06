CREATE UNIQUE INDEX IF NOT EXISTS products_clerk_product_code_unique_idx
    ON products (
        clerk_id,
        lower(regexp_replace(btrim(product_code), '\s+', ' ', 'g'))
    )
    WHERE btrim(product_code) <> '';
