ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS quote_id UUID REFERENCES quotes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS orders_quote_id_idx ON orders (quote_id);
