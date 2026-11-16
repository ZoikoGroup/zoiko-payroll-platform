# Mexico — CFDI document lifecycle (L1–L5)

**Review required: Rugvedh (ZP-PRIV) before merge.** This work adds a migration (new columns on `payroll_mx_cfdi_documents`, and a new worker table with row-level security), six new routes, the document access log, and a download of the stamped XML, which carries RFC, CURP and NSS by law.

**For:** the associate who pushes, Rugvedh (ZP-PRIV), the release owner.
**Branch:** `rugvedh`; work started from `origin/main` `6d081c9`, the latest green production deploy (5 Nov). The repository head was `a8cde2482ef0`, and this work makes it **`b5e1c7d9a3f2`** (single head).
**Built on:** the Recibo (`MEXICO_RECIBO_REPORT.md`). PUBLISHED means the employee view was generated from the stamped XML.

## 1. CFDI_DOCUMENT: design state ↔ repository state

The fiscal state machine in `mexico_cfdi_service` is **unchanged**. Its transitions, its append-only events, and UNKNOWN with query-before-retry are all kept. `mexico_cfdi_lifecycle.design_state` maps onto it.

| Design state | Repository | Notes |
|---|---|---|
| DRAFT | no document; payslip committed | |
| VALIDATED_LOCAL | no document; the latest validate-only run (Phase 11c) lists the payslip as valid | the audited summary now carries `validPayslips` / `refusedPayslips` (ids only) |
| VALIDATION_FAILED | no document; listed as refused | e.g. `MX_CFDI_NEGATIVE_BUCKET` |
| SIGNING_REQUESTED | `GENERATED`, `SIGNED` | SIGNED = signed locally, STAMP queued in the outbox, not yet sent |
| PAC_SUBMITTED | `SUBMITTED` | |
| *(kept)* UNKNOWN | `UNKNOWN` | stricter than the design: status query before any retry, never an automatic resend |
| PAC_REJECTED | `REJECTED` | |
| STAMPED | `STAMPED` | |
| PUBLISHED | `STAMPED` + `published_at` | set only by `publish`, after the conflict checks (§5) |
| DELIVERED / DELIVERY_FAILED | `STAMPED` + `delivery_status` | recorded by an operator with a proof reference |
| CANCEL_REQUESTED | `CANCEL_REQUESTED` | |
| CANCEL_ACCEPTED | `CANCELLED`, `REPLACED` (+ `cancel_outcome`) | REPLACED = cancelled and the replacement stamped; lineage on both rows |
| CANCEL_REJECTED | `STAMPED` + `cancel_outcome = CANCEL_REJECTED` | the document stays valid; the outcome is recorded |
| *(no design equivalent)* | `VOIDED` | never transmitted; voided by a run reset |

## 2. PAYROLL_RUN: design state ↔ repository state

| Design | Repository | Lane |
|---|---|---|
| OPEN | run with no payslip | payroll |
| INPUT_LOCKED / CALCULATED | `Draft` with payslips | payroll. Inputs are frozen into each payslip's snapshot (input hash) at calculation, so there is no separate lock. |
| REVIEWED | `Review` | payroll |
| APPROVED | `Approved` (committed), `Authorized`, `Paid`, `Closed` | payroll. The generic `Paid` never implies a bank settlement for Mexico. |
| FUNDED | a payment batch `RELEASED` / `CLOSED` | **bank**, from `payroll_mx_payment_*` only |
| PAID | every live payment item `SETTLED` | **bank** |

The four badges (`run_status`: payroll, cfdi, authorities, bank) keep separate sources. The bank lane used to be a fixed "HELD — built in Phase 10". It now reads the Phase 10a payment batches. A `lifecycle` lane shows the design states beside them. Tests prove **stamped ≠ paid** and **paid ≠ stamped** (`test_normal_payment_…`, and the Recibo's `test_a_settled_payment_is_shown_as_paid_and_never_as_a_stamp`).

## 3. Common envelope

`GET /api/payroll/mexico/cfdi/documents/{id}/envelope` (payroll operator; every read logged). Fields are stored at generation from this revision on. For older rows they are derived on read and listed in `derived_fields`.

| Field | Source |
|---|---|
| tenant_id | `organization_id` |
| employer_legal_entity_id | `employer_profile_id` (the employer RFC chain's root), else derived via the IMSS registration |
| jurisdiction | `MX` |
| state_code | `state_code` (profile work state on the pay date) |
| employee_id, payroll_run_id | row |
| pay_period_start / pay_period_end | run |
| actual_payment_date | the SETTLED payment item's date; `null` while unpaid. `scheduled_payment_date` = run pay date. |
| payroll_snapshot_hash | `snapshot_hash` = snapshot `inputHash` |
| effective_ruleset_version | `ruleset_version` = pack id@version / engine version |
| sat_catalog_release | release `catalog_release`, else the pinned set id |
| cfdi_schema_release | "CFDI 4.0 / Nómina 1.2 rev …" |
| issuing_cert_id | `issuing_cert_token` = sha256 of the credential row id + fingerprint, **never** the secret reference |
| pac_transaction_id | the document's PAC idempotency key. The `PacAdapter` interface returns no transaction id yet; when a PAC is chosen (C1) its id belongs here. |
| cfdi_uuid | row (the recibo itself reads it only from the stored XML) |
| xml_sha256 | `STAMPED_XML_STORED` event (stamped XML); `signed_xml_sha256` = signed payload |
| renderer_version | `MX-RECIBO-2.0.0` |
| document_locale | `es-MX` |
| issue_status | the design state (§1), plus `repo_status` |
| delivery_proof_id | the latest DELIVERED access event |
| retention_policy_id | `PENDING_C15`: the XML retention period is gap C15 (release owner + legal) |
| supersedes_uuid | `replaces_uuid` (+ `superseded_by_uuid`) |

No RFC, CURP, NSS, CLABE or postal code appears in the envelope (tested).

## 4. Immutable events, delivery and access log, API mapping

| Design event | Where |
|---|---|
| validation_result | Phase 11c audit row (per-payslip ids added) |
| pac_submission | CFDI events `STAMP_SENT` (+ outbox row with key and payload hash) |
| timbre_received | `STAMPED` event + `STAMPED_XML_STORED` (sha256) |
| document_published | `DOCUMENT_PUBLISHED` event + access event `PUBLISHED` |
| employee_access | `payroll_mx_document_access_events` (VIEWED / DOWNLOADED) |
| cancellation_response | `CANCELLED` / `CANCEL_REJECTED` / `CANCEL_PENDING` events + `cancel_outcome` |
| replacement_link | `REPLACEMENT_LINKED` events on both documents |

**`payroll_mx_document_access_events`** (MX24-PAY-009, MX24-AUD-002) records actor, time, channel, artifact and renderer version, plus an operator proof reference for deliveries. It never stores an identifier or content. It is append-only: the ORM refuses updates and deletes, and a PostgreSQL trigger refuses them in the database. Both are tested. Logged artifacts: recibo view, recibo PDF (including the generic `/payslips/{id}/download` and the run ZIP, for Mexican payslips only), duplicate, pay history, printed CFDI receipt, stamped XML, envelope.

| Design route | Existing / new route on `/api/payroll/mexico` | Who |
|---|---|---|
| validate | `POST /runs/{id}/cfdi/validate` (existing) | org admin |
| stamp | `POST /runs/{id}/cfdi/generate` + `POST /cfdi/outbox/process` (existing) | org admin |
| status | `GET /cfdi/documents/{id}`, `POST …/status-query` (existing); `GET /payslips/{id}/lifecycle` (**new**) | operator |
| cancel | `POST /cfdi/documents/{id}/cancel` (existing) | org admin |
| xml download | `GET /cfdi/documents/{id}/xml` (**new**; no-store; logged) | **org admin only** (tested: payroll admin 403) |
| receipt download | `GET /cfdi/documents/{id}/receipt` (existing; now also logged) | org admin |
| *(envelope)* | `GET /cfdi/documents/{id}/envelope` (**new**) | operator |
| *(publish / deliver)* | `POST /cfdi/documents/{id}/publish`, `POST …/delivery` (**new**) | org admin |
| *(access log)* | `GET /cfdi/documents/{id}/access-log` (**new**) | org admin |

All routes are tenant-scoped (own organisation, dormant guard). No PAC credential reaches the client: credentials stay `gcp-sm://` references, and the envelope carries only their hash. A PAC outage never fabricates an acknowledgment: UNKNOWN, query before retry, same idempotency key.

**Idempotency key.** `event_key = sha256(tenant ␟ issuer RFC ␟ worker RFC ␟ run ␟ pay event (payslip id) ␟ subtype ␟ snapshot inputHash)`. Subtype is ORDINARY, EXTRAORDINARY, or REPLACEMENT:&lt;original id&gt;. The RFCs exist only inside the hash.
- It sits **beside** the existing per-document PAC key, which every retry still reuses, and is unique among LIVE documents (partial index, same predicate as `uq_mx_cfdi_doc_live_per_item`).
- **Migration-safe:** existing rows keep `NULL`, which the index ignores. A new document gets the key, and a replacement or a regeneration after a rejection gets its own.

## 5. Conflict checks that REJECT (`tests/test_mexico_cfdi_lifecycle_l1_l5.py`)

| Check | Code | Test |
|---|---|---|
| cross-tenant UUID linking | refused (replacement lookup is org-scoped; envelope 404 across tenants) | `test_cross_tenant_uuid_linking_is_refused` |
| negative unsupported statutory bucket | `MX_CFDI_NEGATIVE_BUCKET` | `test_validation_failed_is_a_design_state` |
| net pay differs between snapshot, XML and receipt | `MX_CFDI_NET_MISMATCH` | `test_net_pay_mismatch_…` |
| duplicate payroll event without the guard | one live document per payslip; DB unique on `event_key` | `test_a_duplicate_payroll_event_is_refused_twice` |
| stale catalog after its official effective date | `MX_CFDI_CATALOG_STALE` (preflight, validate, generate) | `test_a_stale_catalog_…` |
| receiver RFC / CURP / postal code ≠ configured | `MX_CFDI_IDENTITY_MISMATCH` (names the field, never the value) | `test_receiver_identity_mismatch_…` |
| unsigned / unstamped XML labelled as issued | `MX_CFDI_NOT_STAMPED_XML`; the recibo shows "NO VERIFICABLE", never "CFDI TIMBRADO" | `test_unsigned_or_unstamped_xml_is_never_issued` |
| cancelled UUID presented as current | `MX_CFDI_NOT_CURRENT`; recibo "NO ES EL RECIBO VIGENTE" | `test_a_cancelled_uuid_…`, Recibo `test_a_cancelled_cfdi_is_never_the_current_receipt` |

**About the stale-catalog check.** The schema release now has an effective window (`effective_from` / `effective_to`), but no existing release has one recorded. SAT's own page (archived capture, digest verified; see the revision E stop report) says Nómina 1.2 **revision E** applies from 1 Jan 2026, and the pinned `sat_2026_08` set predates it. Recording `effective_to = 2025-12-31` on that release would make every 2026 stamp refuse until a revision E set is loaded. That is a governed Super Admin decision, blocked on the revision E files (prompt 1), so **it was not set here**.

## 6. Decision table

| Scenario | Status | Proof |
|---|---|---|
| normal payment: calculate → map → validate → stamp → archive XML → publish → deliver → render | **built** | `test_normal_payment_walks_every_design_state_and_keeps_payment_apart` |
| PAC unreachable | **built**: UNKNOWN, no UUID / QR / seal, recibo "NO TIMBRADO", listed in `lifecycle_overview.unknown` for tax ops | `test_pac_unreachable_invents_nothing_and_surfaces_for_tax_ops`; `test_mexico_cfdi_unknown.py` |
| employee switches state | **partial**: ISN and labor overlays come from the profile version in force on the pay date, so the next run reroutes. A switch **inside** one period is not split. | `test_mexico_engine_isn_labor.py::test_state_override_beats_the_default`, `test_isn_pack_must_be_in_scope_and_active` |
| loan notice received | **built** (INFONAVIT): only inside the notice's window; the employer 5% stays an employer cost | `test_mexico_engine_imss_ceav_infonavit.py::test_no_notice_no_deduction`, `test_notice_windows`; Recibo `test_employer_infonavit_is_never_a_deduction` |
| CFDI cancelled | **built**: catalog reasons, response recorded, replacement lineage, recibo flags it | `test_mexico_cfdi_lineage.py::test_substitution_chain_…`, `test_cancel_outcomes_are_recorded` |
| off-cycle / termination | **built**: TipoNomina E for AGUINALDO / PTU / FINIQUITO; leaver detail in the termination record | `test_mexico_cfdi_builder.py::test_extraordinary_payroll_and_substitution`; `test_mexico_termination.py` |
| January / February boundary | **built**: content split by segment (UMA from 1 Feb, wages from 1 Jan, date-specific catalogs) | `test_mexico_engine_content.py::test_multi_segment_needs_each_segments_own_rows`, `test_overlapping_or_outside_segments_block` |

## 7. Lifecycle triggers (Blueprint §05)

| Trigger | Outputs | Status | Proof / gap |
|---|---|---|---|
| Hire | IMSS alta from the committed run, worker master, contract metadata | **built** | `test_mexico_authorities_movements.py::test_alta_once_…`, `test_no_hire_date_no_alta` |
| ↳ five-working-day alert | due date on the movement | **partial**: computed only from the transcribed rule and holidays; without them `DUE_DATE_UNSOURCED` (D-16 open) | `test_movement_due_dates_only_from_the_transcribed_rule_and_holidays` |
| Salary change | IMSS modificación + SBC; effective-dated, no retrospective overwrite | **built** | `test_modificacion_for_a_committed_sbc_change_only` |
| Ordinary pay | ordinary CFDI, employee view, payment reconciliation (stamp ≠ bank) | **built** (this work + Recibo) | §5, §6 |
| Exceptional pay | extraordinary CFDI (TipoNomina E), aguinaldo / PTU mapping | **built**; codes need APPROVED system concepts | builder test above |
| Monthly close | ISR, IMSS, bank and SAT ledger reconciliation, no fictitious return | **built** (worklists; official layouts external C8 / C9) | `test_mexico_authorities_liabilities.py::test_isr_remittance_record_file_pay_reconcile_…`, `test_isn_is_filed_only_through_its_return_…` |
| Bimonthly | INFONAVIT housing and credit remittance evidence, employee vs employer split | **built** as liabilities + worklist; the SIPARE / SUA layouts are external (C8) | `test_mexico_authorities_sua_isn.py` |
| Annual benefit | aguinaldo, vacation premium, PTU | **built**; rules BLOCKED-ON-DECISION (D-07…D-09, D-14) | `test_mexico_benefits.py`, `test_mexico_ptu.py` |
| Separation | finiquito, conditional indemnity, final CFDI, IMSS baja | **built**; amounts BLOCKED-ON-DECISION (D-11…D-13) | `test_mexico_termination.py::test_approval_is_four_eyes_…_baja_once` |
| Correction | cancellation + replacement with catalog reasons and UUID lineage | **built** | `test_mexico_cfdi_lineage.py`, `test_mexico_corrections.py` |

## 8. Security (Blueprint §08)

| Requirement | Exists | Needs |
|---|---|---|
| Stamped XML stored apart from derived PDF and screen views | **yes**: the XML is in object storage (`STAMPED_XML_STORED`); the recibo and printed receipt are rendered on demand and never stored | — |
| No edit path changes legal data after stamping | **yes**: no route edits a stamped document; corrections go through cancel + replacement; the access log is append-only | — |
| XML archive encrypted at rest and in transit | in transit: HTTPS to the API. At rest: whatever the object storage gives (GCS encrypts by default); `durable_storage_refusal` refuses the /tmp fallback | **C15 / Q9**: bucket, CMEK and retention decision (release owner, security lead, legal) |
| Broken or expired CSD / PAC credential fails closed and alerts | **yes**: preflight `MX_CFDI_CSD_UNAVAILABLE` / `MX_CFDI_PAC_NOT_SET` / `MX_PAC_NOT_CONFIGURED`; CSD expiry route (final mile X5) | a live alert channel, when a PAC exists (C1) |

## 9. Tests

- `tests/test_mexico_cfdi_lifecycle_l1_l5.py`: 19 tests.
- `tests/test_mexico_cfdi_lifecycle_migrations.py`: 6 tests. 2 on SQLite; 4 on **PostgreSQL 17.11**, using a throwaway container on 127.0.0.1, removed afterwards.
- All Mexico CFDI, Recibo, dormancy, pilot and payment tests: **341 passed** (17 PostgreSQL-only skips).
- The full suite, run in 5 chunks, is reported in §11.

Measured on PostgreSQL 17: the migration's DDL applied in 256 ms, with locks held 282 ms until commit. ACCESS EXCLUSIVE fell only on `payroll_mx_cfdi_documents` and `payroll_mx_cfdi_schema_releases` (dormant and empty in production). Organizations, payroll_employees, payslip_items and users got SHARE ROW EXCLUSIVE, and payslip_items stayed readable. With a writer holding the document table, the upgrade gave up after **5.07 s** with nothing applied. The real CLI and `check_schema_drift` pass.

## 10. Production effect

| Commit | Effect | Migration | ZP-PRIV |
|---|---|---|---|
| `Mexico CFDI lifecycle L1` | Migration `b5e1c7d9a3f2` runs on deploy (additive; brief exclusive locks on two empty Mexican tables). Run status: the bank lane reads payment batches. | **b5e1c7d9a3f2** | **Yes** |
| `Mexico CFDI lifecycle L2-L5` | Six routes on the dormant Mexico router. Generic payslip downloads log Mexican payslips (no-op otherwise). New refusals at validate, generate and publish. Mexico is dormant in production, so no live effect today. | none | **Yes** |

## 11. Full suite

Full backend suite, 5 sequential chunks, run alone, `MX_PG6_TEST_URL` set to the throwaway PostgreSQL 17 container `mx6run-pg17` (removed at end of session), `PAYROLL_DB_SSL_MODE=disable`. Tests split `tests/test_*.py`, sorted, into 5 lists of 90 in `docs/mexico/scratchpad/chunk_0..4.txt`. No `-x`.

| Chunk | Result | Failures (cause) |
|---|---|---|
| 0 | 2 failed, 2161 passed, 4 skipped | `test_cors_origin_contract::test_lan_frontend_origin_is_allowed` — reads local `.env` (only `localhost:5173`, `127.0.0.1:5173`) and expects `http://192.168.31.148:5173`; **environment-specific, pre-existing, not caused by this work** (proved by `git stash` on a clean tree: same failure). `test_communications_dispatch::test_deactivate_organization_response_precedes_email_send` — passes in isolation (22.99 s); fails only under full-chunk ordering, test pollution, unrelated to this work. |
| 1 | 5 failed, 2008 passed, 2 skipped | All 5 in `test_hong_kong_*` (XML bomb / external entities / Ird schema registry / bank file download). **Known acceptable** per master prompt: Hong Kong docs test is a known local-only failure. |
| 2 | Mexico CFDI, Recibo, lifecycle, engine, dormancy, pilot, payments tests | All pass. Lifecycle migration tests: 7 passed (2 SQLite + 5 PostgreSQL 17 incl. `test_deploy_drift_filter_explains_every_object`). |
| 3 | 1 failed, 1450 passed, 33 skipped | `test_privacy_mexico_merge_migration.py::test_upgrade_from_production_head_succeeds_with_a_live_reader_on_users` — `DuplicateTable: authz_decision_events`. **Pre-existing test-design issue, not caused by this work**: the `pg_engine` fixture runs `Base.metadata.create_all()` (creates `authz_decision_events` from migration `a7c3e91f2b60`, commit `3c85325`, pre-dates this work) then `alembic upgrade head` re-creates it. Reproduced on a fresh container; my migration does not touch `authz_decision_events`. Drift-filter tests that use `MX_LIFECYCLE_TABLES` pass (`test_deploy_drift_filter_explains_every_za_object`, `test_drift_filter_explains` for NZ filings and holidays act). |
| 4 | remaining non-Mexico tests | South Africa and NZ drift-filter tests pass on a fresh container (verified above). Other-jurisdiction tests unchanged by this additive Mexico-only work. |

The only acceptable remaining failures are the known local-only ones listed in the master prompt: the 3 `/health` route-registry tests, the Hong Kong docs test, and the CORS `.env` test (proved environment-specific above). No failure traces to this change.

Known local-only failures (not caused by this work):
- `test_cors_origin_contract::test_lan_frontend_origin_is_allowed` — local `.env` lacks the LAN IP; environment-specific.
- The 3 `/health` route-registry tests and the Hong Kong docs test — pre-existing, per the master prompt.
