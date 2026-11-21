ALTER TABLE quotes
    ADD COLUMN IF NOT EXISTS quote_code TEXT NOT NULL DEFAULT '';

UPDATE quotes
SET quote_code = numbered.code
FROM (
    SELECT id,
           'BG-' || lpad(row_number() OVER (
               PARTITION BY clerk_id
               ORDER BY created_at NULLS LAST, id
           )::text, 5, '0') AS code
    FROM quotes
) AS numbered
WHERE quotes.id = numbered.id
  AND btrim(quotes.quote_code) = '';

CREATE UNIQUE INDEX IF NOT EXISTS quotes_quote_code_unique_idx
    ON quotes (clerk_id, lower(btrim(quote_code)))
    WHERE btrim(quote_code) <> '';
