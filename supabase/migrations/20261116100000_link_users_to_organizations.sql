ALTER TABLE organizations
    DROP COLUMN IF EXISTS clerk_id;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS organization_id UUID;

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_organization_id_fkey;

ALTER TABLE users
    ADD CONSTRAINT users_organization_id_fkey
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS users_organization_id_idx ON users (organization_id);
