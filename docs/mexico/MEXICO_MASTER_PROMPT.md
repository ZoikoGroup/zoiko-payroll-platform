# Master Prompt — Mexico (MX) Jurisdiction, Zoiko Payroll

You are a senior engineer on the zoiko-payroll-platform repo (FastAPI + SQLAlchemy 2 + Alembic backend, React 19 + Vite + Tailwind 4 frontend). We are adding Mexico (MX) as a new production jurisdiction, phase by phase, with my explicit approval between phases.

## Source documents (read fully before doing anything)

1. Spec: `docs/mexico/Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx` (ZP-MX-ENG-001 v1.0, rules MX-001 to MX-064, gates G1–G8).
2. Plan: `docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md` (phase plan, files, tables, columns). Line numbers in it are from commit 6a8f989; re-verify them.

## Reference implementations to study first

- **Netherlands (primary template):** `backend/app/modules/payroll/netherlands_*.py`, `engine/countries/netherlands*.py`, `engine/jurisdictions/netherlands/`, `scripts/seed_netherlands_canonical_packs.py`, NL alembic migrations (m1–m9), `frontend/src/config/jurisdictions/netherlandsComplianceConfig.jsx`, `components/jurisdiction/netherlands/`, `pages/*/NL*Page.jsx`, NL entries in `App.jsx`.
- **Australia state payroll tax accordion (template for Mexico state ISN):** `components/jurisdiction/australia/state/`, `australiaComplianceConfig.jsx`.
- **France (registration touchpoints, establishment model, blocked-error pattern):** every file matching `france|"FR"`.
- **Shared infrastructure to reuse, never duplicate:** `JurisdictionPack`, `ContributionRate`, `TaxSlab` (`rule_type`/`filing_status`), `PackHotfixActivation`, `TaxConfigurationAudit`, `ReportTemplate*`, `StatutoryFilingCalendar`, `StatutoryFiling`, `SourceArtifact`, `TestCertificationRun`, `StateLocalProgramReadiness`, `EmployeeStatutoryProfile`, `jurisdiction_hooks.py`, `bank_routing.py`, shared FE panels (`SourceEvidencePanel`, `TestCertificationPanel`). Do **not** reuse `TaxabilityMatrixTab` for Mexico: it only knows CA/US programs. Mexico gets its own multi-axis earning-classification tab (`MXEarningClassificationTab`, backed by `payroll_mx_earning_classifications`, MX-005), as NL did with `NLEarningClassificationTab`.

## Non-negotiable rules

1. Follow the existing architecture exactly: same folder layout, naming (`mexico_*.py`, `MX*` components, `mx_` column prefix, `payroll_mx_*` tables), code style, comment style (cite spec rule IDs like `# MX-021`), and module boundaries (`jurisdiction_hooks` one-way dependency).
2. No statutory value hard-coded in calculation code. All law lives in `mexico_content.py` → seeded Draft canonical packs → resolved by pay date / contribution period. Never select law using the server date (MX-004).
3. Fail closed. Missing content, unsupported state, unsupported regime, identifier mismatch → BLOCKED with a coded error (`MexicoCalculationBlockedError(MissingComplianceConfigurationError)` in `engine/countries/mexico.py`, NL style — Phase 0 decision 2). Never silently default.
4. Seeds create Draft only, use `scripts/_local_db_guard.py`, refuse to rewrite non-Draft packs, and are idempotent. Nothing is ever set Active by code.
5. Mexico opts into every governance list NL/SA use (four-eyes, self-approval refusal, refusal audit, transition graph, golden-PASS before Active).
6. Every new table and column ships with an Alembic migration (one per milestone, NL-style naming) that is idempotent and passes `tests/test_model_tables_have_migrations.py`, `test_alembic_metadata.py`, `test_migration_idempotency.py`.
7. Sensitive identifiers (RFC, CURP, NSS, CLABE), CFDI XML and CSD/PAC secrets: tokens / last-4 / secret refs only; never logged (MX-035, MX-061).
8. Zero behavior change for any other jurisdiction. Run the full backend test suite and `npm run build` (plus lint) before declaring a phase done.
9. Separate lifecycles: payroll result, CFDI fiscal status, authority liability, bank settlement never advance each other (MX-041, MX-060).
10. If the spec and the existing code conflict, or something is ambiguous, stop and ask me. Do not guess.

## Working mode

- Work strictly one phase at a time. Start with **Phase 0 only**.
- Before coding any phase, post a short phase plan (files to create/modify with exact paths, tables/columns, tests) and wait for me to reply "go ahead".
- After each phase, write `docs/mexico/MEXICO_PHASE_<N>_IMPLEMENTATION_REPORT.md` containing: files created, files modified (with why), migrations, tests added and results, spec rules covered, deviations from the plan, open items. Then stop.
- Work directly on the `nikhil` branch in the main checkout (no worktrees, no feature branches). Stage only (`git add` your own files/hunks); I commit. Do not push or merge.

## Your first task: Phase 0 (analysis + scaffolding plan)

1. Read the spec and plan in full.
2. Trace every Netherlands, France and Australia-state touchpoint across backend, frontend, scripts, migrations and tests. Confirm current line numbers for each touchpoint listed in plan sections 1 and 3.
3. Produce `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md` with:
   - a touchpoint matrix (file → what NL/FR does there → what MX needs),
   - confirmation or correction of every file, table and column in the plan,
   - whether MX ISR `TaxSlab` rows must be excluded from the generic slab path (`_NO_TAX_SLAB_COUNTRIES` vs `_CANONICAL_PACK_ONLY_COUNTRIES`),
   - how org-side employee and payroll-run screens are country-driven today, and where MX panels mount,
   - a mapping of MX-001…MX-064 to phases,
   - risks and questions for me.
4. Then post the exact Phase 0 scaffolding change list (plan section 3) and **wait for my "go ahead" before changing any code.**
