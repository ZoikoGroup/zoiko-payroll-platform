# G2 — IRD / eMPF conformance test plan (DRAFT for review)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. Not accepted evidence.
**Execution:** every test in this plan is **PENDING – requires credentials** (IRD software-approval route and test data acceptance; eMPF test environment access). No results are reported because none exist yet.

## Entry criteria

1. Every document in `hk_authority_document_register.md` §2 is archived with its SHA-256.
2. An IRD-layout export exists for each form and has been checked against the archived schema. Today only the internal field map exists (`ZOIKO-HK-IR56-INTERNAL-1`), so this is an engineering task that follows step 1.
3. The eMPF connection method is decided (owner decision D-1), and test credentials are held in the secret store (`EMPF_SECRET_STATUSES = CONFIGURED_IN_SECRET_STORE`).
4. Tests run in an approved non-production environment against synthetic employees. No real HKID or member account number is used.

## IRD tests

| ID | Test | Pass criterion | Evidence to keep | Status |
|---|---|---|---|---|
| IRD-01 | Validate generated BIR56A + IR56B files against the archived XSD | 0 schema errors | validator output + file SHA-256 | PENDING – requires credentials/schemas |
| IRD-02 | IRD test-data submission for BIR56A/IR56B (software approval route) | IRD acceptance letter / approval | IRD correspondence, uploaded as HK-GATE-G2 evidence | PENDING – requires credentials |
| IRD-03 | IR56E for a new joiner likely chargeable, within 3 months of commencement | schema-valid; due date matches `ird.due_date` | file, schema result | PENDING |
| IRD-04 | IR56F for a cessation, ≥ 1 month before cessation | schema-valid; due date correct | file, schema result | PENDING |
| IRD-05 | IR56G for a departure (wireframe R6) with tax-clearance hold | schema-valid; hold created and released only with a Letter of Release | file, hold ledger | PENDING |
| IRD-06 | IR56B suppressed after IR56F for the same income (R7) | no duplicate in the file | file diff | PENDING |
| IRD-07 | IRD rejection → re-preparation → re-filing keeps the original evidence | case history shows REJECTED → PREPARED → FILED | case audit export | PENDING |
| IRD-08 | Amendment after acceptance | AMENDED case linked to the replacement | case audit export | PENDING |

## eMPF tests

| ID | Test | Pass criterion | Evidence | Status |
|---|---|---|---|---|
| EMPF-01 | Remittance file / API payload validates against the eMPF specification | 0 validation errors | validator output + SHA-256 | PENDING – requires credentials |
| EMPF-02 | Test submission accepted end to end, contribution day per `mpf_contribution_day` | ACCEPTED, then PAID, then RECONCILED | eMPF reference, reconciliation | PENDING – requires credentials |
| EMPF-03 | One employee row rejected (wireframe R10) | batch PARTIAL / REJECTED; payroll unchanged; supplementary batch on correction | eMPF response, batch history | PENDING – requires credentials. The internal behaviour is tested in G4 R10 |
| EMPF-04 | New member enrolment and termination | eMPF accepts member data | eMPF response | PENDING – requires credentials |
| EMPF-05 | Late contribution / surcharge handling | operator alert; no silent recalculation | monitoring output | PENDING |

## Exit criteria for G2

All IRD-0x and EMPF-0x tests pass, and the evidence is uploaded under HK-GATE-G2 (and HK-EMPF-CERTIFICATION for the eMPF certificate). The IRD software-approval register then reaches APPROVAL_RECEIVED with a reviewed approval document.

## Sign-off (leave blank until signed by the named person)

QA lead — Name / Role / Date / Signature: ________
Engineering lead — Name / Role / Date / Signature: ________
Payroll Operations — Name / Role / Date / Signature: ________
