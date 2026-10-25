ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS payment_method TEXT
        CHECK (payment_method IS NULL OR payment_method IN ('cash', 'bank_transfer')),
    ADD COLUMN IF NOT EXISTS paid_amount NUMERIC NOT NULL DEFAULT 0
        CHECK (paid_amount >= 0);
