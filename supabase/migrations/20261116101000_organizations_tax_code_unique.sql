CREATE UNIQUE INDEX IF NOT EXISTS organizations_tax_code_unique_idx
    ON organizations (lower(regexp_replace(btrim(tax_code), '\s+', '', 'g')))
    WHERE btrim(tax_code) <> '';
