ALTER TABLE users
    ADD COLUMN IF NOT EXISTS default_payment_term_days INTEGER NOT NULL DEFAULT 3
        CHECK (default_payment_term_days >= 0);
