# Malaysia go-live runbook (ZP-MY-ENG-001)

**Who this is for:** engineering, security, payroll operations, compliance and the CTO.

Malaysia ships switched off. Deploying the code changes nothing for tenants:
- the Malaysia organisation routes answer 404;
- the rule pack is Draft and every row is EXTRACTED (`[PENDING G1]`), even values the specification states;
- PCB blocks every payslip until the HASiL 2026 computerised specification is archived and Phase 4 is built;
- filings are canonical previews only: approval is refused until the official authority layouts are archived.

This runbook is the order of the steps that turn it on. Each step needs its named owner, and none is done from a developer machine against production. The live gate state is the Super Admin Malaysia page's **Release gates** tab; the checklists are in [`release-gates/`](release-gates/README.md).

## 1. Deploy (engineering)

1. Open the PR from `venu` to `main`. Before merging, fetch `main`; if it gained migrations, merge `main` into `venu` and re-parent the first Malaysia migration not on `main` onto `main`'s head (one head). Update the migration pins, `alembic/MIGRATIONS_MANIFEST.txt` and the drift tests.
2. Run the full suite in a clean checkout with no `.env`, plus the frontend gates (`npm run check:undefined`, `npm run build`, `npm test`).
3. Merge. The pipeline applies the additive Malaysia migrations in order: `13574b996ccf`, `5f314f975ac3`, `efdc07f97eb5`, `f793f6074257`.
4. Check the production `alembic_version`, that `/api/payroll/malaysia/*` answers 404, and that another country's run approval, bank export and retention report still work.

## 2. Secrets (security, gate G4)

1. Put `MY_IDENTIFIER_KEYRING` (a JSON map of key version to a 32-byte key) and `MY_IDENTIFIER_FINGERPRINT_KEY` in Secret Manager. The fingerprint key is never rotated. Neither key ever goes in a `.env` file or the repository.
2. Rehearse a rotation on a non-production copy: add the next key version, run `python -m scripts.rotate_my_identifier_keys` (dry run), then `--apply`. The output is counts and row ids only; any row that fails to decrypt stops the run with nothing written.
3. Production rotation is done only by the approved operator, with `--confirm-remote`.

## 3. Statutory content (G1 to G3 owners)

1. **Seed the Draft pack once:** a Super Admin clicks "Create draft pack from the specification" on the Malaysia page (only while no Malaysia pack exists; a reason is required; audited).
2. **Load the tables with the statutory workbook** (Import & verify): download, fill from the official documents (EPF Third Schedule, PERKESO / EIS / foreign-worker schedules, gazetted holidays, ordinances), preview, apply to the Draft pack. Applied rows stay EXTRACTED.
3. **Sign every row** against its stored, hashed source reviewed by a second Super Admin. A policy the specification does not define may be signed `NOT_SUPPORTED`; the feature stays blocked.
4. **Build PCB (Phase 4)** from the HASiL specification and record its official test questions as authority examples; run the golden check until every example matches exactly.
5. **Archive the authority layouts** (e-PCB / CP39, EPF, PERKESO, HRD, EA / EC, Form E, CP8D, CP22 / CP22A / CP21) in `MY_FORM_SCHEMA_CATALOG` through a reviewed code change.
6. A Super Admin who made none of the edits approves the pack, then activates it.

## 4. Canary and parallel run (implementation, gate G5)

1. Put the design employers' organisation ids in `MY_CANARY_ORG_IDS`; only they see the Malaysia API.
2. Record employer registrations, worker profiles, work assignments and identifiers; each needs a second user's approval.
3. Run two monthly cycles per employer in parallel with the incumbent payroll, including at least one foreign worker. Import each incumbent file (no identifiers), explain every difference, and have a second person accept the cycle.

## 5. Decisions, evidence and launch (product, compliance, management)

1. Record owner decision D-8 (retention) and approve the retention periods.
2. Record the `MY-GATE-G1` to `MY-GATE-G7` evidence and the four `MY-SIGNOFF-*` memos, each reviewed by someone other than its uploader.
3. When the Release gates tab shows every gate passed, move the Malaysia service registry from PLANNED to AVAILABLE (the server refuses while anything is unmet), then set `MY_TENANT_ONBOARDING_ENABLED=True`.

## Rollback

Set `MY_TENANT_ONBOARDING_ENABLED=False` and clear `MY_CANARY_ORG_IDS`: the routes answer 404 again. The migrations are additive and stay; no data is deleted.
