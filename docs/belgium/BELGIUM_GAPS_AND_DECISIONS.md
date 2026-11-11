# Belgium (BE) — Gaps and Decisions Register

Spec: docs/belgium/Zoiko_Payroll_Belgium_Engineering_Implementation_Wireframe_v1.0.docx (ZP-BE-ENG-001 v1.0, authoritative; file name kept as-is)
Plan: docs/belgium/BELGIUM_IMPLEMENTATION_PLAN.md
Created: Phase 0, 2026-11-11, against commit 1af3d44 (branch nikhil). Alembic head: efc56f3235e2.

This register is authoritative for open gaps and approved decisions. A gap is closed only by recorded evidence (signed content, specialist confirmation or an approved decision), never by an engineering assumption.

## Gaps

| ID | Status | Description |
|---|---|---|
| G-01 | OPEN | Calculation order not consolidated in the spec; the derived order in plan §8 needs Belgian specialist confirmation. |
| G-02 | OPEN | No rounding rules in the spec. |
| G-03 | OPEN | Annex III professional-withholding tables / formulas absent. |
| G-04 | OPEN | Work-bonus (social and fiscal) parameters absent. |
| G-05 | OPEN | Wage-moderation, 1.60% special-contribution threshold and fund rates absent. |
| G-06 | OPEN | Special social security contribution (BSSC) not mentioned in the spec. |
| G-07 | OPEN | Manual-worker guaranteed-salary day bands absent. |
| G-08 | OPEN | ONSS rate files and authority schemas (Dimona, DmfA, FinProf, Belcotax) are external. |
| G-09 | OPEN | Public-holiday dates and substitution rules absent. |
| G-10 | OPEN | Index-centime mechanics unspecified. |
| G-11 | OPEN | Pay-frequency scope not defined. |
| G-12 | OPEN | Definition of "high-risk" change for four-eyes not defined. |
| G-13 | OPEN | Legal language rules (nl/fr/de for employment documents) not defined. |
| G-14 | OPEN | Spec /be/ API paths vs repository route convention (resolved in practice by D4). |
| G-15 | OPEN | Benefit-in-kind, meal-voucher and ecocheque values absent. |
| G-16 | OPEN | KBO/BCE, ONSS and NISS format / check-digit rules unverified. |
| G-17 | OPEN | (D7) BSSC has no spec requirement ID. Its content key must reference "external specialist confirmation, G-06", not a BE-xxx ID. The engine only emits the BE_BSSC_PENDING exception and never computes it. |
| G-18 | OPEN | (D4) The run lifecycle mapping must show where commit idempotency and four-eyes for high-risk changes are enforced. Acceptance item for Phase 8. If the existing lifecycle lacks either control, stop and report in Phase 8; do not add it silently. |
| G-19 | OPEN (expected) | (D8) be_rounding_* rows have no published source and stay blocked until a specialist signs them. This is expected. |
| G-20 | OPEN | The spec §3 figures are Draft seed content only, labelled "[PENDING G1]", and are never used as code constants. |
| G-21 | OPEN | Belgian statutory retention periods for payroll/social documents not in spec; BE employee deletion blocked until specialist-approved retention rules exist. |

## Decisions

| ID | Status | Description |
|---|---|---|
| D1 | DECIDED | Poland (ZP-PL-ENG-001) generation-2 pattern. |
| D2 | DECIDED | Dedicated payroll_be_* tables (no be_* columns on payroll_employees or payroll_employee_statutory_profiles). |
| D3 | DECIDED | Joint Committee / CBA packs reuse payroll_collective_agreements. |
| D4 | DECIDED | Routes under /api/payroll/belgium and /api/super-admin/compliance/belgium; spec simulate/commit map onto preview_payroll_run and the run lifecycle. |
| D5 | DECIDED | Thin BE frontend files using the shared JP/NZ helpers. |
| D6 | DECIDED | First scope = private-sector ordinary payroll; special regimes and termination block. |
| D7 | DECIDED | BSSC not implemented; pending content key + exception, awaiting specialist confirmation (see G-17). |
| D8 | DECIDED | Rounding as signed pack text rows (be_rounding_*), blocking until signed (see G-19). |
| D9 | DECIDED | Authority transmission adapters stubbed behind gate G3; builders + validation built. |
| D10 | DECIDED | English operator payslip first; nl/fr/de as content keys. |
| D11 | DECIDED | Roadmap P1–P10 (plan §9). |
| D12 | DECIDED | External statutory content supplied by a Belgian specialist. |
| D13 | DECIDED | payroll_be_payment_batches / _items mirroring the Netherlands tables, using bank_export/sepa_pain001.py unchanged. |
| D14 | DECIDED | be_identifiers.py with its own BE_IDENTIFIER_KEYRING / BE_IDENTIFIER_FINGERPRINT_KEY settings. |
| D15 | DECIDED | Employer substitute holidays stored in payroll_holidays with category "Substitute", audited via payroll_tax_configuration_audit. |

## Notes

- (Phase 1) Lowercase "be" resolves to BE through the shared case-insensitive code match in core.jurisdiction.get_jurisdiction_code (same as every country, e.g. "pl" -> PL). There is no bare "be" name alias.
- (Phase 1) The BE schema examples ("0123.456.789", "1234567-89") are input-shape examples required by the shared validator (validate_tax_identifiers quotes them in its format message), not verified formats. G-16 stays open.
- (Phase 1) Frontend production build not verified in Phase 1 (vite build runs out of memory on the development machine). It must be verified before Phase 3.
- (Phase 1) Backend tests ran on Python 3.11. The project requires 3.12+; the environment must be fixed before Phase 5.
