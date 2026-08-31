-- SUPERSEDED by 20260829_productmaster_generated_search_columns.sql, which
-- converts identifier_search into a GENERATED ALWAYS ... STORED column so it
-- can never go stale. Kept here for history; do not run this after that
-- script has been applied -- ALTER COLUMN on a generated column will error.
--
-- Compact identifier search for Productcode/name/description (does not change Productcode values).
-- Productcode on productmaster is integer; alphanumeric catalog codes live in name/description.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE productmaster
    ADD COLUMN IF NOT EXISTS identifier_search TEXT;

UPDATE productmaster
SET identifier_search = lower(
    replace(
        replace(
            replace(
                concat_ws(
                    '',
                    CAST("Productcode" AS TEXT),
                    coalesce(name, ''),
                    coalesce(description, ''),
                    coalesce(description2, '')
                ),
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
WHERE identifier_search IS NULL
   OR identifier_search IS DISTINCT FROM lower(
        replace(
            replace(
                replace(
                    concat_ws(
                        '',
                        CAST("Productcode" AS TEXT),
                        coalesce(name, ''),
                        coalesce(description, ''),
                        coalesce(description2, '')
                    ),
                    ' ',
                    ''
                ),
                '-',
                ''
            ),
            '/',
            ''
        )
    );

CREATE INDEX IF NOT EXISTS idx_productmaster_identifier_search_trgm
    ON productmaster
    USING gin (identifier_search gin_trgm_ops);
