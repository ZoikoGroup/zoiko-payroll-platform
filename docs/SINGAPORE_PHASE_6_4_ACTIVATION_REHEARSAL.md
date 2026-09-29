# Singapore Payroll — Phase 6.4 Controlled Activation Rehearsal (manifest + evidence)

- **Date:** 2026-09-28
- **Branch / base:** `nikhil` @ `83601eb`. Working tree only: nothing staged, committed, pushed, merged or deployed.
- **Builds on:** `docs/SINGAPORE_PHASE_6_3_HANDOVER_MANIFEST.md` (file groups, handover patch, merge revision).
- **Status:** engineering rehearsal passed on a **disposable** database. **Production remains BLOCKED.** The real
  Singapore packs and the 11 real templates are untouched and inactive. No CPF Board / IRAS / MOM / PDPC certification
  exists; `officialCertification` is `false` everywhere. A golden-vector PASS is internal engineering evidence only.

## 1. Where the rehearsal ran
- **Database:** a throwaway PostgreSQL 17 database `p64_reh_*` on `127.0.0.1:55432`. The script refuses any other URL,
  and the database was dropped afterwards.
- **Code:** a scratch integration clone (nikhil working tree + `origin/venu` + R1 + merge `6247da96d605` with P1 +
  Phase 6.3/6.4 changes).
- **Migrations:** built with the real chain: fork-point bootstrap (`7353751`), then `stamp a5f6e7d8c9b0` on the
  throwaway DB only, then `alembic upgrade head`, which applied 16 revisions and ended at `6247da96d605`.
- **Result:** 159 PASS / 0 FAIL / 0 BLOCKED / 2 INFO. The evidence JSON is kept outside the repository.

## 2. Files changed in Phase 6.4

| Group | File | Change | Why |
|---|---|---|---|
| B. Shared file (Singapore-only hunk) | `backend/scripts/seed_statutory_report_templates.py` | +18 lines inside the existing Singapore block: `_sg_catalog_meta()` and `**_sg_catalog_meta(...)` on SG-IR8A, SG-SDL-MONTHLY, SG-CPF-EZPAY | Rehearsal defect: these three templates were seeded with no description, authority or source reference. They now carry the catalogue text and cite the registered IRAS AIS / CPF SDL / CPF EZPay FTP-spec source artifacts (with SHA-256). **The 3 Germany hunks are unchanged. Stage with `git add -p` and leave them out** |
| B. Shared file | `backend/app/modules/payroll/service.py` | 2 `order_by` lines: `TestCertificationRun.id.desc()` added as a tie-breaker in the pack-activation gate's "latest golden run" and in `list_test_certification_runs` (which the SG activation-readiness view reads) | Defect found by the new test in the full suite: `run_at` is server-side `now()` (whole seconds on SQLite), so two runs in one second tied and the gate read the older FAIL after a newer PASS. Only an exact tie changes order. **Shared: the same gate serves US packs; the effect is identical** |
| C. Tests | `backend/tests/test_singapore_phase64_activation.py` (new) | 3 tests | Pins the metadata fix and the golden-FAIL gate, including a forced `run_at` tie. It fails without the tie-break (verified) |
| D. Documentation | `docs/SINGAPORE_PHASE_6_4_ACTIVATION_REHEARSAL.md` (new) | this file | Manifest + evidence |

- **A. Singapore-only files:** none changed.
- **E. Protected, F. Germany, G. other jurisdictions:** none changed. This is hash-verified, and the rehearsal's Germany
  template/pack fingerprint was identical before and after every Singapore seed, reseed and promotion.

## 3. Rehearsal findings (not changed — decisions)
1. **Refused state changes are not audit-logged.** All 48 refusals were structured (HTTP 400/409, `BAD_REQUEST`) and
   left state unchanged, but none wrote an audit row. Successful transitions are fully audited.
2. **Pack self-approval is recorded, then refused at activation.** `set_jurisdiction_pack_approver` records a
   self-approval; the distinct-approver gate refuses activation. An earlier refusal at the approve step is a possible
   hardening.
3. **Four dedicated generators leave `applicable_tax_pack_version` empty:** SG-IR21-REGISTER, SG-SDL-MONTHLY,
   SG-IR8A, SG-CPF-EZPAY. Each underlying payslip pins its pack version (verified), so the evidence exists at payslip
   level, not on the report row.
4. **The CPF EZPay download contains full NRIC/FIN,** as the CPF Board file specification requires. The stored report
   row does not contain it, and the file is never stored (rebuilt, sha256-verified, APPROVED-only download).

## 4. External evidence gates G1–G8 (ZP-SG-ENG-001 §18)

Gate text is quoted from the specification. Status legend:
- **ENGINEERING VERIFIED:** proven by code and tests.
- **INTERNAL EVIDENCE:** Zoiko-produced (golden vectors, rehearsals).
- **EXTERNAL EVIDENCE REQUIRED:** a regulator, independent or employer artifact is needed.
- **BLOCKED:** a required source or route is unavailable.

| Gate | Required evidence (spec) | Current status | Existing repository evidence | Missing external evidence | Owner | Activation impact |
|---|---|---|---|---|---|---|
| G1 CPF content | 2026 citizen/SPR tables, low-wage formulas, OW/AW classification, ceilings, rounding and 2027 boundary **independently certified** | INTERNAL EVIDENCE; EXTERNAL EVIDENCE REQUIRED | Official CPF Board tables hashed as source artifacts; 36/36 golden vectors incl. CPF Board worked examples and 2027-boundary cases; rehearsal matched golden F1/F2/F4 | Independent certification of the tables, formulas and rounding | Statutory compliance owner + independent reviewer | Blocks commercial activation |
| G2 CPF operations | CSN workflow, CPF EZPay FTP/file output, SDL/SHG values, contribution payment and amendment/reconciliation **proven** | ENGINEERING VERIFIED (file build, lifecycle); EXTERNAL EVIDENCE REQUIRED | EZPay builder reproduces the CPF spec sample; PREPARED→APPROVED (distinct approver)→SUBMITTED→ACCEPTED/REJECTED/UNKNOWN; supplementary correction advice; SDL/SHG golden | A real CPF EZPay upload accepted by CPF Board, payment and amendment reconciliation | Employer payroll operations + CPF Board | Blocks |
| G3 IRAS | AIS YA2027 data model validated; AIS-API 2.0 onboarding **or** explicit export-only mode; amendment and acknowledgement paths proven | Export-only: ENGINEERING VERIFIED. AIS-API 2.0: not built, needs IRAS onboarding (EXTERNAL EVIDENCE REQUIRED) | IR8A EXPORT_READY extract + manual-submission lifecycle; AIS API direct submission not built | IRAS validation of the AIS data; AIS-API 2.0 onboarding (or a signed export-only decision); acknowledgement evidence | Product owner + IRAS | Blocks |
| G4 Tax clearance | IR21 trigger, monies hold, filing, directive, release/remittance and exceptions validated with current IRAS guidance | ENGINEERING VERIFIED; EXTERNAL EVIDENCE REQUIRED | IR21 case lifecycle with distinct-approver release, bank-file hold, register (rehearsal: tenant-scoped, FIN masked, hold in force) | Validation against current IRAS guidance / a real IR21 filing | Statutory compliance owner | Blocks |
| G5 Foreign workforce | Work-pass/CPF distinction, employer levy billing, LQS/PWM gating and prohibited levy recovery controls verified | ENGINEERING VERIFIED; partly BLOCKED; EXTERNAL EVIDENCE REQUIRED | S Pass: no CPF, levy is employer cost, net = gross (rehearsal); LQS evaluated; PWM shortfall blocks run approval; PWM overtime-gross from 6,132 MOM cells | Reconciliation with a real MOM levy bill; pre-July-2026 part-time LQS and Work Permit levy before 24 Sep 2026 outside construction are unpublished (pack BLOCKED items) | Statutory compliance owner + MOM | Blocks |
| G6 Labour pay | Salary deadlines, payslip, authorised deductions, Part IV overtime, leave/public-holiday calculations validated | ENGINEERING VERIFIED; EXTERNAL EVIDENCE REQUIRED | Employment Act rule rows; Part IV overtime from attendance (rehearsal: 30 h); MOM incomplete-month table reproduced; gazetted holidays | Legal / MOM validation | Legal + statutory compliance owner | Blocks |
| G7 Security/privacy | PDPA roles/transfers/retention, NRIC/FIN/SHG protections, credentials, tenant isolation and recovery **approved** | ENGINEERING VERIFIED; EXTERNAL EVIDENCE REQUIRED | PDPC partial NRIC masking; no full NRIC/FIN in any stored report (rehearsal, 11 generators); tenant isolation; Super Admin-only RBAC over HTTP; retention report | PDPA / DPO approval, security review, recovery test sign-off | DPO + security owner | Blocks |
| G8 Parallel payroll | Two consecutive cycles and annual AIS simulation show zero unexplained material differences | INTERNAL EVIDENCE; EXTERNAL EVIDENCE REQUIRED | Two-cycle rehearsals (5.9, 6.4) on disposable data: continuity, YTD, no duplication, byte-identical replay | Parallel run against a live design-partner employer's existing payroll, plus an annual AIS simulation on real data | Implementation lead + design-partner employer | Blocks |

## 5. Remaining blockers
- **G1–G8** external evidence (§4).
- **Shared database lineage:** `5ae06cfda828` versus integration head `6247da96d605`. Owner-led migration planning is
  required; never stamp or upgrade from `nikhil`.
- **Deploy pipeline:** merging to `main` auto-deploys; the `deploy_migrate.sh` orphan path still mutates while refusing.
- **Owner decisions:** Singapore hotfix policy; the §3 findings.
