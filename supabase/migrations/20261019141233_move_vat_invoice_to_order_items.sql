ALTER TABLE order_items
    ADD COLUMN vat_invoice BOOLEAN NOT NULL DEFAULT false;

UPDATE order_items AS items
SET vat_invoice = orders.vat_invoice
FROM orders
WHERE items.order_id = orders.id;

ALTER TABLE orders
    DROP COLUMN vat_invoice;
