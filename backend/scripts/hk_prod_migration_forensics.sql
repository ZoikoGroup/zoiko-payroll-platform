-- hk_prod_migration_forensics.sql — READ-ONLY schema inventory for the deploy failure on
-- alembic revision 4c5d6e7f8a9b (docs/hk-evidence/ops/DEPLOY_FAILURE_4c5d6e7f8a9b.md).
--
-- SELECT statements only. Reads system catalogs (information_schema / pg_catalog) and the
-- one-row alembic_version table — never an application table, so no personal data.
-- Run by a human with production read access, in a read-only session:
--
--   PGOPTIONS="-c default_transaction_read_only=on" \
--   psql "$PROD_READONLY_URL" -X -A -t -F '|' -f backend/scripts/hk_prod_migration_forensics.sql \
--        -o prod_schema_inventory.txt
--   LC_ALL=C sort -o prod_schema_inventory.txt prod_schema_inventory.txt   # byte order, like the references
--
-- Output: one line per object, "kind|object|detail", sorted, so it diffs line by line against
-- docs/hk-evidence/ops/forensics/reference_*.txt (the same query on local copies):
--   diff docs/hk-evidence/ops/forensics/reference_prod_2026-10-13_b08f04497195.txt prod_schema_inventory.txt
-- shows everything that changed in production since 2026-10-13 (what 4c5d6e7f8a9b and any
-- other out-of-band step did);
--   diff docs/hk-evidence/ops/forensics/reference_main_head_8b14824fb575.txt prod_schema_inventory.txt
-- shows how far production is from main.

SELECT kind || '|' || object || '|' || detail FROM (
    SELECT '0_alembic_version' AS kind, version_num::text AS object, '' AS detail
      FROM alembic_version
    UNION ALL
    SELECT '1_table', c.relname, ''
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    UNION ALL
    SELECT '2_column', table_name || '.' || column_name,
           udt_name || coalesce('(' || character_maximum_length || ')', '')
           || CASE WHEN is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END
           || coalesce(' DEFAULT ' || regexp_replace(column_default, 'nextval\(''[^'']+''::regclass\)', 'nextval(<seq>)'), '')
      FROM information_schema.columns
     WHERE table_schema = 'public'
    UNION ALL
    SELECT '3_index', indexname, indexdef
      FROM pg_indexes
     WHERE schemaname = 'public'
    UNION ALL
    SELECT '4_constraint', con.conrelid::regclass::text || '.' || con.conname,
           pg_get_constraintdef(con.oid) || CASE WHEN con.convalidated THEN '' ELSE ' [NOT VALID]' END
      FROM pg_constraint con JOIN pg_namespace n ON n.oid = con.connamespace
     WHERE n.nspname = 'public'
    UNION ALL
    SELECT '5_enum', t.typname, string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
      FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = 'public'
     GROUP BY t.typname
    UNION ALL
    SELECT '6_sequence', sequence_name, data_type
      FROM information_schema.sequences
     WHERE sequence_schema = 'public'
    UNION ALL
    SELECT '7_trigger', tg.tgrelid::regclass::text || '.' || tg.tgname, pg_get_triggerdef(tg.oid)
      FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND NOT tg.tgisinternal
    UNION ALL
    SELECT '8_function', p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')', md5(pg_get_functiondef(p.oid))
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public' AND p.prokind = 'f'
) inventory
ORDER BY 1;
