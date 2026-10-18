CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    product_code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    product_type TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    selling_price NUMERIC NOT NULL DEFAULT 0,
    stock NUMERIC NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX products_clerk_id_idx ON products (clerk_id);
CREATE INDEX products_created_at_idx ON products (created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.products TO service_role;
