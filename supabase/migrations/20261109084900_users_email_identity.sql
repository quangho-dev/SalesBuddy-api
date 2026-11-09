ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique_idx
    ON users (lower(btrim(email)))
    WHERE btrim(coalesce(email, '')) <> '';

-- clerk_id stays the auth key and the foreign key, but it can change when the
-- same email signs in from another Clerk environment. Owned rows follow it.
DO $$
DECLARE
    rec record;
BEGIN
    FOR rec IN
        SELECT
            nsp.nspname AS schema_name,
            rel.relname AS table_name,
            con.conname,
            (
                SELECT string_agg(quote_ident(att.attname), ', ' ORDER BY u.ord)
                FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord)
                JOIN pg_attribute att
                  ON att.attrelid = rel.oid
                 AND att.attnum = u.attnum
            ) AS columns
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class frel ON frel.oid = con.confrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        JOIN pg_namespace fnsp ON fnsp.oid = frel.relnamespace
        WHERE con.contype = 'f'
          AND nsp.nspname = 'public'
          AND fnsp.nspname = 'public'
          AND frel.relname = 'users'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I DROP CONSTRAINT %I',
            rec.schema_name,
            rec.table_name,
            rec.conname
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ADD CONSTRAINT %I FOREIGN KEY (%s) REFERENCES public.users (clerk_id) ON UPDATE CASCADE ON DELETE CASCADE',
            rec.schema_name,
            rec.table_name,
            rec.conname,
            rec.columns
        );
    END LOOP;
END $$;
