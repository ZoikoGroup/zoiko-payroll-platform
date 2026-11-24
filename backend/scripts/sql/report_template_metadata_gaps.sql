-- Report templates that need content attention — READ-ONLY (a single SELECT).
--
-- One row per template version (every country) that has an empty required
-- metadata field, or a description containing an internal code. Run it against
-- the live database with a read-only role, e.g.
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/scripts/sql/report_template_metadata_gaps.sql
--
-- Required metadata (matches the Overview "Missing" warning): regulatory_authority,
-- source_references, change_summary. reconciliation_tolerance is NOT required:
-- NULL means "exact match" (see ReportTemplate.reconciliation_tolerance).
--
-- Internal-code patterns (any one flags the description):
--   gate / decision refs     (G3) (D10) "gate G3"
--   spec / gap ids           BE-027, MX-061, "gap register C8", ZP-BE-ENG-001
--   document version codes   BE-FICHE-COPY-A, BE-INDIVIDUAL-ACCOUNT-A
--   catalogue wording        "content keys", [PENDING G1]
SELECT
    t.id,
    t.jurisdiction_country                                   AS country,
    t.jurisdiction_state                                     AS state,
    t.template_key,
    t.version,
    t.status,
    t.reporting_year,
    t.name,
    concat_ws(', ',
        CASE WHEN nullif(btrim(t.regulatory_authority), '') IS NULL THEN 'regulatory_authority' END,
        CASE WHEN nullif(btrim(t.source_references), '')   IS NULL THEN 'source_references' END,
        CASE WHEN nullif(btrim(t.change_summary), '')      IS NULL THEN 'change_summary' END
    )                                                        AS missing_fields,
    (t.description ~ '(\(G[0-9]+\)|\(D[0-9]+\)|gate G[0-9]+|\m[A-Z]{2}-[0-9]{3}\M|gap register [A-Z][0-9]+|ZP-[A-Z]{2}-ENG-[0-9]+|\m[A-Z]{2}(-[A-Z]+)+-[A-Z]\M|content keys|\[PENDING)')
                                                             AS description_has_internal_code,
    substring(t.description from '(\(G[0-9]+\)|\(D[0-9]+\)|gate G[0-9]+|\m[A-Z]{2}-[0-9]{3}\M|gap register [A-Z][0-9]+|ZP-[A-Z]{2}-ENG-[0-9]+|\m[A-Z]{2}(-[A-Z]+)+-[A-Z]\M|content keys|\[PENDING)')
                                                             AS first_internal_code,
    t.description
FROM payroll_report_templates t
WHERE nullif(btrim(t.regulatory_authority), '') IS NULL
   OR nullif(btrim(t.source_references), '')   IS NULL
   OR nullif(btrim(t.change_summary), '')      IS NULL
   OR t.description ~ '(\(G[0-9]+\)|\(D[0-9]+\)|gate G[0-9]+|\m[A-Z]{2}-[0-9]{3}\M|gap register [A-Z][0-9]+|ZP-[A-Z]{2}-ENG-[0-9]+|\m[A-Z]{2}(-[A-Z]+)+-[A-Z]\M|content keys|\[PENDING)'
ORDER BY t.jurisdiction_country, t.jurisdiction_state NULLS FIRST, t.template_key, t.version;
