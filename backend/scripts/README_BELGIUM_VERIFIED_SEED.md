# Loading verified Belgian values (`seed_belgium_verified_values.py`)

The script loads a file of **verified** Belgian values into a **Draft** Belgian pack. It uses the same governed import
as the Super Admin **Import from file** button: the same validation, all-or-nothing, a source on every row, and every
row saved **unsigned** (`[PENDING G1]`). It never signs, approves, certifies or activates anything.

## 1. Prepare the file

- Start from the import template (Readiness → Signing status → **CSV template** / **JSON template**, or
  `scripts/templates/be_content_import_template.csv|json`), or from **Export workbook** for an XLSX.
- Use one row per value: the catalogue key, the `rowId` (for scalar rows, from the exported workbook), the official
  figure and `sourceDocumentId`.
- `sourceDocumentId` is the id or reference of a source document that has already been registered and reviewed.
  The script refuses an empty source, and any source containing SAMPLE, DRAFT, NOT VERIFIED or the word AI. It also
  refuses a source document marked `[UNVERIFIED]`, a *Draft sources* sheet, and the AI-drafted workbook
  `BE_2026_AI_DRAFT.xlsx`.

## 2. Dry run, then apply (from `backend/`)

```
python -m scripts.seed_belgium_verified_values --pack BE-PAYROLL-2026 --file verified.csv --actor-id <importer id>
python -m scripts.seed_belgium_verified_values --pack BE-PAYROLL-2026 --file verified.csv --actor-id <importer id> --apply
```

- The dry run (the default) writes nothing. It prints the rows to add or update per group, any refusals and
  validation errors, and the catalogue keys the file does not mention.
- `--apply` writes only when the dry run is clean. A single error writes nothing.
- `--apply` writes to a local database only, unless the operator sets the override described in
  `scripts/_local_db_guard.py`.
- Add `--version` when the pack id has several versions, and `--reason` to set the audit reason.

## 3. After loading: each step by a different Super Admin

1. **Sign:** a second Super Admin (not the importer, and not anyone who edited those rows) reviews each row in the
   Super Admin console and signs it. Use Readiness → Signing status → *Select pending cells* to bulk-sign. Each row
   needs its own reviewed, archived source. Signing removes `[PENDING G1]`.
2. **Certify:** once no row is pending and the authority examples replay exactly, use **Record certification run**
   (Readiness → Golden certification). Activation needs a **PASS** run recorded for this pack, with its content
   unchanged since: any later edit, signature or unsigning means a new run must be recorded.
3. **Approve:** a Super Admin who neither edited nor signed this version records the approval (**Approve** in the
   pack header). Belgium refuses self-approval.
4. **Activate:** a **different** Super Admin from the approver sets the pack Active. That Super Admin must also not
   have edited or signed this version. Belgium's approver may not activate, and Hotfix Activate is not offered.
   Activation is refused while any row is pending, empty or without a source, or the certification is not PASS
   (gate G1). Readiness shows every gate (G1–G7) and what each one still needs.

Any later edit to a row clears the pack's approval and must be signed again.
