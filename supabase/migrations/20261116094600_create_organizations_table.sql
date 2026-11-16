CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON UPDATE CASCADE ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    tax_code TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX organizations_clerk_id_idx ON organizations (clerk_id);
CREATE INDEX organizations_created_at_idx ON organizations (created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.organizations TO service_role;
