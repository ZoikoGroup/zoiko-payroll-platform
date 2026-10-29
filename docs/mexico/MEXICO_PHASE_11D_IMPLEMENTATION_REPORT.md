# Mexico (MX) — Phase 11d Implementation Report: seed fixes (A9), stale text (A8), dead code (A14)

Requested 2026-10-26, step 1 of 3 ("STEP 1 — Phase 11d: A9 seed fixes …, plus A8 stale text and A14 dead code. Tests for each. Stage, report, stop."). Review addition the same day: VERIFIED only through `verify_mexico_sources.py` and a verification log (§2.5). The stricter approval rule (§2.2) was approved.

> **Rugvedh (ZP-PRIV) review:** not required by rule 7. No change to authz, redaction, RLS, migrations or cross-tenant data. The change does tighten a release gate: pack **approval** and **activation** now also refuse any pack whose cited sources are not `VERIFIED` (§2.2). Flagged so it is seen.

**Base.**
- `nikhil` = `a0da835` (PR #131, the 11c CI fix). That is the `main` content deployed by run **40265941034** (green).
- Production should be at alembic head `b9f3d5a1c7e2`. Mexico is dormant: registry PLANNED, flag off.

**No migration. No new route. No frontend change.**

## 1. Result

| Check | Result |
|---|---|
| Full backend suite (sequential chunks, run alone) | §5 |
| New and updated 11d tests | All pass (§4) |
| Targeted Mexico files (seed, activation gates, report templates, content, run dormancy, corrections, router, source tool, release gates) | 130 passed, 9 skipped (PostgreSQL-only) |
| Real manifest smoke check | 9 rows. Draft: 9 citable keys. Activation: **0** (no file is `VERIFIED` yet; the log is empty). Bare `S28` is refused with "S28 has 3 saved files — cite one of them (…)" |

## 2. A9 — seed fixes

### 2.1 Both statuses feed a Draft pack
- New module `backend/app/modules/payroll/mexico_sources.py` is the one reader of `docs/mexico/sources/SOURCES_MANIFEST.csv`:
  - `DRAFT_STATUSES = (VERIFIED, ARCHIVE_COPY_VERIFIED)`
  - `ACTIVATION_STATUSES = (VERIFIED,)`
- `seed_mexico_canonical_packs.load_manifest` accepts both statuses. The seed writes **Draft** packs only, as before. `WRONG_VERSION` and anything else is never usable.
- `verify_mexico_sources.py` recognises `ARCHIVE_COPY_VERIFIED` as a status.
- **The filing calendar is not Draft pack content.** Its due dates are written straight to live filing rules, so `seed_statutory_report_templates.py` reads the manifest with `ACTIVATION_STATUSES`: only a directly downloaded (`VERIFIED`) source seeds a due date, and an archive copy is skipped.

### 2.2 Approval and activation refuse a non-VERIFIED source
- `mexico_service.activation_checks` gains a fifth check, `sources_verified` ("Every cited source VERIFIED (not an archive copy)"), placed after `evidence`.
- Every source artifact the pack cites must match a manifest row with status `VERIFIED` **and** the same URL **and** the same SHA-256.
- **Fail-closed:** if the manifest cannot be read, the check fails ("SOURCES_MANIFEST.csv cannot be read — no source can be confirmed VERIFIED").
- The manifest ships with the repository, and production runs from the git checkout. `security/assurance.py` already reads `docs/privacy` the same way.
- `mx_activation_evidence_refusal` refuses on it (the first unmet check).
- **Stricter than before (approved 2026-10-26):** `mx_pack_approval_refusal` now requires `content`, `evidence` **and** `sources_verified`, looked up by key; it used to take the first two checks by position. A pack built on archive copies can be **Draft or QA**, but can't be **Approved**.

### 2.3 Manifest keyed by file as well as code
- `usable()` returns every file as `CODE/file`. It also returns the bare `CODE`, but **only when that code has exactly one usable file**.
- S28 (3 files) and S30 (4 files) no longer collapse to whichever row came last. A content row must cite, for example, `S28/S28_SAT_catNomina.xls`.
- A bare cite of a multi-file code is refused, naming the files to choose from (`missing_reason`).
- Artifact titles use the code (`row['code']`), so they are unchanged for single-file codes.

### 2.4 `MinWageRow.zone` stored
- The seed writes a minimum-wage row's `zone` into `TaxSlab.jurisdiction_state`. Before, it was dropped, so `Content.min_wage(code, zone)` could not restrict a professional minimum to its zone.
- `slab_signature` gains `jurisdiction_state`, which is `None` for every slab other than a minimum wage.
  - The expected signatures carry `w.zone`.
  - `_db_signatures` carries `s.jurisdiction_state`.
  - So the content check (gate 1b-1) also fails if a stored zone is lost or changed.
- **The runtime is safe:** `service.pack_rows_for_golden`, which Mexico runs read, does not filter on `jurisdiction_state`, so zoned rows reach the engine. The null-state filter in `service.get_tax_slabs` (the generic federal path) is not used by Mexico.

### 2.5 VERIFIED only through a logged direct download (review addition)
- **`verify_mexico_sources.py verify CODE downloader=NAME [file=F]` is the only way a source becomes `VERIFIED`.** It:
  1. refuses an empty downloader, a URL that is not http(s), or a URL on an archive host (`archive.org`, `archive.today`/`.ph`/`.is`, Google cache);
  2. requires title, issuer, version header and a text layer (the rules that used to sit in `set`);
  3. requires the saved copy to still hash to the manifest (otherwise "run `hash` first");
  4. downloads the official URL afresh and refuses if the final URL after redirects is an archive host;
  5. **appends every attempt** to `docs/mexico/sources/VERIFICATION_LOG.csv`: code, file, URL, final URL, timestamp (UTC), downloader, response size, SHA-256, and `MATCH` or `MISMATCH`;
  6. sets `VERIFIED` only on a `MATCH`. A mismatch is logged and refused, and the status is left unchanged.
- **`set` refuses `status=VERIFIED`.** Changing the URL of a VERIFIED row resets it to UNVERIFIED. `hash` already reset a changed file to UNVERIFIED.
- **A `VERIFIED` row counts only with a matching `MATCH` log entry** (same code, file, URL and SHA-256). `mexico_sources.effective_status` treats a VERIFIED row without one as `VERIFIED_WITHOUT_LOG`, which is usable nowhere: not for a Draft seed, a due date, approval or activation. The gate reads the log beside the manifest; a missing log means nothing is VERIFIED (fail-closed).
- `VERIFICATION_LOG.csv` is new, with its header only: nothing has been verified.
- **G1 checklist:** the re-download item now names the `verify` command, and a new evidence item makes the log G1 evidence (attach its rows to the pack). The activation runbook's step 1.1 says the same.

## 3. A8 stale text and A14 dead code

| Item | Change |
|---|---|
| A8 `engine/countries/mexico.py` docstring | Still described `MX_ENGINE_NOT_IMPLEMENTED`. Now describes the dormant engine and the content blocks it raises |
| A8 `tests/fixtures/mx_golden/README.md` | Named codes that no longer exist. Rewritten: cases arrive after content B1–B18 and B21 |
| A14 `mexico_run_service.BUILT_RUN_TYPES` | Removed. It equalled `RUN_TYPES`, so the guard could only fire on an unknown type. The guard is now `not in RUN_TYPES` → **`MX_RUN_TYPE_UNKNOWN`** (renamed from `MX_RUN_TYPE_PHASE9`, whose message promised a later phase). `GUARD_CODES` is updated |
| A14 `classification.py` `MX_SPECIAL_PAY_PHASE9` | **Kept.** It still guards an invariant (a special pay type outside the built set). The comment says so and the message no longer promises a phase |
| A14 `MX_ISR_ARITHMETIC_EXCEPTIONS` | **Kept, not dead.** Read by `tests/test_mexico_content.py:301`; comment added |
| A14 `mx_uma_annual` | **Kept.** Rules read it through content, not core code; comment added |

## 4. Tests

| Test | Proves |
|---|---|
| `test_mexico_seed::test_only_verified_manifest_rows_are_usable` (updated) | Keys are now `{"S2", "S2/S2_synthetic.pdf"}`; other statuses are excluded |
| `test_mexico_seed::test_an_archive_copy_may_back_a_draft_pack` | An `ARCHIVE_COPY_VERIFIED` row seeds a Draft pack and links its artifact; `WRONG_VERSION` is never usable |
| `test_mexico_seed::test_a_code_with_several_files_must_be_cited_by_file` | Two S28 files stay two keys; a bare `S28` cite is refused; `S28/S28_b.xls` links the right file |
| `test_mexico_seed::test_a_professional_minimum_wage_keeps_its_zone` | The zone is stored; `min_wage(code, zone)` picks the zone's amount; the content signatures match, and stop matching when the zone is lost |
| `test_mexico_activation_gates::test_gate_sources_verified_refuses_an_archive_copy_at_activation_and_approval` | An archive-copy source refuses activation and (in QA) approval |
| `test_mexico_activation_gates::test_gate_sources_verified_refuses_when_the_manifest_cannot_be_read` | A missing manifest fails the check (fail-closed) |
| `test_mexico_report_templates::test_an_archive_copy_never_seeds_a_due_date` | The calendar's manifest read accepts `VERIFIED` and rejects `ARCHIVE_COPY_VERIFIED` |
| `test_mexico_activation_gates::test_gate_sources_verified_refuses_a_verified_row_without_a_log_entry` | **The review test:** a manifest row marked VERIFIED with no log entry fails `sources_verified` and approval; an entry for another hash still fails; the matching entry passes |
| `test_mexico_source_tool::test_verify_logs_the_download_and_sets_verified_on_a_match` | A matching direct download sets VERIFIED and writes the log row (all nine fields); the gate's reader then accepts it |
| `test_mexico_source_tool::test_verify_refuses_a_hash_mismatch_and_logs_it` | A different download is refused, logged `MISMATCH`, status unchanged |
| `test_mexico_source_tool::test_verify_never_uses_an_archive_capture` | An archive URL and a redirect to an archive host are refused; so is an empty downloader |
| `test_mexico_source_tool::test_verify_refuses_when_the_saved_copy_changed` | An edited saved copy cannot be verified |
| `test_mexico_source_tool` (3 updated) | Reach VERIFIED through `verify` with a SYNTHETIC download; `set status=VERIFIED` is refused |
| `test_mexico_seed::test_only_verified_manifest_rows_are_usable` (log) | A VERIFIED row is unusable until its log entry exists |
| `test_mexico_approval` `_seed_ready` (updated) | Writes its SYNTHETIC manifest and log to a temp directory, so the QA → Approved test exercises the stricter approval rule |
| `test_mexico_run_dormancy`, `test_mexico_corrections` (updated) | Expect `MX_RUN_TYPE_UNKNOWN`; `BUILT_RUN_TYPES` is absent |
| `test_mexico_activation_gates` `ready_pack` fixture, G2 test, real-packs test; `test_mexico_router` (updated) | Write their synthetic manifest to a temp file for the new check; expect five checks |

## 5. Full suite

Run 2026-10-26 on SQLite, in five sequential chunks, alone. An earlier attempt was discarded: leftover runners from an interrupted session ran chunks in parallel and chunk 0 hit a MemoryError. Those processes were stopped and the suite was rerun from the start.

| Chunk | Result |
|---|---|
| 0 | 867 passed, 15 skipped, **3 failed**: `tests/privacy/test_route_registry.py` (`test_every_route_is_registered`, `test_registry_matches_fresh_generation`, `test_public_routes_are_exactly_known`). These are the known local-only failures caused by your uncommitted `/health/version` and `/health/ready` routes in `backend/app/main.py` |
| 1 | 2283 passed, 1 skipped, 2 xfailed, **1 failed**: `test_hong_kong_configuration.py::test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed`, the known local-only HK docs test |
| 2 | First run: 1480 passed, 37 skipped, **1 failed**: `test_mexico_approval.py::test_a_qa_pack_with_exact_linked_content_is_approved_without_auto_advance`. This was a real consequence of §2.2: approval now needs `sources_verified`, and the helper's synthetic pack had no manifest or log on disk. The helper now writes both, as the activation-gate fixture does. **Rerun of chunk 2: 1481 passed, 37 skipped, 0 failed** |
| 3 | 1734 passed, 69 skipped, 0 failed |
| 4 | 1059 passed, 6 skipped, 0 failed |

**Total: 7424 passed, 128 skipped, 2 xfailed. The only failures are the 4 known local-only ones.** Every NL / IE / SE / HK / SG / DE pinned test passes.

## 6. Production effect

| Area | Effect when merged |
|---|---|
| Database / Alembic | **None.** No migration; head stays `b9f3d5a1c7e2` |
| Mexico in production | Stays dormant (registry PLANNED, flag off). The seeded Draft packs already fail activation on content and evidence; they now also fail `sources_verified`, since no saved source is `VERIFIED` |
| Mexico readiness view (Super Admin) | Shows a fifth check, "Every cited source VERIFIED (not an archive copy)". The frontend renders the list as sent; no UI change |
| Mexico pack approval | Also refused unless every cited source is `VERIFIED` (§2.2). No Mexico pack is in QA in production |
| `verify_mexico_sources.py` | Not run by the deploy. `set status=VERIFIED` is refused; `verify` is new and makes network requests only when an operator runs it |
| Seed scripts | Not run by the deploy. When run, the national seed accepts archive copies for Draft and needs `CODE/file` cites for S28 and S30. Mexico content is still empty, so nothing new is seeded |
| Filing-calendar seed | Unchanged output today: no Mexico filing source is in the manifest |
| Other jurisdictions | **None.** Every edit is in Mexico-only modules, scripts and tests. Pinned NL/IE/SE/HK/SG tests pass in the full suite (§5) |
| Identifiers (RFC, CURP, NSS, CLABE) | Not touched |

## 7. Staged

The 11d files only:
- **New:** `backend/app/modules/payroll/mexico_sources.py`, `docs/mexico/sources/VERIFICATION_LOG.csv` (header only), this report.
- **Code:** `mexico_service.py`, `mexico_run_service.py`, `engine/countries/mexico.py`, `engine/countries/mexico_content.py`, `engine/jurisdictions/mexico/classification.py`, `scripts/seed_mexico_canonical_packs.py`, `scripts/seed_statutory_report_templates.py`, `scripts/verify_mexico_sources.py`.
- **Tests:** `test_mexico_seed.py`, `test_mexico_activation_gates.py`, `test_mexico_approval.py`, `test_mexico_report_templates.py`, `test_mexico_source_tool.py`, `test_mexico_router.py`, `test_mexico_run_dormancy.py`, `test_mexico_corrections.py`, `tests/fixtures/mx_golden/README.md`.
- **Docs:** `release-gates/G1/CHECKLIST.md`, `MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md`.

Your uncommitted files (`backend/app/main.py`, `backend/.env.example`, `frontend/vite.config.js`, `backend/scripts/validate_environment.py`, `docs/SINGAPORE_*`, `docs/HONG_KONG_*`, the source binaries) are **not** staged. Nothing is committed or pushed.

**Next:** step 2 (Batch A sources) has its own report.
