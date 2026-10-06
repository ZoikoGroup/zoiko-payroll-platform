# Singapore — External Evidence, Decision & Deploy-Owner Handoff

Status date: 2026-09-29 · Engine `SG-2026.10` · Alembic head `445abd6a9083`

This document lists what the business must obtain, and who must obtain it, before Singapore can go live. Engineering can build the mechanism that records this evidence, but it cannot supply the evidence itself.
**No gate has evidence today.** Every G1–G8 gate is `EVIDENCE_REQUIRED`, except G3, which is `BUSINESS_DECISION_REQUIRED`. D1–D3 are all `BUSINESS_DECISION_REQUIRED`.
Code existing for a gate is **not** evidence for it.

The gate and decision definitions live in one place: `SG_PRODUCTION_GATES` and `_pending_decisions` in `backend/app/modules/payroll/engine/jurisdictions/singapore/statutory_summary.py`. Super Admin → Singapore → Readiness shows their live state.

---

## 1. How evidence is recorded (all gates and decisions)

1. **Register.** Go to Super Admin → Compliance → Source Evidence and create an artifact:
   - form number `SG-GATE-G<n>` or `SG-DECISION-D<n>`;
   - agency, title, source URL / reference and publication date.
2. **Upload** the signed document. The server computes and stores the SHA-256. A typed or client-supplied hash is never accepted as evidence.
3. **Review.** A **different** Super Admin records the outcome. Use the Readiness tab's "Review…" control, or `PUT /api/super-admin/compliance/source-artifacts/{id}/sg-review`.
   - **ACCEPTED**: optional notes, and an optional *valid until* date (it must be in the future).
   - **REJECTED**: notes are required.

   The outcome is refused when:
   - no file has been uploaded;
   - the reviewer is the person who registered the artifact;
   - the artifact is superseded or is already reviewed, because a review outcome is never replaced.

   A rejected artifact can't be accepted, reviewed again or given a new file afterwards.
4. **Lifecycle.** The state is derived from the record and is never typed in:

   | State | Meaning | Next action |
   |---|---|---|
   | `EVIDENCE_REQUIRED` | No current (non-superseded) artifact | Register the artifact and upload the document |
   | `SUBMITTED` | Registered, no document uploaded | Upload the signed document |
   | `UNDER_REVIEW` | Uploaded (server SHA-256), awaiting a distinct reviewer | A second Super Admin accepts or rejects |
   | `PASS` | Accepted: creator on record, a different reviewer, file with server hash, not superseded, within its validity date | None |
   | `REJECTED` | The reviewer rejected it (notes shown) | Register a corrected artifact, upload it, supersede the rejected one |
   | `EXPIRED` | Accepted, but past its *valid until* date | Register current evidence and supersede the expired one |

   The readiness view shows for each gate:
   - the required artifact and its acceptance criterion;
   - the submitted artifact id, the reviewer and review date;
   - the expiry date and the notes;
   - the blocking reason and the next action.

   Each outcome is an immutable `payroll_tax_configuration_audit` row on the artifact. No new table or column was added.
5. **Correction.** Once an artifact has been reviewed, its file can never be replaced. To correct it:
   - register a new artifact with the **same** form number and upload the corrected file;
   - supersede the old artifact. Use the Readiness tab's "Supersede with #n" button, or `PUT /api/super-admin/compliance/source-artifacts/{id}/supersede` with body `{"replacementId": n}`. This requires a Super Admin.

   What supersession does:
   - the old artifact, its file and its review are **kept**, and it is shown as `SUPERSEDED`;
   - the action is audited (`source_artifact` update, "superseded by #n");
   - the gate returns to pending until the replacement is reviewed by a different Super Admin. Supersession can only withdraw acceptance, never grant it.

   Supersession is refused when:
   - the replacement has a different form number;
   - an artifact would supersede itself;
   - the old artifact is already superseded;
   - the replacement is itself superseded;
   - the artifact is not Singapore gate or decision evidence.

---

## 2. G1–G8 production gates

Every gate has the same reviewer requirement: a Super Admin other than the one who created the artifact.

| Gate | Requirement | Authority | Artifact required | Acceptance criterion | Form code | Owner | Status today | Blocks go-live | Next action |
|---|---|---|---|---|---|---|---|---|---|
| G1 | CPF content certification | Independent reviewer; CPF Board sources | Signed independent comparison report | An independent reviewer signs that the CPF rates, ceilings, age bands, OW/AW treatment and golden vectors match CPF Board publications | `SG-GATE-G1` | Statutory compliance owner | EVIDENCE_REQUIRED | Yes | Commission the independent review against the Draft v1.1 pack and the 37 golden vectors |
| G2 | CPF operations (EZPay file, payment, reconciliation) | CPF Board (EZPay / Corppass) | CPF acknowledgement and payment reconciliation | A CPF acknowledgement of a real submission is reconciled to the payroll register with zero unexplained variance | `SG-GATE-G2` | Employer payroll operations | EVIDENCE_REQUIRED | Yes | Complete the Corppass / EZPay set-up; submit the first cycle; reconcile |
| G3 | IRAS AIS (YA2027 model, route, amendments) | IRAS | Signed submission-mode decision, plus an acknowledged original and modification | D1 is recorded, then IRAS acknowledges an original and an amended submission (or export upload) | `SG-GATE-G3` | Product owner | BUSINESS_DECISION_REQUIRED (becomes EVIDENCE_REQUIRED once D1 is recorded) | Yes | Record D1 first |
| G4 | IR21 tax clearance | IRAS | Guidance review; acknowledged filing | A compliance review of the IR21 workspace against IRAS guidance, plus one acknowledged IR21 | `SG-GATE-G4` | Statutory compliance owner | EVIDENCE_REQUIRED | Yes | Review the IR21 workspace; file the first real case |
| G5 | Foreign workforce (levy billing, LQS / PWM) | MOM | Levy-bill reconciliation; published values | A MOM levy bill is reconciled to computed FWL; the section 4 data items are resolved or formally scoped out | `SG-GATE-G5` | Statutory compliance owner | EVIDENCE_REQUIRED | Yes | Obtain the first MOM levy bill; close the section 4 items |
| G6 | Labour pay (Employment Act) | MOM / counsel | Legal review memo | Counsel signs a memo covering the Employment Act pay, overtime and deduction rules the product applies | `SG-GATE-G6` | Legal and compliance owner | EVIDENCE_REQUIRED | Yes | Instruct counsel |
| G7 | Security / privacy (PDPA, NRIC/FIN) | PDPC framework (DPO) | DPO sign-off; security review; recovery test | The DPO signs; the security review has no open high findings; the backup-restore rehearsal is evidenced | `SG-GATE-G7` | DPO and security owner | EVIDENCE_REQUIRED | Yes | Book the DPO and security review; run the runbook §C restore rehearsal |
| G8 | Two-cycle parallel payroll and AIS simulation | Design-partner employer | Parallel-run reconciliation report | Two consecutive cycles reconcile against the incumbent payroll, and an AIS simulation is included | `SG-GATE-G8` | Implementation lead | EVIDENCE_REQUIRED | Yes | Sign a design partner; run two cycles |

---

## 3. D1–D3 owner decisions

Nothing in the product chooses these options. The value shown as "in force" is the product default, what it does today; it is not a recorded decision.

**How to record a decision:**
1. The decision maker uses **Record decision** on the Readiness tab (or `POST /api/super-admin/compliance/singapore/decisions` with `{key, selectedValue, reason}`). Nothing is pre-selected. The option must be one of those listed, and a reason is required. This creates the `SG-DECISION-D<n>` artifact and an audit row holding the selected option, the decision maker and the reason. Status: `SUBMITTED`.
2. Upload the signed decision memo to that artifact. Status: `UNDER_REVIEW`.
3. A **different** Super Admin accepts it. Status: `DECISION_RECORDED`.

A memo uploaded through the generic Source Evidence screen, with no selected option recorded, never counts as a decision.

Recording a decision **never changes the behaviour in force**:
- the hotfix policy constant, the SG-only control scope and the AIS route stay as they are;
- when the recorded value differs from the value in force, the readiness view flags `inForceDiffers` and states the change needed.

| Decision | Question | Options | In force today | Status | Effect once recorded |
|---|---|---|---|---|---|
| D1 | IR8A / AIS submission mode offered by the product | EXPORT_ONLY · API_SUBMISSION · BOTH | EXPORT_ONLY (built) | BUSINESS_DECISION_REQUIRED | G3 moves to EVIDENCE_REQUIRED. API_SUBMISSION / BOTH also need the IRAS AIS-API 2.0 onboarding (APEX, Corppass, credentials, sandbox). None of that exists today, and it is not built |
| D2 | Singapore hotfix policy | RESTRICTED · PROHIBITED · FOLLOW_UP_REQUIRED | RESTRICTED (a distinct reviewer is required; the approver cannot be the activator) | BUSINESS_DECISION_REQUIRED | Documents the policy. Any change of policy is a code change with review |
| D3 | Scope of the Singapore-only governance controls | SG_ONLY · ALL_COUNTRIES | SG_ONLY | BUSINESS_DECISION_REQUIRED | ALL_COUNTRIES would be a separate cross-jurisdiction change. It is out of scope for the Singapore programme |

---

## 4. MOM statutory data matrix

| Item | Status | Basis | Blocks | Next action |
|---|---|---|---|---|
| Pass end-day rule on **cancellation** (S Pass, Work Permit) | AVAILABLE | MOM cancellation pages: "levy stops 1 day before cancellation". Seeded as `fwl_*_cancellation_end_day_basis = EXCLUSIVE` with SHA-256 source records | — | None |
| Part-time LQS hourly rate before 1 Jul 2026 | AVAILABLE | MOM COS 2024 factsheet (seeded) | — | None |
| Pass end-day rule on **expiry** (or no end reason recorded) | EXTERNAL_DATA_REQUIRED | Not published by MOM. A mid-month expiry is computed as BLOCKED (fail closed) | A mid-month expiry payslip | Obtain a written MOM answer; seed `fwl_s_pass_end_day_basis` / `fwl_work_permit_end_day_basis` with its source |
| Work Permit levy rates before 24 Sep 2026 | EXTERNAL_DATA_REQUIRED | The historical tables are not seeded. Earlier pay dates fail closed | Back-dated WP runs | Source the historical MOM levy tables, if back-dating is in scope |
| Foreign-worker quota tables (dependency ratios, headcount) | EXTERNAL_DATA_REQUIRED, plus a scope decision | Not seeded, and no quota check is performed. Quota is not a payroll calculation: MOM computes the employer's authoritative quota balance, and the Work Permit levy tier that depends on it is an employee input taken from MOM's levy bill | Quota compliance reporting only (not payroll) | Product owner decides whether Zoiko computes quota at all. If yes: register the MOM sector quota and headcount pages as source artifacts, then build it |
| Retail PWM 3-month averaging | **AVAILABLE, implemented** | MOM Retail Tripartite Cluster report (Aug 2025), Annex D §1–4 and footnote 2. SG-PWM-COMPLIANCE evaluates a retail shortfall against the 3-month average, using each month's own payslip: job level, gross wages, overtime hours and the MOM Gross Wage Requirement. It doesn't average months 1–2 of employment, and pro-rates an incomplete first month | Only months the source doesn't cover stay flagged: part-time months, an incomplete month other than the first, payslips calculated before this release | None |

---

## 5. Deploy-owner checklist

The steps below follow `docs/SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md`; the runbook is authoritative.

- [ ] Review the Singapore change set and merge it (engineering does not commit, push, merge or deploy).
- [ ] Review the `scripts/deploy_migrate.sh` safety fix (runbook A6).
- [ ] Confirm `alembic heads` shows a single head, `445abd6a9083`.
- [ ] Choose the deploy case:
  - **A. Shared database at `998877665544` (today's read-only observation).** A plain `upgrade head` applies the Singapore migrations. The existing orphan table `sgp_ir21_cases` (no rows) is kept; migration `f6a1` skips it (runbook §C). Never use `alembic stamp`.
  - **B. The database is already at head.** No-op.
  - **C. The database is at an unknown revision or has multiple heads.** Stop and escalate; do not stamp.
  - **D. A fresh database.** `upgrade head` from base.
- [ ] Take a backup (runbook §B) and complete the restore rehearsal (§C) **before** migrating.
- [ ] Migrate in the maintenance window (§D). Verify readiness → "Database state":
  - the database matches the alembic head;
  - no Singapore objects are missing.
- [ ] Seed the canonical Singapore pack (§E). It stays **Draft**.
- [ ] Run the golden vectors (§F): 37 are expected to pass.
- [ ] Pack approval by a second Super Admin, then activation by a **different** admin (§G–H). Do this only after G1 is PASS.
- [ ] Template promotion (§I): 11 templates, maker-checker.
- [ ] Test tenant and audit verification (§J–K).
- [ ] Switch the registry to `AVAILABLE` (§L). This is the **only** step that opens onboarding. Do it only when G1–G8 are PASS and D1–D3 are recorded.
- [ ] Monitor the first two cycles (§M). The rollback plan (§N) must be understood before §L.

---

## 6. External-action packets

This section has one packet per item that engineering can't complete. Every evidence item is uploaded the same way:
1. Go to Super Admin → Compliance → Source Evidence and register the artifact with the form code shown. Upload the file; the server records its SHA-256.
2. Review it on Super Admin → Singapore → Readiness with "Review…". The reviewer must be a Super Admin **other than** the one who registered it. Accepting can set an expiry ("valid until"); rejecting needs notes.
3. A decision (D1–D3) instead uses **Record decision** on the same page, then its signed memo is uploaded and reviewed the same way.

| Item | Owner | Authority | Request / artifact required | Where to obtain it | Configuration | Expected format | Acceptance criterion | Upload location (form code) | Reviewer | Expiry | Next action |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 CPF certification | Statutory compliance owner | Independent reviewer against CPF Board publications | Signed comparison of the CPF configuration and the 37 golden vectors | Commission the reviewer. Engineering input: `SINGAPORE_G1_CPF_INDEPENDENT_COMPARISON_PACK.md`, the Draft pack, `tests/fixtures/sg_golden/` | None | Signed PDF report | Every CPF rate, ceiling, age band and OW/AW rule matches CPF Board; every vector agrees | `SG-GATE-G1` | Second Super Admin | Set to the next CPF rate change (1 Jan 2027 tables) | Commission the review |
| G2 CPF operations | Employer payroll operations | CPF Board | CPF acknowledgement of a real EZPay submission, plus a payment reconciliation | CPF EZPay (Corppass) after the first live cycle | Employer's CSN in company compliance | CPF acknowledgement plus a reconciliation sheet (PDF) | Zero unexplained variance to the payroll register | `SG-GATE-G2` | Second Super Admin | None | Submit the first cycle |
| G3 IRAS AIS | Product owner | IRAS | D1 decision, then an IRAS-acknowledged original and amendment | myTax Portal (export route) or AIS-API (after onboarding) | D1; for API, the AIS prerequisites below | IRAS acknowledgement (PDF) | Acknowledged original plus modification for one income year | `SG-DECISION-D1`, then `SG-GATE-G3` | Second Super Admin | Per year of assessment | Record D1 |
| G4 IR21 | Statutory compliance owner | IRAS | IR21 guidance review, plus one acknowledged IR21 filing | IRAS guidance; myTax Portal filing | None | Review memo plus IRAS acknowledgement | Review signed; one acknowledged filing | `SG-GATE-G4` | Second Super Admin | None | File the first real case |
| G5 Foreign workforce | Statutory compliance owner | MOM | A MOM levy bill reconciled to computed FWL; the MOM data items resolved or scoped out | MOM levy statement (employer's MOM account) | Employees' pass and levy-tier data | Levy bill plus reconciliation (PDF) | Levy matches computed FWL; §4 items closed or scoped out | `SG-GATE-G5` | Second Super Admin | Monthly bills; set a validity date | Obtain the first levy bill |
| G6 Employment Act | Legal and compliance owner | Counsel (MOM Employment Act) | Signed legal memo on the pay, overtime and deduction rules applied | External counsel | None | Signed memo (PDF) | No open finding against the applied rules | `SG-GATE-G6` | Second Super Admin | Set to the next Employment Act amendment review | Instruct counsel |
| G7 PDPA / security | DPO and security owner | PDPC framework (DPO) | DPO sign-off, a security review and a restore-test record | DPO; security reviewer; runbook §C on production infrastructure | None | Signed PDFs | DPO signs; no open high findings; restore test passed | `SG-GATE-G7` | Second Super Admin | 12 months (recommended) | Book the reviews |
| G8 Parallel run | Implementation lead | Design-partner employer | Two-cycle parallel-run reconciliation plus an AIS simulation | A signed design partner | Partner tenant | Reconciliation report (PDF/XLSX) | Two consecutive cycles reconcile with the incumbent payroll | `SG-GATE-G8` | Second Super Admin | None | Sign a partner |
| D1 / D2 / D3 | Product / business owner | Internal decision | The selected option plus the reason (Record decision), then a signed memo | The decision maker | None (behaviour isn't changed by recording) | Signed memo (PDF) | One of the listed options, with a reason; accepted by a second Super Admin | `SG-DECISION-D1` … `D3` | Second Super Admin | None | Decide |
| AIS-API 2.0 credentials | Product owner, then deploy / security owner | IRAS (APEX), Corppass | APEX onboarding, the API specification, client credentials, employer Corppass authorisations, sandbox pass | IRAS APEX; Corppass | Credentials in a secrets store, never in the database or repository; D1 = API_SUBMISSION or BOTH | IRAS-issued credentials | A sandbox original plus amendment accepted | The specification as a source artifact; the sandbox evidence under `SG-GATE-G3` | Second Super Admin | Per IRAS credential validity | Only if D1 chooses the API |
| MOM expiry end-day rule | Statutory compliance owner | MOM | A written MOM answer: is the pass expiry day levied? | MOM enquiry | Seed `fwl_s_pass_end_day_basis` / `fwl_work_permit_end_day_basis` from the answer | MOM letter or email (PDF) | States INCLUSIVE or EXCLUSIVE | A source artifact linked from the pack rows | Pack maker-checker | None | Ask MOM |
| MOM WP levy before 24 Sep 2026 | Statutory compliance owner | MOM | The historical Work Permit levy tables | MOM publications / enquiry | Seed the effective-dated `fwl_wp__*` rows | Official table (PDF) | Effective dates and sector tiers stated | Source artifact plus pack rows | Pack maker-checker | None | Only if back-dated payroll is in scope |
| Production deployment | Deploy owner | — | Merge, migrate and seed per the runbook | — | — | — | Runbook sections A–O complete | — | — | — | See `SINGAPORE_RELEASE_CHECKLIST.md` |
