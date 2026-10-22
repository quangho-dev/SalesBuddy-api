CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    quantity NUMERIC NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX order_items_order_id_idx ON order_items (order_id);
CREATE INDEX order_items_sort_order_idx ON order_items (order_id, sort_order);

INSERT INTO order_items (order_id, product_name, unit, quantity, notes, sort_order)
SELECT id, product_name, unit, quantity, notes, 0
FROM orders;

ALTER TABLE orders
    DROP COLUMN product_name,
    DROP COLUMN unit,
    DROP COLUMN quantity,
    DROP COLUMN notes;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.order_items TO service_role;
