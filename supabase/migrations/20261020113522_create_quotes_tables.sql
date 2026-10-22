CREATE TABLE quotes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    notes TEXT NOT NULL DEFAULT '',
    subtotal NUMERIC NOT NULL DEFAULT 0,
    vat_total NUMERIC NOT NULL DEFAULT 0,
    grand_total NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX quotes_clerk_id_idx ON quotes (clerk_id);
CREATE INDEX quotes_created_at_idx ON quotes (created_at DESC);

CREATE TABLE quote_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id UUID NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    product_name TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    quantity NUMERIC NOT NULL DEFAULT 0,
    selling_price NUMERIC NOT NULL DEFAULT 0,
    vat_invoice BOOLEAN NOT NULL DEFAULT false,
    notes TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX quote_items_quote_id_idx ON quote_items (quote_id);
CREATE INDEX quote_items_sort_order_idx ON quote_items (quote_id, sort_order);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.quotes TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.quote_items TO service_role;
