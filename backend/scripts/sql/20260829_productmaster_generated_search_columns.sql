-- Convert productmaster.search_text / identifier_search from plain backfilled
-- columns into GENERATED ALWAYS ... STORED columns, so Postgres recomputes
-- them automatically on every insert/update. Supersedes the manual backfill
-- scripts 20260827_productmaster_search_text.sql and
-- 20260827_productmaster_identifier_search.sql -- once this has been run,
-- those two scripts are no longer needed (and will error if run again,
-- since a generated column cannot be set directly).
--
-- Safe to run more than once: DROP ... IF EXISTS / ADD COLUMN are idempotent
-- as a pair, though re-running still pays the cost of a full column rebuild.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP INDEX IF EXISTS idx_productmaster_search_text_trgm;
DROP INDEX IF EXISTS idx_productmaster_identifier_search_trgm;
ALTER TABLE productmaster DROP COLUMN IF EXISTS search_text;
ALTER TABLE productmaster DROP COLUMN IF EXISTS identifier_search;

-- concat_ws() is STABLE, not IMMUTABLE (it takes a polymorphic VARIADIC
-- "any" argument), so it can't be used inside a GENERATED column expression
-- ("generation expression is not immutable"). These rewrites use only
-- immutable primitives (||, CASE, coalesce) and were verified to produce
-- byte-identical values to the original concat_ws-based columns across all
-- existing rows before this script was applied.

ALTER TABLE productmaster
    ADD COLUMN search_text TEXT GENERATED ALWAYS AS (
        lower(
            CAST("Productcode" AS TEXT)
            || CASE WHEN name IS NOT NULL THEN ' ' || name ELSE '' END
            || CASE WHEN description IS NOT NULL THEN ' ' || description ELSE '' END
            || CASE WHEN description2 IS NOT NULL THEN ' ' || description2 ELSE '' END
        )
    ) STORED;

ALTER TABLE productmaster
    ADD COLUMN identifier_search TEXT GENERATED ALWAYS AS (
        lower(
            replace(
                replace(
                    replace(
                        CAST("Productcode" AS TEXT)
                        || coalesce(name, '')
                        || coalesce(description, '')
                        || coalesce(description2, ''),
                        ' ',
                        ''
                    ),
                    '-',
                    ''
                ),
                '/',
                ''
            )
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_productmaster_search_text_trgm
    ON productmaster
    USING gin (search_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_productmaster_identifier_search_trgm
    ON productmaster
    USING gin (identifier_search gin_trgm_ops);
