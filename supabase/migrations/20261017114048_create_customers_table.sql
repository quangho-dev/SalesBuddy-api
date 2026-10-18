CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    company_name TEXT NOT NULL DEFAULT '',
    contact_person TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    phone_number TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    facebook TEXT NOT NULL DEFAULT '',
    zalo TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    interaction_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX customers_clerk_id_idx ON customers (clerk_id);
CREATE INDEX customers_created_at_idx ON customers (created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.customers TO service_role;
