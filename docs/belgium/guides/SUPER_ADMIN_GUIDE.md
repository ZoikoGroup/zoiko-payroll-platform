# Belgium — Super Admin guide

For: the Super Admin team who owns Belgian **content**, meaning the rates, bands, formulas and earning treatments
the engine reads. The organisation side is covered by [ORG_ADMIN_GUIDE.md](ORG_ADMIN_GUIDE.md).

Where: **Super Admin → Compliance → Belgium** (`/super-admin/compliance/belgium`). The page header shows the selected
pack, with its status, version and window. Below it are the Belgian tabs:
- **Overview**;
- **Policy & rounding**, **Withholding**, **ONSS employee**, **ONSS employer & reductions**;
- **Holiday pay**, **Wages & working time**, **Absence**, **Public holidays**;
- **Earning classification**, **Joint Committees**;
- **Signing status**, **Owner decisions**;
- **Organizations**.

Three rules apply throughout:
- **Nothing in Belgium is calculated from a value that is not signed.** An unsigned row blocks payroll with
  `BE_CONTENT_PENDING` (see [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md)).
- **Four-eyes everywhere.** The person who imports or edits a row can never sign it. Signing is per row, with a
  reviewed source and a reason, and is audited.
- **No statutory value lives in code.** Everything comes from the pack.

## 1. The content lifecycle

| Step | Who | Where (screen labels) | Result |
|------|-----|-----------------------|--------|
| 1. Seed the Draft | Super Admin A | **Overview** → "No Belgium pack yet" → **Reason \*** → **Create the Draft pack** | `BE-PAYROLL-2026` in **Draft**, every row `[PENDING G1]`, registry row PLANNED. Only offered while no Belgian pack exists. On a fresh deploy, `python -m scripts.belgium_post_deploy_setup` does the same ([DEPLOY_NOTES.md](../DEPLOY_NOTES.md) §5) |
| 2. Export the workbook | A | **Signing status** → "Content workbook (specialist intake)" → **Export workbook** | XLSX with every key, slab, earning class, schema version, tolerance, calendar template, decision and source |
| 3. Specialist fills it | Belgian specialist | Offline, in the XLSX | Value, source (form number) and confidence per row. Start from the AI draft `docs/belgium/content/BE_2026_AI_DRAFT.xlsx` if useful: its rows are proposals, never signed |
| 4. Import | A | **Signing status** → **Workbook (.xlsx)** + **Reason \*** → **Dry run** → read the report (every changed cell, `ERROR` rows in red) → **Confirm import** | Rows written as **UNSIGNED**. Draft packs only ("Imports go into a Draft pack only."). It is all-or-nothing: one error means nothing is written |
| 5. Review by pattern | Super Admin B (not the importer) | **Signing status** → "Bulk sign (N pending)" → "Earning-class patterns" → **Select pending cells** for a pattern; or tick rows one by one | A pattern groups components that have the same treatment in every obligation, so one review covers many cells |
| 6. Bulk sign | B | Same panel → **Reason \*** → **Sign N selected** | Each row is signed on its own, with its own reviewed, archived source. Refused for anyone who imported or edited the row |
| 6a. Single row | B | The row's tab → open the row → **Sign (no changes)** | Signs as reviewed. Editing and signing in one action is refused: **Save (stays pending)** first, then a different person signs |
| 7. Golden certification | A or B | **Overview** → "Golden certification (gate G1)" → **Register example** (**Name \***, **Reviewed source id \***, **Description \***, worked case, **Reason \***) → **Record certification run** | Each official example is replayed with this pack's own rows, and every expected figure must match exactly. The run is what activation requires |
| 8. Approve the pack | A second Super Admin | Pack header → **Approve** | Recorded approver (hover shows "Currently approved by user #…") |
| 9. Activate | Owner-authorised Super Admins | Per [BELGIUM_ACTIVATION_RUNBOOK.md](../BELGIUM_ACTIVATION_RUNBOOK.md) | Refused while any gate is red. The refusal is shown on **Overview** |
| 10. Assign | Super Admin | **Organizations** → **Assign Organizations** | Belgium is assigned only to organisations that are open for it (canary first) |

## 2. The release gates (Overview → "Release gates")

**G1** through **G7** are shown as `MET` (green) or red. A red gate lists its failing checks underneath. Gates are
**computed from evidence**: nobody can tick one.

| Gate | What makes it green (summary — exact checks in [BELGIUM_ACTIVATION_RUNBOOK.md](../BELGIUM_ACTIVATION_RUNBOOK.md)) |
|------|------|
| G1 | Every content row signed, with a source, and golden certification passing |
| G2-G7 | Authority channels, parallel cycles (**Parallel cycles (release gate G4)** in the organisation's Compliance Centre), security and operational evidence, as listed per gate on the Overview |

The registry row stays **PLANNED** while any gate is red, so organisations cannot onboard Belgium.

## 3. Other tabs

- **Policy & rounding … Public holidays**: the canonical rows of each catalogue group. Open a row to see its value,
  source, signer and history.
- **Earning classification**: "Earning classification (independent statutory bases, BE-006 / BE-007)". A REVIEW
  treatment never calculates (`BE_EARNING_CLASS_REVIEW`).
- **Joint Committees**: sector agreements and wage modules (**Save Draft**). These are content as well.
- **Owner decisions**: "Owner and specialist decisions" from the gaps register. **Blocks launch** says whether a
  decision holds back activation.

## 4. The DEMO pack (staging only)

`BE-DEMO-2026` "DEMO — NOT FOR PAYROLL" exists only when `BE_DEMO_PACKS_ENABLED=true` and the environment is not
production. It is created by `scripts/seed_belgium_demo.py`, never through this console.
- It is never offered for activation, and never assigned to an organisation outside `BE_DEMO_ORG_IDS`.
- Its payslips and filings carry the DEMO watermark.
- It is never paid and never transmitted.

Click-through script: [STAGING_REHEARSAL.md](../STAGING_REHEARSAL.md).

## 5. When something is refused

Look the code up in [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md). Content codes (`BE_CONTENT_PENDING`,
`BE_ROW_MISSING`, `BE_TABLE_EMPTY`, `BE_FORMULA_INVALID`, `BE_BAND_NOT_FOUND`, `BE_EARNING_CLASS_*`) are fixed here,
by entering, correcting and re-signing the row. They are never worked around in an organisation.
