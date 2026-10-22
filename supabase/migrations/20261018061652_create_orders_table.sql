CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    product_name TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    quantity NUMERIC NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    vat_invoice BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX orders_clerk_id_idx ON orders (clerk_id);
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
CREATE INDEX orders_order_date_idx ON orders (order_date DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.orders TO service_role;
