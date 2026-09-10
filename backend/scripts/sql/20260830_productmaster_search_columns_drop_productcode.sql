-- Remove Productcode from the generated search_text / identifier_search
-- columns. Matches alembic migration 20260830_0005_search_columns_drop_
-- productcode exactly -- this is the current, up-to-date column
-- definition. Supersedes 20260829_productmaster_generated_search_columns.sql
-- (that file still includes Productcode; run this one instead on a fresh
-- or reloaded database).
--
-- productmaster.Productcode is an internal-only surrogate key; the real,
-- external orderable identifier is productmaster.name. Customers/external
-- agents never reference Productcode, so it should never be searchable --
-- leaving it in these columns meant a query could coincidentally "match"
-- on an internal number that means nothing to anyone using the tool. Both
-- columns now derive from name, description, and description2 only.
--
-- Safe to run more than once, and safe to run on a database that has never
-- had these columns at all (e.g. right after a schema-only restore) --
-- every DROP is IF EXISTS and every CREATE is IF NOT EXISTS.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP INDEX IF EXISTS idx_productmaster_search_text_trgm;
DROP INDEX IF EXISTS idx_productmaster_identifier_search_trgm;
ALTER TABLE productmaster DROP COLUMN IF EXISTS search_text;
ALTER TABLE productmaster DROP COLUMN IF EXISTS identifier_search;

-- concat_ws() is STABLE, not IMMUTABLE (it takes a polymorphic VARIADIC
-- "any" argument), so it can't be used inside a GENERATED column expression
-- ("generation expression is not immutable"). These rewrites use only
-- immutable primitives (||, CASE, coalesce) and were verified to produce
-- byte-identical values to the original concat_ws-based columns.

ALTER TABLE productmaster
    ADD COLUMN search_text TEXT GENERATED ALWAYS AS (
        lower(
            coalesce(name, '')
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
                        coalesce(name, '')
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

-- Refresh planner statistics for the reloaded data -- do this every time
-- after a truncate + bulk load, not just after a schema change.
ANALYZE productmaster;
