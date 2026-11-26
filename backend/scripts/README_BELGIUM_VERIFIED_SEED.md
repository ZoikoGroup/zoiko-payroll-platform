# Loading verified Belgian values (`seed_belgium_verified_values.py`)

The script loads a file of **verified** Belgian values into a **Draft** Belgian pack. It uses the same governed import
as the Super Admin **Import from file** button: the same validation, all-or-nothing and a source on every row. Since
the gate removal (owner decision 2026-11-25, `docs/GATE_REMOVAL.md`) a saved row is **in force**: there is no signing
step and no `[PENDING G1]` marker. The script never approves or activates anything.

## 1. Prepare the file

- Start from the import template (Pack status → Signing status → **CSV template** / **JSON template**, or
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

## 3. After loading

There is no signing, golden-certification or release-gate step since the gate removal (owner decision 2026-11-25):

1. **Approve:** a Super Admin other than the pack's last editor records the approval (**Approve** in the pack
   header). The pack's catalogue must be complete; rows may still be empty.
2. **Activate:** set the pack Active. Activation needs only content in the pack (a DEMO pack is never activated).
3. **Registry:** if Belgium's registry row is PLANNED, move it to AVAILABLE (reason required) so registration opens.

A row still without a value blocks only the Belgian calculation that needs it, with a named reason.
