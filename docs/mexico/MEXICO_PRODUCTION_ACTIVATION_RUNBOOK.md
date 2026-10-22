# Mexico — production activation runbook

**For:** the two Super Admins and the release owner who will switch Mexican payroll on in production, and the engineer who changes the deployment.

**Today.** Mexico is built through Phase 10 and **dormant** in production: every Mexico route and screen refuses, no organisation can become Mexican, and every Mexican calculation is blocked because no statutory content is transcribed. Nothing in this runbook has been done.

Follow the steps **in order**. Each one has a check; do not continue until it passes.

## 1. Sources and content

| Step | Check |
|---|---|
| 1.1 Save every source the gates need (see `release-gates/G1…G8/CHECKLIST.md`) under `docs/mexico/sources/`, with `SOURCES_MANIFEST.csv` updated (SHA-256, retrieval date, version header). Replace S22, which is saved but the wrong version. | Every source a launch gate names has status `VERIFIED` in the manifest. |
| 1.2 Transcribe the content (ISR tariffs and subsidy, UMA, minimum wages, IMSS branches and CEAV, INFONAVIT, each enabled state's ISN, labour floors, special-pay rules) into the Mexico packs. Every row is source-linked. | The pack's activation readiness (Readiness G1–G8 tab) shows content exact and every row source-linked. |
| 1.3 Move each pack Draft → In Review → QA → Approved → Active. A Super Admin who edited a row cannot approve it. | Each launch pack is Active. |
| 1.4 Load the CFDI schema and catalog releases from S28 / S30 and make them Active. | CFDI release Active. |
| 1.5 Run and approve the golden cases for each gate. | Golden runs PASS. |

## 2. Release gates and legal decisions

| Step | Check |
|---|---|
| 2.1 For each gate G1–G8, complete its checklist and sign it as described in `release-gates/README.md`: upload the evidence pack, and a second Super Admin marks it reviewed. | All 8 gates show **SIGNED** on the Readiness G1–G8 tab. |
| 2.2 Record the legal decisions: retention period (`MX-DECISION-RETENTION-PERIOD`), deletion vs anonymisation (`MX-DECISION-RETENTION-END`), hosting and cross-border transfers (`MX-DECISION-HOSTING`). | Each shows RECORDED. |
| 2.3 Propose and approve (two Super Admins) a retention period for each record category. | No category is BLOCKED_UNDECIDED. |

## 3. External setup

| Step | Check |
|---|---|
| 3.1 Contract the PAC; store its credentials and each employer's CSD as secret references only. | The PAC test stamp, cancel and status query pass (G1, G6). |
| 3.2 Set `MX_IDENTITY_TOKEN_KEY` in Secret Manager. There is no fallback outside development or test. | The backend starts with the key present. |
| 3.3 Obtain the employer bank's SPEI bulk-file specification, if a bank file is wanted. Until then, payments use the worklist. | Decided and recorded. |
| 3.4 Rugvedh (ZP-PRIV owner) has reviewed the Phase 10c redaction rules and the retention purge item. | Recorded in the release checklist. |

## 4. Switching on

| Step | Check |
|---|---|
| 4.1 A Super Admin moves the Mexico service registry **PLANNED → AVAILABLE**, with a reason. The platform refuses this unless every gate is SIGNED. | Registry AVAILABLE. |
| 4.2 The engineer sets `MX_TENANT_ONBOARDING_ENABLED=true` in the production environment and redeploys. This is a deployment change, reviewed like any other. | `/api/payroll/mexico/...` no longer answers with the dormancy refusal. |
| 4.3 Onboard the **first** organisation as an EVALUATION workspace and run the parallel payroll (G8) there before any live run. | G8 evidence. |
| 4.4 Then move that organisation to a live workspace. | First live run approved by two people. |

## 5. Rollback

- Unset `MX_TENANT_ONBOARDING_ENABLED` and redeploy. Every Mexico route refuses again at once, and no data is deleted.
- Move the registry back to PLANNED, with a reason.
- Anything already transmitted (CFDI, filings, payments) is resolved with `MEXICO_UNKNOWN_STATE_RUNBOOK.md`. Nothing is reversed automatically.
