# Mexico (MX) — Phase 8 Plan: Authorities — IMSS movements / IDSE, SUA and SIPARE, INFONAVIT, ISR remittance, state ISN

Spec ZP-MX-ENG-001 v1.0:
- §8 (MX-023–MX-026), §10 (MX-031–MX-033), §14 (MX-042–MX-044) and §15 (MX-045–MX-047);
- implementation plan v1.1 §11;
- the Phase 6 reset rule ("Phase 8 must register in `run_downstream_actions`").

**Base.** `main` = `b041ead` (PR #109, Phase 7 `9e00a20`), with a single Alembic head, `d8b3e5f1a2c7`. PR #109's deploy run `39200794145` was green at every step (test, single-head, SSH deploy with `deploy_migrate.sh` and head verification, schema drift), and frontend build `39200794149` was green, so production should be at `d8b3e5f1a2c7`. Confirm with `alembic current`; the job logs need admin rights.

**Status (2026-10-19).** Built on `nikhil` and staged — see `MEXICO_PHASE_8_IMPLEMENTATION_REPORT.md`. You said "start implementing next phase" without answering D1–D12, so the build follows every recommendation in §12 (D1 file-export only; D12 on-request, audited worklist). Each remains yours to change.

**Ground rules (unchanged):**
- source wins and fail closed;
- no statutory value, layout or deadline is inferred;
- seeds stay Draft and nothing is set Active by code;
- zero behaviour change for other jurisdictions;
- the migration is additive and guarded;
- Mexico stays dormant behind `MX_TENANT_ONBOARDING_ENABLED`.

## 1. What Phase 8 is — split explicitly

### Buildable now — needs no layout, deadline, credential or integration choice

| # | Item | What it does |
|---|---|---|
| B1 | **IMSS movements from committed events** (MX-025) | **Sources:** an *alta* from the employee's first committed run on an IMSS registration; a *modificación de salario* from a committed change in `payroll_mx_sbc_history` (`sbc_total` differs from the previous committed row for the same employee and registration); a *baja* only from a recorded end of employment (§4.1, D2). **Records:** each movement carries its source row, the event date, the SBC and an idempotency key, so the same committed event can never produce two movements. Nothing is generated from a preview, a Draft run or an uncommitted change. |
| B2 | **Due-date tracking** | Every movement, liability and return has `due_date` and a `due_rule_ref`. The date is computed **only** from an Active content row (the rule plus, for business days, a sourced holiday calendar). Until that row exists the item is `DUE_DATE_UNSOURCED`: shown in amber, never defaulted (D3). Overdue, due-soon and filed-late states follow from the date. |
| B3 | **Authority liability ledger** | One row per authority × registration / state × period, aggregated **only** from committed rows: IMSS branch lines (incl. CEAV and the INFONAVIT 5% employer line), withheld ISR and INFONAVIT credit amortisation from the committed payslip snapshot, and ISN liabilities. Each contributing row is linked in a sources table that is unique per source row, so nothing is counted twice and every liability traces back to payslips. States: ACCRUED → DUE → FILED → PAID → RECONCILED, plus UNKNOWN. **Payment is recorded evidence** (reference + document); no money moves (Phase 10). |
| B4 | **SUA reconciliation workflow** (MX-033, MX-042) | A per-registration period: Zoiko's per-worker × per-branch totals (IMSS branches, RCV, INFONAVIT 5%, credit amortisation) against SUA's figures, which the operator enters through a **Zoiko-defined template** with the SUA output attached as evidence (until the S12 layout is sourced, D5). **Every** non-zero difference is BLOCKING until it has an explanation (reason code + text), and a second person approves it (four-eyes, D6). A period becomes RECONCILED only when no difference is open. The tolerance is zero (D5). |
| B5 | **ISN return records** (MX-046) | One return per state × period, built from that state's committed `payroll_mx_isn_liabilities`, with reconciliation from employee/location detail → return → ledger. Statuses DRAFT → FILED → ACCEPTED / REJECTED, plus UNKNOWN. Amendments are new rows linked by `amendment_of_id`; a filed return is never edited. Only states with an Active ISN pack can have a return (MX-045, already enforced in the Phase 5 calculation). |
| B6 | **ISR remittance record** | The SAT_ISR liability per organisation × month carries the declaration / payment reference and evidence. It has no separate table: the liability *is* the remittance record. |
| B7 | **UNKNOWN rule for any transmission** (MX-043, MX-062) | Any step that leaves Zoiko (an export the operator uploads, or later an integrated call) is a *transmission* with an idempotency key. If the outcome is not known, the item is UNKNOWN, never FAILED. Re-sending needs a recorded status check first (FOUND with the authority's reference, or NOT_FOUND), then an operator-confirmed retry that reuses **the same record, payload and key** — the Phase 7 rule. Nothing is ever automatic. |
| B8 | **Reset registration** | `run_downstream_actions` gains authority reasons (§6). Reset is refused once a movement, return, SUA period or liability that includes the run has been exported / filed / paid / is UNKNOWN. Untransmitted drafts are withdrawn on reset and recomputed. |
| B9 | **Operator and Super Admin UI** | The Social Security Center (spec §14 cards except SIPARE and work-risk, which are blocked); ISN returns; the authority liability ledger; the run "Authorities" badge reading real state; a Super Admin read-only overview with the blocks. |

### Blocked — not built in Phase 8; each needs something only you (or a source) can provide

| # | Item | Blocked on |
|---|---|---|
| X1 | **IDSE / SUA / SIPARE file layouts.** Generating the real IDSE movement file, the SUA import file, or parsing SUA's output and the SIPARE capture line. | **S12** (SUA 3.7.1), **S13** (affiliation movements), **S16** (INFONAVIT–SUA): no layout saved. Until then, B1/B4 export a **Zoiko worklist** (CSV, labelled "not an IMSS file") for keying into the authority's system. |
| X2 | **Due-date rules.** The 5-business-day movement deadline and the official holiday calendar, the IMSS / INFONAVIT monthly / bimonthly payment dates, the ISR day-17 remittance, and each state's ISN due date. | **S24, S10, S27, S22** (plus S13 for the five-business-day rule and S5 for day 17). Not transcribed, so every due date is `DUE_DATE_UNSOURCED` (B2). |
| X3 | **Any real transmission** to IDSE, SIPARE, SAT or a state portal. | The **integration-mode decision** (D1), plus per-employer credentials (e.firma / IMSS certificate) behind `gcp-sm://` refs → **Secret Manager (Phase 7 D12)**. |
| X4 | **Bank payment** of any liability (SIPARE line, SAT, state). | **Phase 10.** Phase 8 records evidence of a payment made outside Zoiko; it never instructs one. |
| X5 | **Liability periodisation beyond the calendar month.** Bimonthly RCV / INFONAVIT grouping. | S12 / S16 (and S10). Phase 8 accrues by calendar month (a fact of the committed data) and attaches the payment period only from sourced content. |
| X6 | **Annual work-risk premium review** (MX-026, MX-044): the premium formula and the February filing. | S10 (LSS Art. 72/74), S14, S29 (RACERF) — the same gap as the Phase 3 premium approval. Deferred (D10). |
| X7 | **Evidence file storage in production.** | Cloud Storage (`PAYROLL_STORAGE_BACKEND=gcs`), the shared prerequisite with Phase 7 D4 / HK F-8. Evidence upload refuses in production until then; the rest of the workflow works. |

## 2. Preconditions the code enforces (fail closed, in order)

1. The org guard (Phase 4a); the employer, IMSS registration and ISN registration exist (Phase 3).
2. Only **committed** runs feed anything (`committedAt` set and approval drift empty).
3. A movement needs an **ACTIVE IMSS registration** for the event date and the employee's NSS on the profile. It is never logged; it is masked in views (MX-061).
4. A liability / return for a state needs that state's Active ISN pack (MX-045).
5. Due dates come only from Active content (B2), and exports are labelled worklists until X1.
6. Marking anything FILED / PAID / RECONCILED needs evidence (reference, plus a document where the D9 storage allows) and a second person for RECONCILED / ACCEPTED (D6).

## 3. Data model — migration `mx_authorities_m6` (new tables only)

Every table is new. There is **no ALTER on any shared table**. FKs to `payroll_runs` / `payslip_items` / `payroll_employees` are created inside the migration with `lock_timeout = '5s'`, exactly as in Phase 7, and are measured on PG17 before merge.

| Table | Key columns |
|---|---|
| `payroll_mx_imss_movements` | **Links:** org, registration_id (RESTRICT), employee_id (RESTRICT), payroll_run_id (nullable, RESTRICT), source_kind (`FIRST_RUN` / `SBC_CHANGE` / `END_OF_EMPLOYMENT`), source_row_id. **Facts:** movement_type (ALTA / BAJA / MODIFICACION), event_date, sbc, reason_code (nullable until X1). **Deadline:** due_date (nullable), due_rule_ref. **Lifecycle:** status, export_batch_ref, authority_reference, evidence_ref, idempotency_key (unique). Unique (source_kind, source_row_id). |
| `payroll_mx_authority_liabilities` | **Scope:** org, authority (`IMSS` / `INFONAVIT` / `SAT_ISR` / `ISN`), registration_id or state_code, period_key (YYYY-MM). **Amount:** amount, components (JSON by branch). **Deadline:** due_date (nullable), due_rule_ref. **Lifecycle:** status, payment_reference, evidence_ref. Unique (org, authority, registration / state, period_key). |
| `payroll_mx_authority_liability_sources` | **Links:** liability_id, payroll_run_id (RESTRICT), payslip_item_id (RESTRICT). **Source:** source_table, source_row_id, amount. Unique (source_table, source_row_id) — no double counting. |
| `payroll_mx_sua_periods` | **Scope:** org, registration_id, period_key, sua_version (recorded, never assumed). **Totals:** zoiko_totals (JSON), sua_totals (JSON), difference_total. **Lifecycle:** status (DRAFT / RECONCILED / PAID / UNKNOWN), evidence_ref, reconciled_by_id + approved_by_id (four-eyes), capture_line (recorded only). |
| `payroll_mx_sua_differences` | **Links:** sua_period_id, employee_id. **Figures:** branch_code, zoiko_amount, sua_amount, difference. **Explanation:** explanation_code, explanation, explained_by_id, approved_by_id. **Lifecycle:** status (OPEN / EXPLAINED / APPROVED). |
| `payroll_mx_isn_returns` | **Scope:** org, isn_registration_id, state_code, period_key. **Amounts:** base_total, amount. **Deadline:** due_date (nullable), due_rule_ref. **Lifecycle:** status, filing_reference, payment_reference, evidence_ref, amendment_of_id (self, RESTRICT), created_by_id. |
| `payroll_mx_authority_events` | An append-only timeline for all of the above: entity_type, entity_id, event_type, from / to status, detail (JSON, never identifiers in clear), actor, occurred_at. The Phase 7 pattern. |

SIPARE payments and work-risk reviews (plan v1.1 §11) are **not** created in Phase 8 (X1, X4, X6). They come with their sources.

## 4. Lifecycles

### 4.1 Movements

The lifecycle runs PENDING → EXPORTED → FILED → ACCEPTED, or REJECTED. Branches: EXPORTED → UNKNOWN, and PENDING → WITHDRAWN (with a reason, or by reset).

- **ALTA:** the employee's first committed run under a registration.
- **MODIFICACION:** a committed SBC change. *Which* changes legally require a movement, and when (fixed vs variable, bimonthly), is an S13 / S10 rule. Until it's transcribed, every committed change is listed, and the operator may withdraw one only with a recorded reason (D2).
- **BAJA:** only from a recorded end of employment. Phase 9's termination workflow replaces the interim source (D2).

### 4.2 UNKNOWN (B7)

UNKNOWN is entered when a transmission's outcome is not known, including when the operator records that they uploaded something but have no answer. The way out:

1. **Record a status check:** FOUND with the authority's reference, or NOT_FOUND, with evidence.
2. **After NOT_FOUND,** an admin confirms a retry with a reason. It reuses the same row, payload hash and idempotency key.
3. **"Definitively not found"** needs provider / portal-specific config with no default, as in Phase 7.

Nothing retries automatically. An UNKNOWN item is never shown as failed.

### 4.3 Liabilities, SUA periods, ISN returns

- **Liabilities:** ACCRUED (from committed sources) → DUE (once a sourced due date exists) → FILED (declaration evidence) → PAID (payment evidence) → RECONCILED (for IMSS / INFONAVIT: the SUA period is RECONCILED; for ISN: the return is ACCEPTED).
- **SUA periods:** a period cannot be PAID or RECONCILED while any difference is OPEN or EXPLAINED but unapproved.
- **ISN returns:** DRAFT → FILED → ACCEPTED / REJECTED, plus UNKNOWN. An amendment is a new return.

## 5. Services and routes

- **`mexico_imss_service.py`:** movement generation (idempotent, from committed sources), the worklist export, the transitions and the UNKNOWN rule.
- **`mexico_filing_service.py`:** the liability ledger (accrue / refresh from committed runs), ISN returns, ISR remittance records and SUA periods / differences.
- **`mexico_due_dates.py`:** reads Active content only. Returns `(None, "DUE_DATE_UNSOURCED")` without it, and never uses the shared weekend-only `_add_business_days` (D3).
- **Org routes** sit behind the guard: list / generate / export / record-status / confirm-retry / withdraw for movements; liabilities; SUA periods (create, enter SUA totals, explain, approve); ISN returns (draft, file, amend, record outcome).
- **Super Admin:** one read-only overview.

## 6. Reset rule (registration in `run_downstream_actions`)

A reset of a committed run is **refused** (`MX_RESET_DOWNSTREAM_ACTED`) when any of these includes the run:
- a movement with status EXPORTED / FILED / ACCEPTED / REJECTED / UNKNOWN;
- a liability past ACCRUED;
- a SUA period that is RECONCILED / PAID / UNKNOWN;
- an ISN return past DRAFT.

On an allowed reset:
- PENDING movements from the run are WITHDRAWN;
- the run's liability sources are removed;
- ACCRUED liabilities and DRAFT returns are recomputed.

Tests cover each refusal and each withdrawal.

## 7. Frontend

- **`MXSocialSecurityCenter`** (Compliance → Mexico → Social Security), one card each for:
  - employer registration;
  - movements (with UNKNOWN banner and status-check / confirmed-retry actions);
  - SUA period;
  - differences (BLOCKING until explained and approved).
- **SIPARE and work-risk cards** are shown as "blocked — source not transcribed".
- **`MXAuthorityLiabilitiesTab`** (ledger, sources drill-down, due-date state), **`MXIsnReturnsTab`**, and **`MXSuaReconciliationPanel`**.
- **The run "Authorities" badge** reads the real lane: NOT_STARTED / ACCRUED / FILED / PAID / UNKNOWN.
- **Super Admin:** an "Authorities" read-only tab listing the X1–X7 blocks.
- **Flag off:** nothing renders for a refused (403) org, as in Phase 7.

## 8. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `mx_authorities_m6` | **Seven new, empty tables.** No column on any shared table. The head moves `d8b3e5f1a2c7` → the new revision. FK creation takes SHARE ROW EXCLUSIVE on `payroll_runs` / `payslip_items` / `payroll_employees` for about 0.1 s (to be measured on PG17, as in Phase 7). Under `lock_timeout` 5 s it fails fast with nothing created if a writer holds a table. |
| Movement / liability / SUA / ISN services | **Unreachable.** Every org route is behind the Phase 4a guard (403). No Mexican run can be committed in production (no MX employee, no Active MX pack), so no movement, liability or return can exist. |
| Due dates | No due-date content is Active, so every date would be `DUE_DATE_UNSOURCED`. There is nothing to date. |
| Transmissions | None exist: no adapter, no outbound call. Worklists are files an operator downloads; with no data there is nothing to download. |
| `run_downstream_actions` | Also queries the new (empty) tables and returns `[]`, so **reset behaviour is unchanged.** |
| Evidence uploads | No data → none. If attempted, production refuses the `/tmp` fallback (X7). |
| Secrets | Nothing is read. No credential is used in file-export mode. |
| Super Admin "Authorities" tab | A read-only page: zero counts and the X1–X7 blocks. |
| Run badge / org screens | Nothing renders for a refused org; no other country's screens change. |

**Net effect:** an additive schema change and no behaviour change for any jurisdiction.

## 9. Tests (synthetic, labelled)

- **Movements:** generated once per committed event (idempotent across re-runs and restarts), never from a preview / Draft / uncommitted change, and NSS never logged or returned in clear.
- **Liability ledger:** sums equal the committed source rows exactly; sources are unique; a reset removes the sources and recomputes the totals.
- **Due dates:** no Active rule → `DUE_DATE_UNSOURCED`, and a test that the weekend-only helper is never called. With a synthetic Active rule → the correct date, plus a directional test (a later event never gets an earlier due date).
- **SUA:** any non-zero difference blocks RECONCILED. An explanation without a second approver blocks it too. A zero-difference period reconciles.
- **ISN:** return = Σ state liabilities, multi-state employers get separate returns, an amendment links and never edits, and an unsupported state is refused.
- **UNKNOWN:** no automatic retry; a retry needs a recorded NOT_FOUND and confirmation; the same key and payload are reused; a late FOUND after NOT_FOUND adopts the reference with no second filing.
- **Reset:** refused for each acted state; drafts withdrawn and recomputed.
- **Other:** dormancy (all routes 403 with the flag off); migration tests (SQLite + PG17 with measured lock hold and fail-fast); browser checks with the flag off and on.

## 10. Order of work

1. Migration + models.
2. Liability ledger (B3) and its sources.
3. Movements (B1) + due dates (B2).
4. UNKNOWN rule (B7).
5. SUA reconciliation (B4).
6. ISN returns (B5) + ISR record (B6).
7. Reset registration (B8).
8. Routes and Super Admin.
9. Frontend.
10. Full suite in chunks, PG17 measurement, browser checks, report, stage.

## 11. Recommendation — launch mode (decision D1, yours)

**Recommendation: launch file-export only. The operator uploads to IDSE / SUA / SIPARE / SAT / the state portal; Zoiko never transmits. Integrated transmission comes as a later, separately approved phase.**

Reasons:

1. **Layouts first.** Even file export needs the official layouts (X1), and those are the smaller dependency. Integrated mode needs the layouts **and** each authority's transmission interface, credentials and certification.
2. **No sourced machine interface.** No saved source establishes that IMSS, SAT or the state portals offer a supported machine interface to a third-party payroll provider. The spec treats SUA as an external system Zoiko reconciles to (MX-042), not one Zoiko replaces.
3. **Credentials in Secret Manager.** Integrated filing would hold each employer's e.firma / IMSS credentials, which puts per-employer signing secrets in Secret Manager (D12) and widens the Q9 / D-4 security review.
4. **Fewer UNKNOWN states.** File export keeps the UNKNOWN surface small and human-resolved (MX-043), and B7 is designed so that integration can later reuse the same records, keys and rule unchanged.
5. **States.** Thirty-two states' ISN portals differ (MX-047). Integrating them one by one is a long tail; file export plus recorded evidence scales to every certified state on day one.

**Cost of this choice.** The operator does the upload and records the outcome. Zoiko's value is the worklist, the deadlines (once sourced), the reconciliation and the evidence trail. If you choose integrated, Phase 8's buildable scope is unchanged (B1–B9). X3 becomes its own phase, needing a per-authority interface source, credential custody and certification.

## 12. Decisions needed from you (built on the recommendations, 2026-10-19 — still open for you to change)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Launch mode: file-export only, or integrated transmission | **File-export only** (§11). |
| D2 | Movement sources until S13 / S10 rules are transcribed | ALTA from the first committed run per registration. MODIFICACION for **every** committed SBC change, withdrawable only with a recorded reason. BAJA only from a recorded end of employment (an interim field / record, replaced by Phase 9's termination workflow). |
| D3 | Due dates without a sourced rule / holiday calendar | **No fallback**: `DUE_DATE_UNSOURCED`, and never the shared weekend-only helper. |
| D4 | Liability period | Accrue by calendar month (the pay-date month). Bimonthly payment grouping only from sourced content (X5). |
| D5 | SUA input and tolerance | Until S12: operator enters SUA figures through a Zoiko template, with the SUA output attached as evidence. **Zero tolerance**: every non-zero difference needs an explanation. Reason codes are Zoiko workflow labels (TIMING / SUA_VERSION / DATA_CORRECTION / OTHER), not statutory codes. |
| D6 | Four-eyes | A second person approves each explanation, each RECONCILED SUA period, and each ACCEPTED return / movement outcome. The maker and the checker must differ. |
| D7 | Reset scope | As in §6: refused past ACCRUED / PENDING / DRAFT, with drafts withdrawn and recomputed. |
| D8 | Shared `statutory_filings` (Super Admin Filings & Remittances) | **Do not write MX rows in Phase 8.** The MX tables are authoritative. A read-only adapter can come later, if you want MX on that shared page. |
| D9 | Evidence documents | Reuse the durable-storage path (Phase 7 D4), refused in production until Cloud Storage. Before that, a reference number alone is enough to record FILED / PAID. |
| D10 | Work-risk annual review | Defer until S10 / S14 / S29 are transcribed (X6). Nothing is built in Phase 8. |
| D11 | ISN scope | Returns only for states with an Active ISN pack. Other states stay blocked (MX-045). No state is enabled by code. |
| D12 | NSS in exports | The worklist necessarily contains the NSS (the operator keys it). It is generated on request, never stored as a file, the download is audited, and the NSS is never logged. Confirm, or require that the export be refused until Q9 is decided. |

**Open, unchanged from Phase 7:** D10–D12 there (PAC provider, S28 / S30 / S4, Secret Manager), Cloud Storage, G1–G8, Q9.
