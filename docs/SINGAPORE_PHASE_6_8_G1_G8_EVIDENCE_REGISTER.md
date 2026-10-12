# Singapore Payroll — Phase 6.8 G1–G8 Evidence Register (execution started)

- **Date:** 2026-09-28. Baseline: `docs/SINGAPORE_PHASE_6_7_G1_G8_EVIDENCE_READINESS.md` (priority order kept).
- **Statuses:** ENGINEERING COMPLETE · EXTERNAL EVIDENCE REQUIRED · BUSINESS APPROVAL REQUIRED · BLOCKED · COMPLETE.
- **No gate is COMPLETE.** "Engineering complete" never means "gate complete". No external approval, certification,
  acceptance or partner result exists.

## Evidence produced or registered this phase (internal / retrieved — not external acceptance)

| Item | Source | Date | Gate |
|---|---|---|---|
| G1 independent-comparison **input pack** (36 cases, cited CPF Board sources, expected figures, fixture hashes; reviewer column PENDING) | `docs/SINGAPORE_G1_CPF_INDEPENDENT_COMPARISON_PACK.md` | 2026-09-28 | G1 |
| IRAS modification guide registered as a canonical source (`iras_ais_modification_guide`, SHA-256 `a419da57…f01df`) | `backend/scripts/seed_singapore_canonical_pack.py` | Published 2025-09-15; retrieved 2026-09-28 | G3 |
| IR8A Revision / Amendment workflow (engineering) | `backend/app/modules/payroll/service.py` `create_sg_ir8a_modification`; `tests/test_singapore_phase68_ir8a_modifications.py` | 2026-09-28 | G3 |

## Register

| Gate | Requirement | Evidence required | Current status | Evidence source (existing) | Evidence date | Owner | Acceptance criterion | Missing item | Next action |
|---|---|---|---|---|---|---|---|---|---|
| **G1** CPF content (priority 1) | Tables, low-wage formulas, OW/AW, ceilings, rounding, 2027 boundary independently certified | Signed independent comparison report | ENGINEERING COMPLETE · **EXTERNAL EVIDENCE REQUIRED** | 36/36 golden; CPF Board sources hashed; G1 input pack | Pack 2026-09-28 | Statutory compliance owner | Every case matches the reviewer's own computation to the cent; signed | Independent reviewer engagement and signed report | Send the input pack to the reviewer; agree the case set |
| **G8** Parallel payroll (priority 2) | Two cycles + annual AIS simulation, zero unexplained material differences | Parallel-run reconciliation report | ENGINEERING COMPLETE (rehearsal) · **EXTERNAL EVIDENCE REQUIRED** | Rehearsals 172/0 (6.5–6.8, incl. the migrated shared-schema copy) | 2026-09-28 | Implementation lead | Two live cycles + AIS simulation reconcile | Design partner; data-processing agreement (needs G7) | Select a partner; sign a DPA |
| **G7** Security / privacy (priority 3) | PDPA roles/transfers/retention, NRIC/FIN/SHG protections, credentials, isolation, recovery approved | DPO sign-off; security review; recovery test | ENGINEERING COMPLETE · **EXTERNAL EVIDENCE REQUIRED · BUSINESS APPROVAL REQUIRED** | Masking, isolation, access control, refusal auditing, hotfix maker-checker, IR8A-modification masking and isolation tests | 2026-09-28 | DPO + security owner | Approvals signed; no open critical findings | DPO review; security review; recovery test | Schedule the DPO + security reviews |
| **G5** Foreign workforce (priority 4, MOM) | Work-pass/CPF distinction, levy billing, LQS/PWM gating, levy-recovery controls | MOM levy-bill reconciliation; published values | ENGINEERING COMPLETE · **EXTERNAL EVIDENCE REQUIRED** · partly **BLOCKED** | 6,132 MOM PWM cells (6 MOM sources hashed); levy/LQS/PWM tests | Sources 2026-09-23/25 | Statutory compliance owner | Bill reconciles; no BLOCKED rows in scope | Real levy bill; unpublished values | Obtain values or a signed scope-out |
| **G6** Labour pay (priority 4, MOM) | Salary deadlines, payslip, deductions, Part IV OT, leave/public holidays validated | Legal review memo | ENGINEERING COMPLETE · **EXTERNAL EVIDENCE REQUIRED** | Employment Act rules; MOM incomplete-month table reproduced | 2026-09-25 | Legal + compliance owner | No open legal findings | Legal review | Commission a legal review |
| **G3** IRAS (priority 5) | AIS YA2027 model validated; API onboarding or export-only; amendment + acknowledgement proven | Signed mode decision; IRAS-acknowledged original + modification | ENGINEERING COMPLETE (export mode incl. revision/amendment) · **BUSINESS APPROVAL REQUIRED · EXTERNAL EVIDENCE REQUIRED** | Extract, lifecycle, 6.7 guard, 6.8 modifications; IRAS guide registered | 2026-09-28 | Product owner | G3 decision doc §J | Mode decision; IRAS acknowledgements; API onboarding if chosen | Owner Decision 1 |
| **G4** Tax clearance (priority 5) | IR21 lifecycle validated with current IRAS guidance | Guidance review; acknowledged filing | ENGINEERING COMPLETE · **EXTERNAL EVIDENCE REQUIRED** | IR21 lifecycle tests; register | 2026-09-24/25 | Statutory compliance owner | Matches guidance; filing acknowledged | Review + filing | Compliance review against IRAS IR21 guidance |
| **G2** CPF operations | CSN, EZPay file, SDL/SHG, payment, amendment / reconciliation proven | CPF acknowledgement + payment reconciliation | ENGINEERING COMPLETE · **EXTERNAL EVIDENCE REQUIRED** | EZPay spec sample byte-exact; lifecycle; rehearsal file | 2026-09-28 | Employer payroll operations | Accepted file; totals reconcile | Live submission | With the G8 partner |
| **Priority 6** Unpublished statutory values | Pre-July-2026 part-time LQS; Work Permit levy before 24 Sep 2026 outside construction | Official publication or signed scope-out | **BLOCKED** | Pack BLOCKED rows (not invented) | — | Statutory compliance owner | Values published and seeded from a hashed source, or cohort scoped out | MOM publication | Monitor MOM; decide the scope-out |
