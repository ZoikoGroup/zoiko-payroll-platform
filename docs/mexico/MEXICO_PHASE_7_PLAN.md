# Mexico (MX) — Phase 7 Plan: CFDI 4.0 + Complemento de Nómina 1.2 + PAC

Spec ZP-MX-ENG-001 v1.0 §6 (MX-014–MX-018), §13 stage 6, §20 (MX-035, MX-060–MX-062), fixture F6 · plan v1.1 §10 · Phase 6 reset rule (`MEXICO_IMPLEMENTATION_PLAN.md` §10).
**Plan only — nothing is built.** Standing rules apply:
- stage only;
- zero behaviour change for other jurisdictions;
- never infer a statutory value;
- fail closed;
- nothing Active by code;
- merging to `main` deploys to production and runs Alembic (§8);
- git state is verified, never assumed (master prompt rule 12).

**Baseline — checked 2026-10-17:**
- `main` is `318aa20` (PR #107, Phase 6). Deploy run **39002236064** is green: test, single-head, SSH deploy with migrations, drift. Production is expected at **`c4f7a2d9e6b1`**.
- The Phase 6 follow-up (preview pay date, the Mexico read-only policy, "—" employer totals, master-prompt rule 12, OOS-8/OOS-9) is **staged on `nikhil`, not committed**. It has no migration, and it should be merged before Phase 7 starts.
- Saved sources: **S22 only**. S4, S28 and S30 are not saved.

---

## 1. What Phase 7 is — split explicitly

### Buildable now — no statutory content, provider or secret needed

| # | Item | Notes |
|---|---|---|
| B1 | **Tables:** `payroll_mx_cfdi_documents`, `payroll_mx_cfdi_outbox_items`, `payroll_mx_cfdi_events` (append-only) | migration `mx_cfdi_m5` (§3) |
| B2 | **Lifecycle state machine** (§4), including **UNKNOWN → status query before any retry** (MX-062) | Every transition writes an event; illegal transitions are refused |
| B3 | **Cancellation / substitution lineage** (MX-018, F6) | `replaces_uuid` / `replaced_by_uuid`; the original is retained. Reason codes come from the catalog (value-free, §4.3) |
| B4 | **Provider-agnostic `PacAdapter` interface** (§5) + registry. The **only implementation is a test-only mock in `tests/`**, which can't be selected in production | Production registry is empty, so PAC calls are refused with `MX_PAC_NOT_CONFIGURED` |
| B5 | **Outbox:** durable, idempotent, explicitly processed (§5.3) | Deterministic idempotency keys; never resent blindly |
| B6 | **`run_downstream_actions`** registers the CFDI check | Reset is refused once a CFDI has been transmitted or stamped (§6, D2) |
| B7 | **Builder and signer seams** as interfaces whose production implementations refuse: `MX_CFDI_BUILDER_BLOCKED`, `MX_CSD_SIGNING_BLOCKED` | Tests inject synthetic implementations; production can't create a document |
| B8 | **Frontend:** CFDI stage panel, detail drawer (lineage + events), cancel/replace dialog, Super Admin read-only lifecycle tab | All honest about the blocks |
| B9 | **Status badge:** the Phase 6 "CFDI" badge reads the documents (counts by status) | MX-041: never moves payroll, authority or bank state |

### Blocked — not built in Phase 7; each needs something only you can provide

| # | Item | Needs | Until then |
|---|---|---|---|
| X1 | **XML builder** for CFDI 4.0 + Nómina 1.2: node mapping from the committed `mx_result` (Percepciones / Deducciones / OtrosPagos incl. subsidy MX-014, dates, NumDiasPagados, receiver data) | **S28** (Nómina 1.2 catalog workbook + `nomina12.xsd`), **S30** (CFDI 4.0 catalogs / Anexo 20 incl. `cfdv40.xsd`), **S4** (SAT payroll-receipt guide). The earning-classification `cfdi_concept_code` must be VERIFIED against S28 | `MX_CFDI_BUILDER_BLOCKED` |
| X2 | **XSD validation** against the pinned release (MX-015) | The XSDs above, loaded into an **Active** `PayrollMxCfdiSchemaRelease` (Phase 2 table) with its checksum | Blocked with the builder |
| X3 | **Any real PAC adapter** (sandbox or production) | Your **provider decision** (D10), its API contract and credentials | `MX_PAC_NOT_CONFIGURED` |
| X4 | **CSD signing** (cadena original + sello) | **GCP Secret Manager** live, with the CSD key behind a `gcp-sm://` ref (MX-035; only fingerprints and expiry are in the DB, from Phase 3) | `MX_CSD_SIGNING_BLOCKED` |
| X5 | **Employer stamp test** (`stamp_test_status`, Phase 3 column) and employee delivery of the receipt | X1–X4 | Stays `NOT_TESTED`; LIVE is never reached |

---

## 2. Preconditions the code enforces (fail closed, in this order)

A CFDI document can be created for a payslip only if all of these hold:
1. **Onboarding:** `MX_TENANT_ONBOARDING_ENABLED` is on and the organisation is Mexican (the Phase 6 guard).
2. **Committed run (MX-016):** the run is APPROVED with `mx_approval_fingerprint.committedAt` set and no approval drift. A preview or a recalculation never creates or alters a document.
3. **Payslip:** has an `mx_calculation_snapshot` that is not blocked.
4. **Schema release:** an **Active** CFDI schema release covers the pay date (Phase 2), with its catalog release.
5. **Employer:** the CSD credential ref is ACTIVE and unexpired (Phase 3); PAC provider and environment are set; for PRODUCTION, `stamp_test_status = PASSED`.
6. **Builder and signer** are available. In production both refuse, so **no document is ever created in production during Phase 7.**

Each unmet precondition is reported with its own code on a CFDI preflight (the same pattern as Phase 6's run preflight).

## 3. Data model — migration `mx_cfdi_m5` (new tables only)

`down_revision` is `main`'s head when Phase 7 is built (expected `c4f7a2d9e6b1`). There are **no ALTERs on shared tables.** Creating the FKs takes a brief `SHARE ROW EXCLUSIVE` lock on `payslip_items` / `payroll_runs`: reads continue, writes wait for milliseconds. It runs under `SET LOCAL lock_timeout = '5s'`, is guarded and idempotent, and is tested on throwaway PostgreSQL 17 with the hold time measured, like Phase 6.

**`payroll_mx_cfdi_documents`**

| Column | Notes |
|---|---|
| id, organization_id (CASCADE), payroll_run_id (**RESTRICT**), payslip_item_id (**RESTRICT**), employee_id (**RESTRICT**) | A fiscal document is never cascade-deleted |
| series, folio | Assigned at generation; unique per issuer RFC |
| schema_release_id (FK `payroll_mx_cfdi_schema_releases`) | Pins the release used (MX-015) |
| payload_hash (sha256), xml_storage_ref | Raw XML is **never in the DB or logs** (MX-061). It is stored through the existing durable-storage mechanism (`app/core/object_storage`: GCS `gs://…` in production, local disk in dev/tests), with the **same production refusal of the `/tmp` fallback** the HK evidence uploads use (`durable_storage_refusal`), checked before anything is written (D4). |
| status | GENERATED / SIGNED / SUBMITTED / STAMPED / REJECTED / UNKNOWN / CANCEL_REQUESTED / CANCELLED / REPLACED / VOIDED (D3) |
| uuid (unique where not null), stamped_at, sat_certificate_number, pac_provider, pac_environment, pac_response_code, pac_message | Immutable once STAMPED |
| cancellation_reason_code, cancel_requested_at, cancelled_at, replaces_uuid, replaced_by_uuid | Lineage (MX-018) |
| idempotency_key (unique), created_by_id, created_at, updated_at | |

Partial unique index: **one live document per payslip** (status not in CANCELLED / REPLACED / VOIDED / REJECTED).

**`payroll_mx_cfdi_outbox_items`**

| Column | Notes |
|---|---|
| id, document_id (RESTRICT) | |
| action | STAMP / CANCEL / STATUS_QUERY / CANCEL_STATUS_QUERY |
| payload_hash, idempotency_key (unique) | Deterministic per (document, action, attempt group). **No timestamp in the key** (the NL Digipoort key includes `utcnow()`; this one won't) |
| status | PENDING / SENT / ACKNOWLEDGED / FAILED / UNKNOWN |
| attempts, last_error (redacted), sent_at, acknowledged_at, created_at, updated_at | |

**`payroll_mx_cfdi_events`** (append-only)

| Column | Notes |
|---|---|
| id, document_id (RESTRICT), event_type, from_status, to_status, payload_hash, actor_id, occurred_at | |

There is no update or delete path in code. A test asserts that every service function touching events only inserts.

## 4. Lifecycle state machine

### 4.1 Transitions (anything not listed is refused with `MX_CFDI_ILLEGAL_TRANSITION`)

| From | To | Trigger |
|---|---|---|
| — | GENERATED | builder produced and XSD-validated the payload (blocked in production) |
| GENERATED | SIGNED | signer produced the sello (blocked in production) |
| SIGNED | SUBMITTED | outbox STAMP item sent |
| SUBMITTED | STAMPED | PAC accepted: uuid, stamped_at and SAT certificate number recorded |
| SUBMITTED | REJECTED | PAC rejected with a definitive code; a corrected document is a **new** document |
| SUBMITTED / CANCEL_REQUESTED | **UNKNOWN** | timeout, transport error, ambiguous answer, or restore (MX-062) |
| UNKNOWN | STAMPED / REJECTED / SIGNED | **only via a STATUS_QUERY result:** FOUND → STAMPED with the PAC's uuid; definitively NOT_FOUND → SIGNED (eligible for one new STAMP attempt); still unknown → stays UNKNOWN |
| STAMPED | CANCEL_REQUESTED | cancellation with a catalog reason code (and the replacement uuid when the reason requires one) |
| CANCEL_REQUESTED | CANCELLED / STAMPED | the PAC/SAT cancellation result (accepted, or rejected, which leaves it STAMPED) |
| CANCELLED | REPLACED | the replacement document is STAMPED and linked (`replaced_by_uuid`) |
| GENERATED / SIGNED | VOIDED | never transmitted, and the run was reset (D3) |

### 4.2 UNKNOWN rule (MX-062) — revised 2026-10-17
- A document in UNKNOWN has **no** STAMP or CANCEL outbox item processed for it. The only automatic action is a STATUS_QUERY (or CANCEL_STATUS_QUERY).
- **A retry reuses the SAME signed payload (same `payload_hash`) and the SAME idempotency key** as the original STAMP. A PAC that deduplicates then returns the existing UUID instead of stamping twice.
- **"Definitively not found"** needs two provider-specific settings, **with no default**:
  - `min_wait_seconds` since the last send;
  - `min_not_found_queries`, which must be more than one.

  They live in a per-provider config. While they're unset — and that's every case until a provider is chosen (D10) — the document can never become "definitively not found".
- **Until then, any retry from UNKNOWN needs explicit operator confirmation:** an org admin, with a reason, recorded as an `OPERATOR_RETRY_CONFIRMED` event. It is never automatic. Even with provider config, a retry is offered only when both thresholds are met, and confirmation is still recorded.
- **Late FOUND:** a query that answers FOUND after an earlier NOT_FOUND (or after a confirmed retry) adopts the PAC's UUID. No second stamp is ever created; a second STAMPED answer for the same idempotency key must carry the same UUID, or the document goes to UNKNOWN with `MX_CFDI_UUID_CONFLICT` for manual reconciliation.
- After a restore, every document in SUBMITTED or CANCEL_REQUESTED is moved to UNKNOWN by a reconciliation function before any outbound action.
- Tests:
  - a timeout → UNKNOWN, and an attempted automatic STAMP is refused;
  - a query returning FOUND → STAMPED with no second stamp;
  - NOT_FOUND with no provider config → the retry is refused without operator confirmation;
  - with confirmation → exactly one retry, with the **same idempotency key and the same payload hash** (asserted on the mock's call log);
  - **a late FOUND after NOT_FOUND → adopts the UUID, and the mock records a single stamp per idempotency key**;
  - provider config set but thresholds not met → no "definitively not found";
  - a never-answering query stays UNKNOWN.

### 4.3 Cancellation and substitution (MX-018, F6)
- Correcting a stamped payslip goes through:
  1. a Phase 6 **correction run**, using the existing `mx_run_type = CORRECTION` — Phase 7 only needs the lineage, and the correction run's calculation itself stays Phase 9;
  2. a new document with `replaces_uuid`;
  3. a cancellation of the original with a reason code;
  4. after both settle, the original goes to REPLACED.
- The original's uuid, reason and replacement uuid are never edited.
- **Reason codes are catalog content:** a code is accepted only if it exists in an **Active** catalog release (Phase 2 `PayrollMxCfdiCatalogEntry`, catalog `c_MotivoCancelacion` — name confirmed at S30 transcription). Whether a reason requires a related uuid is a field of that catalog row. With the catalog empty, cancellation is refused (`MX_CFDI_CANCEL_REASON_UNAVAILABLE`), so this is built and tested with synthetic catalog rows only.

## 5. PAC adapter, outbox, builder and signer seams

### 5.1 `PacAdapter` (ABC, `mexico_pac.py`)

```python
class PacAdapter(ABC):
    provider: str
    def stamp(self, signed_payload: bytes, idempotency_key: str, credential: CredentialHandle) -> StampResult: ...
    def query_status(self, document: DocumentRef, idempotency_key: str, credential: CredentialHandle) -> StatusResult: ...
    def cancel(self, uuid: str, reason_code: str, replacement_uuid: str | None, idempotency_key: str,
               credential: CredentialHandle) -> CancelResult: ...
    def query_cancel_status(self, uuid: str, credential: CredentialHandle) -> CancelStatusResult: ...
```

- **Results:** each carries `outcome` (ACCEPTED / REJECTED / UNKNOWN, or FOUND / NOT_FOUND / UNKNOWN), `uuid`, `stamped_at`, `sat_certificate_number`, `code`, `message` (redacted) and `raw_response_hash`. Never raw XML.
- **Errors:** a transport exception or timeout is always mapped to `UNKNOWN`, never to REJECTED.
- **`CredentialHandle`** is an opaque reference resolved by a secrets provider. The adapter never sees DB secrets, and in Phase 7 no real secret exists.
- **Registry:** `get_adapter(provider, environment)` returns from `_ADAPTERS`, which is **empty in `app/`**. That gives `MX_PAC_NOT_CONFIGURED`.
- **Test-only mock:** the mock lives in `tests/_mx_mock_pac.py` and is registered only by tests via monkeypatch. It scripts per call: accept / reject / timeout / not-found / found.
- **Pinned by tests:** that `app/` contains no adapter implementation, and that production settings can't select `MOCK`.

### 5.2 Builder and signer seams
- `CfdiPayloadBuilder.build(document_input) -> (bytes, payload_hash)`. `SatBuilder` raises `MX_CFDI_BUILDER_BLOCKED` with the missing sources named (S28, S30, S4, XSD release).
- `CfdiSigner.sign(payload, credential) -> (bytes, cert_number)`. `GcpSmSigner` raises `MX_CSD_SIGNING_BLOCKED` ("GCP Secret Manager not configured").
- Tests inject a synthetic builder and signer that produce labelled non-SAT bytes, so the state machine and outbox can be proven end to end.

### 5.3 Outbox processing (D5)
- `process_outbox(db, organization_id, limit)` runs explicitly from an org-admin route. **No scheduler in Phase 7.**
- For each item it:
  1. takes a row lock (`SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL);
  2. calls the adapter;
  3. records the result;
  4. writes events;
  5. commits per item.
- A crash between the adapter call and the commit leaves the item SENT and the document SUBMITTED. Reconciliation then moves it to UNKNOWN, and a status query follows.

## 6. Reset rule and lifecycles (Phase 6 carry-over)
- `mexico_run_service.run_downstream_actions(db, run)` gains a CFDI check. It returns one reason per document of the run in **SUBMITTED, UNKNOWN, STAMPED, CANCEL_REQUESTED, CANCELLED or REPLACED** (D2). Any such document refuses reset with `MX_RESET_DOWNSTREAM_ACTED`.
- Documents only in GENERATED or SIGNED were never transmitted. On reset they move to **VOIDED** (D3) and the event is kept.
- Tests:
  - reset after STAMPED is refused;
  - reset after UNKNOWN is refused;
  - reset with only SIGNED voids the document and succeeds.
- **MX-041:** stamping never changes `payroll_runs.status`, authority liabilities or the bank hold. AUTHORIZED / PAID stay refused through Phase 7 (D8). A test asserts no cross-object writes on every CFDI transition.

## 7. Frontend

| Component | Where | Shows |
|---|---|---|
| `MXCfdiStagePanel.jsx` | run drawer (MX runs), under the Phase 6 panels | CFDI preflight (§2) with codes; per-payslip document status, folio, uuid when stamped, outbox attempts; an UNKNOWN banner with **"Query status"**, and no "retry" button while UNKNOWN; "Generate CFDI" is disabled with the blocking reason |
| `MXCfdiDetailDrawer.jsx` | from a document row | Lineage (replaces / replaced by), the event timeline, PAC codes and messages. Never XML |
| `MXCancelReplaceDialog.jsx` | stamped document | Reason picker from the Active catalog; disabled with "cancellation reasons not transcribed (S30)" while it's empty |
| `MXCfdiLifecycleTab.jsx` | Super Admin Mexico workspace | Read-only counts by status, UNKNOWN items, the pinned schema release |
| CFDI badge | `MXRunStatusBadges.jsx` | Real counts, e.g. "CFDI: 0 of 1 — builder blocked" |

## 8. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `mx_cfdi_m5` | Three new empty tables. FK creation briefly takes SHARE ROW EXCLUSIVE on `payslip_items` / `payroll_runs` under `lock_timeout` 5 s (measured on PG17 before merge). No column on any shared table. Head moves from `c4f7a2d9e6b1` to `mx_cfdi_m5`. |
| CFDI service, state machine, outbox | Unreachable: the new routes sit behind the 4a guard (403), no Mexican run can be committed (no MX employee, no Active MX pack), and the builder and signer refuse. No document can exist. |
| `PacAdapter` registry | Empty in `app/`. No outbound call to any PAC is possible; the mock is test-only. |
| `run_downstream_actions` | Queries an empty table and returns `[]`, so reset behaviour is unchanged (there are no MX runs anyway). |
| Status badge / panels | Mount only for runs with MX items; there are none. |
| Secrets | Nothing is read. Signing refuses before any Secret Manager call. |

Net effect: an additive schema change and no behaviour change.

## 9. Tests (synthetic, labelled)

- **State machine:** every legal transition; every illegal transition refused; an event per transition; STAMPED fields immutable.
- **UNKNOWN:** the §4.2 matrix with the mock (timeout / found / not-found / never-answers), plus restore reconciliation.
- **Lineage:** a cancel with a catalog reason (synthetic catalog row); the related-uuid requirement read from the catalog row; the substitution chain to REPLACED; the original uuid retained; cancel refused while the catalog is empty.
- **Preconditions (§2):** each one refuses with its code. MX-016: a preview or recalculation never touches a document.
- **Idempotency:** a duplicate outbox key is refused; a key is deterministic; processing twice is a no-op; `SKIP LOCKED` on PostgreSQL.
- **Reset:** the §6 cases.
- **Lifecycles:** no cross-object writes.
- **Unreachable in production:** flag off, every route 403; production builder, signer and registry refuse; `app/` contains no adapter; the mock can't be selected.
- **Migration:** SQLite and PostgreSQL 17 (order, measured lock, held-lock fail-fast, re-run, drift).
- **Regression:** the full suite in chunks; lint and build.

## 10. Browser checks

- **Flag off:**
  - NL run screen unchanged;
  - no CFDI panels;
  - routes return 403;
  - the Super Admin tab loads with zero counts.
- **Flag on (scratch DB, synthetic pack, harness-only synthetic builder/signer + mock PAC wired in by `serve.py`, never in `app/`):**
  - committed run;
  - CFDI preflight;
  - generate → stamp;
  - force a timeout → UNKNOWN banner with no retry button;
  - query → STAMPED;
  - cancel/replace dialog with a synthetic reason;
  - the lineage drawer;
  - reset refused with `MX_RESET_DOWNSTREAM_ACTED`;
  - badges: CFDI changes, Payroll / Authorities / Bank unchanged.

  Screenshots are inspected.

## 11. Order of work
1. Commit and merge the Phase 6 follow-up; update `nikhil` and verify (rule 12).
2. Migration and models, plus the PG17 tests.
3. State machine and events.
4. Adapter interface, registry and the test mock; outbox and processing.
5. Builder and signer seams (production refusal).
6. Lineage and cancellation (catalog-driven).
7. `run_downstream_actions` and VOIDED on reset.
8. Routes.
9. Frontend.
10. Full suite, browser checks, report, stage, stop.

## 12. Decisions (approved 2026-10-17: D1–D3 and D5–D9 as recommended; D4 as decided; the §4.2 UNKNOWN rule revised; D10–D12 open)

| # | Question | Recommendation |
|---|---|---|
| D1 | Build only the provider-agnostic `PacAdapter` and a **test-only** mock in Phase 7 — no real provider code until you choose one? | Yes. |
| D2 | **Which document states count as "a downstream lifecycle has acted"** for the reset rule? Your Phase 6 wording was "CFDI stamped". I recommend also refusing on SUBMITTED, UNKNOWN, CANCEL_REQUESTED, CANCELLED and REPLACED, because a transmitted document may already be stamped at the PAC. | Refuse from SUBMITTED onward. |
| D3 | Documents never transmitted (GENERATED / SIGNED) when a run is reset: move them to a terminal **VOIDED** status, keeping their events, rather than deleting them? | VOIDED. |
| D4 | **Decided 2026-10-17:** no GCS-specific path. Reuse `app/core/object_storage` (the HK evidence-upload mechanism), including its production refusal of the `/tmp` fallback. **CFDI XML retention** (how long, who may delete, legal hold) is a legal / **Phase 10 retention-policy item**; until then nothing deletes a stored CFDI XML. | Decided. |
| D5 | Outbox processed by an **explicit org-admin action** in Phase 7, with a scheduler/worker deferred to the external-operations phase (G6)? | Yes. |
| D6 | Cancellation reason codes and their "requires related uuid" flag **only from an Active catalog** (S30), refused while it's empty? | Yes. |
| D7 | PRODUCTION stamping requires the employer's `stamp_test_status = PASSED`, set only by a real **sandbox** stamp (blocked until X1–X4)? | Yes. |
| D8 | AUTHORIZED / PAID stay refused for MX runs through Phase 7 (bank settlement is Phase 10). A stamped CFDI does not unlock them (MX-017). | Yes. |
| D9 | Migration is **new tables only**, with no shared-table columns. The CFDI status is read from the documents, not stored on `payslip_items` or `payroll_runs`. | Yes. |
| D10 | **PAC provider (open):** which certified PAC (and sandbox) will Zoiko use? It is needed for X3, the stamp test and the §4.2 retry thresholds. The adapter stays thin (§5.1: four calls, typed results, no provider types leak), so the chosen provider is one new class, not a rewrite. | Open. |
| D11 | **Sources to save** (`docs/mexico/sources/`, hashed in the manifest), needed for X1/X2: **S28** (Nómina 1.2 catalog workbook + `nomina12.xsd`), **S30** (CFDI 4.0 catalogs, Anexo 20, `cfdv40.xsd`), **S4** (SAT payroll-receipt guide). | Please save them, or tell me where to download them from (I won't fetch them unasked). |
| D12 | **GCP Secret Manager:** when will the project, IAM and a test CSD under a `gcp-sm://` ref be available (X4)? Until then signing refuses. | Your timeline. |
