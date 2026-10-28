# Mexico release gate G7 — Security / privacy — evidence draft

**DRAFT assembled by engineering (completion W8, 2026-10-27). This is not a signature and does not sign the gate.** G7 is signed only when its evidence pack is uploaded as a source artifact tagged `MX-GATE-G7` and reviewed by a second Super Admin (Readiness tab).

## 1. Produced by engineering

- Identifier masking and log redaction (Phase 10c; `test_mexico_identity_token_key.py`, `test_mexico_employee_validation.py`); no full RFC / CURP / NSS in any generated report (scan in `test_mexico_report_generators.py`); the printed receipt is the one allowed exception, rendered on demand and never stored (`test_mexico_cfdi_receipt.py`)
- Credential references only (`gcp-sm://`; `test_mexico_credential_refs.py`); the route registry classifies every Mexico route (`docs/privacy/route_policy_inventory.csv`)
- Retention: no period chosen by the platform; nothing purged without an approved policy (`test_mexico_retention.py`)
- Full backend suite at the end of W5 (2026-10-27): 7,561 passed, 120 skipped, 2 xfailed; only the known local-only failures and one intermittent communications test (`MEXICO_COMPLETION_PROGRESS.md`, End of W5)

**Final mile (2026-10-28) — what the new tooling now produces for this gate:**

- Report MX-IDENTIFIER-ACCESS-AUDIT: every render of the full-identifier CFDI receipt (who, when)
- `ZP_PRIV_REVIEW_PACKETS.md` (13 packets, W4-3b first) and the `payslip_items.compliance_fields` note
- CSD custody interface (key never returned) and Super Admin CSD expiry alerts; XML store contract
- `INCAPACITY_RECORD_PROPOSAL.md` (health data — ZP-PRIV and legal, nothing built)
- Configuration re-audit `MEXICO_SUPER_ADMIN_CONFIG_AUDIT.md`: Mexico rows can no longer be moved through another pack; MX gate / decision evidence is governed (no replacement after review); D-26, D-27

## 2. Checklist items a code check confirms (state is live in Readiness → Gate checklists)

- None: every item of this gate needs a person or an external party.

## 3. Not confirmed by code — evidence a person prepares or signs, or an external party produces

- [PRE-PILOT] CSD and PAC credentials held only as secret references; rotation procedure tested
- [PRE-PILOT] RFC / CURP / NSS / CLABE and CFDI XML masked in logs and error reports (Phase 10c, reviewed by the ZP-PRIV owner)
- [PRE-PILOT] Q9 (identifiers at rest) recorded by the security lead (MX-DECISION-Q9)
- [PRE-PILOT] Hosting and cross-border transfers recorded (MX-DECISION-HOSTING); the pilot organisation's data region set accordingly (organisations default to EU)
- [PRE-PILOT] Retention decisions recorded (MX-DECISION-RETENTION-PERIOD, MX-DECISION-RETENTION-END) or explicitly deferred past the pilot
- [PRE-PILOT] Privacy notice (aviso de privacidad) and processor terms in place
- [PRE-PILOT] Backup and restore procedure tested for a Mexican tenant
- The G7 signature itself: the evidence pack reviewed and accepted by the gate owner, then a second Super Admin

## 4. Open decisions and gaps this gate waits on

- Q9 (identifiers at rest), hosting, retention period and end; **ZP-PRIV reviews pending by Rugvedh**: the sources gate (52af6eb), W4-2 report route, W4-3b receipt route (raw identifiers), W5-1 / W5-3 Super Admin routes, W5-2 generic-edit and hotfix refusal — the first four already merged (PR #134)

Source of the checklist: `docs/mexico/release-gates/G7/CHECKLIST.md`. Decisions: `docs/mexico/DECISIONS_PENDING.md`. Gaps: `docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md`.
