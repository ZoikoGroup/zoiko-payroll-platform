# Poland (PL) — build hand-off index

Specification: `Jur_doc/Zoiko_Payroll_Poland_Engineering_Implementation_Wireframe_v1.0.docx`
(ZP-PL-ENG-001 v1.0). Architectural reference: South Africa (ZA). Engine and
declaration shapes follow New Zealand (NZ) where the Poland spec requires it.

## Workflow

1. Venu hands one phase file (`HANDOFF_P<n>.md`) to the implementing agent.
2. The agent implements **that phase only** and leaves the work **uncommitted**.
3. Claude reviews the diff against the phase file and the specification, fixes
   issues, runs the targeted tests, and reports.
4. Venu says "go ahead" before anything is committed or pushed (push only to `venu`).

## Decisions (approved 2026-11-05)

| ID | Decision |
|---|---|
| D1 | ZA file naming / UI layout; NZ-style split engine (`engine/jurisdictions/poland/*`), versioned declaration tables, separate `pl_org_router.py`, governed Super Admin edit/sign console. |
| D2 | First release = `umowa o pracę` on MONTHLY pay only. Civil-law contracts, multiple insurance titles, A1/posted workers, management contracts, equity and 50% creator costs BLOCK with a reason code. |
| D3 | Content pack `PL-PAYROLL-2026` (1 Jan – 31 Dec 2026). `PL-PAYROLL-2027` is added only when 2027 values are supplied and sourced. |
| D4 | New append-only accumulator ledger `payroll_pl_accumulator_entries` (not `payroll_ytd_accumulators`, which is updated in place). |
| D5 | Filing generates and versions payloads only. No live ZUS / e-Deklaracje / PPK / bank calls anywhere (PL-021). Submission and receipts are recorded manually. |
| D6 | No override table. Adjustments use explicit correction / earning / deduction objects (PL-024). |

## Rules for every phase (non-negotiable)

- **Do not commit.** Leave changes in the working tree.
- **Never touch a database:** no seed scripts, no `alembic upgrade`/`downgrade`
  against any URL, no script that imports `app.database` outside pytest.
- **Never read or print `.env` files.**
- **No statutory value in code or UI.** Every rate, threshold, cap, amount, date
  rule, form version or code lives only in `engine/countries/poland_content.py`
  (from P1) and resolves from pack rows. A value the specification does not
  give stays EMPTY and marked `pending_g1` — never guessed.
- **Fail closed.** Missing fact or row → block with a reason code. No
  `try/except: pass`, no checks that always return True, no defaults that
  silently pick the lowest-cost treatment.
- **"PL" is Poland.** Never add the bare alias `"pl"` anywhere a free-text
  value is normalised (it is the paid-leave attendance code).
- **Stay in scope.** Edit other countries' files only where the phase file
  lists a shared wiring point, and only by adding Poland next to the existing
  entries.
- **Tests must assert real behaviour** (values, refusals, messages), not just
  "does not crash".

## Phases

| Phase | File | Status |
|---|---|---|
| P0 Scaffold, dormancy, identifiers | [HANDOFF_P0.md](HANDOFF_P0.md) | built by Claude 2026-11-05 (uncommitted) — also added a fail-closed engine stub (`engine/countries/poland.py`, `PL_ENGINE_NOT_BUILT` / `PL_SIMPLE_MODE_UNSUPPORTED`) and the dormancy refusals in `service.py` (company-details update + backfill), which the handoff missed |
| P1 Content pack | — | built by Claude 2026-11-05 (uncommitted): `engine/countries/poland_content.py`, `poland_service.seed_poland_pack` + `pl_pack_activation_refusal`, `scripts/seed_poland_canonical_packs.py` (NOT run) |
| P2 Migration + models (incl. PESEL vault) | — | built by Claude 2026-11-05 (uncommitted): migration `1ee3bbde33bb_pl_foundation` (child of `a8cde2482ef0`, single head, 255 revisions) — `payroll_pl_identifier_vault` / `_identifier_access_events` / `_employer_registrations` (TENANT) / `_worker_profiles` / `_declarations` / `_ppk_participations` / `_accumulator_entries` + `payslip_items.pl_calculation_snapshot`, `payroll_runs.pl_approval_fingerprint`; `PayrollPl*` models; `pl_identifiers.py` (AES-GCM vault, keys `PL_IDENTIFIER_KEYRING` / `PL_IDENTIFIER_FINGERPRINT_KEY`). Never applied to any database. |
| P3 Engine (PIT / ZUS / health / funds / PPK) | — | built by Claude 2026-11-05 (uncommitted): orchestrator `engine/countries/poland.py` (replaces the P0 stub; `PL_ENGINE_NOT_BUILT` is gone) over `engine/jurisdictions/poland/{errors,pack,applicability,bases,declarations,zus,health,ppk,pit,employer_funds}.py`; `pl_*` context fields + `PayrollResult.pl_result`; `pl_employee_total` in the standard net; 8 hand-computed fixtures in `tests/fixtures/pl_golden/`. New pending policy row `pl_fund_cap_rule`; rounding vocabulary now names unit + mode. |
| P4 Service, hooks, API | — | built by Claude 2026-11-05 (uncommitted): `poland_service.py` (versioned registrations / profiles / PPK with four-eyes, statements PL-005/007/010, identifier vault with single-use reveal, pay-date calc inputs, freeze / replay, preflight, fingerprint, ledger at PAID, 13 hooks); `pl_org_router.py` (26 routes, `/api/payroll/poland`, dormant 404); `service.py` wiring at preview + run + manual payslip; PESEL / NIP now vault-only (refused as employee fields); route registry regenerated (1,487). |
| P5 Labour (minimum wage, overtime, leave) | HANDOFF_P5.md | — |
| P6 Sickness and benefits | HANDOFF_P6.md | — |
| P7 Frontend + Super Admin console | HANDOFF_P7.md | — |
| P8 Filing, settlement, reconciliation | HANDOFF_P8.md | — |
| P9 Release gates, parallel, privacy, release | HANDOFF_P9.md | — |
