ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS payment_term_days INTEGER NOT NULL DEFAULT 0
        CHECK (payment_term_days >= 0);
