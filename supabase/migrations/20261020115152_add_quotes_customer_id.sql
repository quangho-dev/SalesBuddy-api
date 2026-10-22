ALTER TABLE quotes
    ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE RESTRICT;

UPDATE quotes
SET customer_id = (
    SELECT customers.id
    FROM customers
    WHERE customers.clerk_id = quotes.clerk_id
    LIMIT 1
)
WHERE customer_id IS NULL;

DELETE FROM quotes
WHERE customer_id IS NULL;

ALTER TABLE quotes
    ALTER COLUMN customer_id SET NOT NULL;

CREATE INDEX quotes_customer_id_idx ON quotes (customer_id);
