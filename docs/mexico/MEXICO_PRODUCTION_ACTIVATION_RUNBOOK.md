# Mexico — production activation runbook

**For:** the two Super Admins and the release owner who will switch Mexican payroll on in production, and the engineer who changes the deployment.

**Today.** Mexico's buildable scope is complete through Phase 10 and **dormant** in production: every Mexico route and screen refuses, no organisation can become Mexican, and every Mexican calculation is blocked because no statutory content is transcribed. Nothing in this runbook has been done.

Follow the steps **in order**. Each one has a check; do not continue until it passes.

## 0. Buildable scope complete, not code-complete


| Integration code still to write | Waits for | Today |
|---|---|---|
| Statutory content transcription into the packs, plus golden vectors for every gate | The sources (S1–S33; S22 is the wrong version) | Every Mexican calculation is BLOCKED (empty content). |
| CFDI 4.0 + Nómina 1.2 XML builder and XSD validation; CSD signer | S28 (Nómina 1.2 catalogs + `nomina12.xsd`), S30 (CFDI 4.0 Anexo 20), S4; Secret Manager for the CSD | `mexico_cfdi_builder.py` refuses (`MX_CFDI_BUILDER_BLOCKED`, `MX_CSD_SIGNING_BLOCKED`). |
| PAC adapter (one class behind `PacAdapter`), plus its retry thresholds | The chosen PAC and its API documentation | `mexico_pac._ADAPTERS` is empty (`MX_PAC_NOT_CONFIGURED`). |
| SPEI bulk payment file generator | The employer bank's SPEI file specification | Payments are a Zoiko worklist, not a bank file (Phase 10a). |
| IDSE / SUA / SIPARE file layouts | S12, S13, S16 layouts | IMSS movements and payments are Zoiko worklists (Phase 8). |

Each item above is built, tested and reviewed like any other phase before the step that needs it.

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

## 4. Switching on (two levels, Phase 10e)

| Step | Check |
|---|---|
| 4.1 The engineer sets `MX_TENANT_ONBOARDING_ENABLED=true` in the production environment and redeploys. It is a **kill switch only**: with nothing else, every Mexico route still refuses. | Mexico routes still refuse. |
| 4.2 **Pilot.** With G1, G2, G4, G5 and G7 SIGNED, Q9 and the hosting decision RECORDED and the identity key configured, a Super Admin proposes a pilot grant for one named EVALUATION organisation (reason, scope, expiry of at most 120 days); **a different Super Admin approves it**. | Only that organisation opens, with the PILOT banner. |
| 4.3 Run the parallel payroll in the pilot organisation. Its output is **non-binding**: CFDI only through the PAC sandbox, no payments, no authority filings, every payslip watermarked. Produce the G3, G6 and G8 evidence and sign those gates. | G3, G6, G8 SIGNED. |
| 4.4 **General availability.** A Super Admin moves the registry **PLANNED → AVAILABLE**. The platform refuses unless all eight gates are SIGNED, Q9 is RECORDED, the identity key is configured and new Mexican organisations are **not paused** (§6). | Registry AVAILABLE. |
| 4.5 Create the **live** organisation, then copy the pilot's master data into it with the governed copy: one Super Admin proposes, a different one approves; read its diff report. Payroll results are never copied. | Diff report shows no difference. |
| 4.6 Run the go-live checks (§6) on the live organisation's first cycle. | All §6 checks done. |

## 5. Rollback

- Unset `MX_TENANT_ONBOARDING_ENABLED` and redeploy. Every Mexico route refuses again at once, and no data is deleted.
- Move the registry back to PLANNED, with a reason.
- Anything already transmitted (CFDI, filings, payments) is resolved with `MEXICO_UNKNOWN_STATE_RUNBOOK.md`. Nothing is reversed automatically.

## 6. Go-live checks (real filings and payments)

These are possible only after general availability, because the pilot never files or pays. They are checked here, not as gate evidence. Each one is resolved to a final outcome with `MEXICO_UNKNOWN_STATE_RUNBOOK.md`.

- [ ] The first real IDSE filing (alta) accepted (G2)
- [ ] The first INFONAVIT liability filed and paid through SUA / SIPARE (G3)
- [ ] The first ISN return filed and accepted, per enabled state (G4)
- [ ] The first SAT ISR declaration and payment recorded (G1, G6)
- [ ] The first salary payment batch released by a second person and every item resolved (G6)
- [ ] The first production CFDI stamped by the production PAC (G1)

### When a go-live check fails

A go-live check fails when a real filing or payment is rejected, stays UNKNOWN past its runbook window, or produces a figure the authority, the bank or the PAC disagrees with.

| Step | Who | What |
|---|---|---|
| 1. Contain | The operator who saw it | Resolve the object with `MEXICO_UNKNOWN_STATE_RUNBOOK.md`. Never retry automatically, never send a second filing or payment, never edit the payslip. Record the object id, the reference and the authority's message in the incident log. |
| 2. Decide | **The release owner, with the two Super Admins who signed the gate the check belongs to** | Is it this employer's data (fix the data) or Zoiko's content or code (a defect)? If Zoiko's, the gate's signature is reopened: its evidence artifact is superseded until the fix is proven again. |
| 3. Pause new organisations | Two Super Admins, on the release owner's decision | **Pause new Mexican organisations** (Phase 10g): one Super Admin proposes PAUSE with a reason (Super Admin → Mexico → Readiness G1–G8 → **New Mexican organisations**), **a different one approves** — audited. While paused, **no organisation can become Mexican** (the country-change and company-jurisdiction gates refuse with the pause message) and **no pilot grant can be approved**; organisations that are **already Mexican keep running**, the affected one included. Only if the failure makes it unsafe for live employers to continue, also move the registry **AVAILABLE → PLANNED** (closes every live Mexican organisation), or as a last resort the kill switch (`MX_TENANT_ONBOARDING_ENABLED`). |
| 4. Support the affected employer | The release owner and the employer's payroll owner | Agree, in writing, what the employer files or pays **outside Zoiko** to meet the statutory deadline (the authority's portal, the bank, the PAC). Zoiko records those references afterwards as the resolved outcome. Communicate the cause, the workaround and the expected fix date. |
| 5. Fix and prove | Engineering, then two Super Admins | Fix through a normal PR (tests, PostgreSQL, browser). Re-run the failed check, re-sign the reopened gate with new evidence, and only then move the registry back to AVAILABLE (step 4.4). |
| 6. Close | The release owner | Record the closure in the incident log and in `PRODUCTION_STATE.md`. |

Nothing is reversed automatically, and no data is deleted. The pause refuses only an organisation **entering** Mexico (with the pause message) and pilot approvals; if the registry is also moved to PLANNED, every Mexico route returns the same coded refusal an employer sees when Mexico is closed.

**Resuming:** when the fix is proven (step 5), one Super Admin proposes RESUME and a different one approves it. General availability cannot be opened (step 4.4) while new organisations are paused — "not paused" is a general-availability precondition (Phase 10g).
