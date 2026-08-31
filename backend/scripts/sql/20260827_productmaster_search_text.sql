-- SUPERSEDED by 20260829_productmaster_generated_search_columns.sql, which
-- converts search_text into a GENERATED ALWAYS ... STORED column so it can
-- never go stale. Kept here for history; do not run this after that script
-- has been applied -- ALTER COLUMN on a generated column will error.
--
-- productmaster search_text for trigram candidate retrieval.
-- Does not modify Productcode, name, description, or description2 values.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE productmaster
    ADD COLUMN IF NOT EXISTS search_text TEXT;

UPDATE productmaster
SET search_text = lower(
    concat_ws(
        ' ',
        CAST("Productcode" AS TEXT),
        name,
        description,
        description2
    )
)
WHERE search_text IS NULL
   OR search_text IS DISTINCT FROM lower(
        concat_ws(
            ' ',
            CAST("Productcode" AS TEXT),
            name,
            description,
            description2
        )
    );

CREATE INDEX IF NOT EXISTS idx_productmaster_search_text_trgm
    ON productmaster
    USING gin (search_text gin_trgm_ops);
