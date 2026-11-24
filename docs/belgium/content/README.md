# Belgium content files — read before importing

## ⚠️ `BE_2026_AI_DRAFT.xlsx` — AI-drafted, UNVERIFIED

**Every value in `BE_2026_AI_DRAFT.xlsx` was drafted by an AI assistant. None of it has been verified.**

- It is **not** an official source and must **not** be imported or signed as it stands.
- **Each value must be checked, one by one, against the official sources** — ONSS / RSZ (social security
  contributions, employer categories and worker codes, reductions, quarterly rate files) and SPF Finances /
  FOD Financiën (professional withholding / précompte professionnel / bedrijfsvoorheffing, Annex III scales
  and amendments) — before it is imported, and again by the signer before it is signed.
- Replace any value that does not match the official source, and record the **official source reference**
  for every row (the import refuses a changed row without one).
- Importing never signs: every imported row arrives as `[PENDING G1]` and only counts once a **second Super
  Admin** has checked it against its source and signed it. Gate G1 and pack activation stay blocked until
  then.

The file is kept in the repository as a structured starting point and as a regression fixture: a test
imports it in dry-run to prove the workbook format still parses (`tests/test_belgium_content_workbook.py`,
`tests/test_belgium_content_import_formats.py`). Passing that test says nothing about whether its values are
correct.

## `BE_DEMO_PLACEHOLDERS.json`

Placeholder values for the non-production demo only (see `backend/scripts/seed_belgium_demo.py` and
`backend/app/modules/payroll/belgium_demo.py`). Never real
statutory content; never imported into a real pack.

## Supplying real values

Use the content workbook export of the Draft pack, or the CSV / JSON template
(`backend/scripts/templates/be_content_import_template.*`), fill in the official figures with their source
references, run the import as a **dry run** first, then import. See `docs/belgium/BELGIUM_SPECIALIST_PACK.md`.
