# G7 — Hong Kong launch approval sheet (DRAFT — every sign-off blank)

**Status:** DRAFT — Zoiko internal. **Launch is not approved.** Nobody has signed. Do not sign until every gate below is PASS in the product: an independent Super Admin has accepted its evidence.
**Gate:** HK-GATE-G7 — "Product, Engineering, QA, Payroll Operations, Security/Privacy and local statutory reviewer approve production activation" (wireframe v1.0 §16).
**Owner-controlled counterpart:** `docs/HONG_KONG_RELEASE_EVIDENCE/G7/LAUNCH_APPROVAL_FORM.md` (86840c5d…) and `G7_LAUNCH_CHECKLIST.md` (7b82bcd9…). Use one form or the other, not both.

## Evidence each approver relies on

| Gate | Draft evidence (this folder) | In-product state on 2026-10-13 |
|---|---|---|
| G1 Statutory content | `../G1/G1_statutory_content_review_memo.md`, `../G1/G1_governed_values_worksheet.csv` | EVIDENCE_REQUIRED (draft submitted only in the scratch environment) |
| G2 Authority conformance | `../G2/hk_authority_document_register.md`, `../G2/G2_conformance_test_plan.md`, `../G2/authority_documents.csv` | EVIDENCE_REQUIRED — PENDING, requires credentials |
| G3 Parallel payroll | `../G3/G3_parallel_payroll_reconciliation.md` | EVIDENCE_REQUIRED — PENDING, requires two real cycles |
| G4 Edge cases | `../G4/G4_edge_case_test_report.md`, `../G4/G4_test_run_output.txt` | EVIDENCE_REQUIRED (tests: 50/50 PASSED; all 10 matrix rows end to end) |
| G5 Security / privacy | `../G5/G5_security_privacy_assessment.md`, `../G5/G5_retention_deletion_policy_draft.md`, `../G5/G5_privileged_access_test_run_output.txt` | EVIDENCE_REQUIRED (tests 41/41; findings F-1, F-3, F-7, F-8, F-9 closed; F-2, F-4, F-5, F-6 open, design notes for F-4/F-5/F-6 in ops/) |
| G6 Operations | `../G6/G6_operations_runbook_cover.md`, `../G6/G6_contribution_day_calendar_2026_27.json` plus the owner pack `G6/` | EVIDENCE_REQUIRED |
| Owner decisions D-1 … D-11 | `../decisions/D-*_decision_record.md` | OPEN |
| Production verification | `../ops/HK_production_readonly_verification_instructions.md` | EVIDENCE_REQUIRED |
| D-5 identity key | `../ops/HK_IDENTITY_TOKEN_KEY_provisioning.md` | not configured |

The product enforces these gates: the service registry cannot be made AVAILABLE, and packs cannot go Active, until they are met. This sheet records the human approval; it does not replace the product checks.

## Approvals (leave blank)

| Role | Name | Date | Decision (approve / reject + conditions) | Signature |
|---|---|---|---|---|
| Product owner | ________ | ________ | ________ | ________ |
| Engineering lead | ________ | ________ | ________ | ________ |
| QA lead | ________ | ________ | ________ | ________ |
| Payroll Operations lead | ________ | ________ | ________ | ________ |
| Security / Privacy lead | ________ | ________ | ________ | ________ |
| Local statutory reviewer (Hong Kong) | ________ | ________ | ________ | ________ |

After all six sign: upload this sheet under `HK-GATE-G7`. A Super Admin other than the uploader reviews it.
