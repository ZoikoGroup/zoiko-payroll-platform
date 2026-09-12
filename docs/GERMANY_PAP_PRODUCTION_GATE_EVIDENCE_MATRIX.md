# Germany PAP Production Gate — Evidence Matrix

**Phase:** 8BD
**Branch:** `nikhil`
**Date:** 2026-09-09
**Worktree:** `D:\zoiko_payroll_platform\zpp-nikhil-extract`

The production PAP executor MUST NOT activate unless **all eight** gates below are
simultaneously satisfied at execution time from a fresh authoritative snapshot
(§ 6/§ 12/§ 27 of the Phase 8BD brief). Today **zero** of the eight are satisfied, so
`resolve_pap_executor()` correctly returns `UnavailablePapExecutor` and REGULAR/MIDIJOB
wage-tax correctly fail closed.

| Gate | Status | Evidence | Blocking? | Human Action? |
|------|--------|----------|-----------|---------------|
| `source_identity_verified` | **NOT SATISFIED** (release row not verified in DB) | Condition exists and is enforced: `_pap_release_gate_snapshot` → `source_identity_verified: bool(row.source_identity_verified)` (`service.py:2770`); setter `record_pap_release_source_identity` (`service.py:2516`). Missing → gate evaluates False (`production_gate.py:58`). Engineering identity evidence is strong (§ source_provenance), but **no release row in any DB has a recorded identity verification** — no `GermanyPapRelease` exists outside ephemeral SQLite test transactions. | **Blocking** | Yes — Super Admin records identity evidence on a real release; no DRAFT row exists to act on yet |
| `source_hash_verified` | **NOT SATISFIED** (no bound asset in DB) | `source_hash_verified` requires live asset hash == bound hash (`service.py:2751-2757`); `record_pap_release_source_hash_verification` refuses on drift (`service.py:2548`); drift test `test_asset_hash_drift_after_binding_is_detected...` (final_certification.py:144). **No `PapAlgorithmAsset` (hence no bound hash) exists in any persistent DB.** Hash itself is stable/verified (SHA-256 `63d898…` across 8 phases). | **Blocking** | Yes — a real asset must be ingested (Super Admin) before a release can bind a hash |
| `source_finality_verified` | **NOT SATISFIED** | Code gate `PAP_SOURCE_FINALITY = "OPEN"` (`adapter.py:80`); `assert_pap_source_finality_resolved()` always raises. Release gate requires `source_finality_status == "VERIFIED"` (`service.py:2772`). **Evidence upgraded this phase** (final official 12.11.2025 Datenportal release == hash `63d898…`; see provenance doc §5), but `OPEN` is deliberately **retained** pending legal + byte-level finality package. | **Blocking** | Yes — legal/eng decision to formally resolve finality + record on a release |
| `licensing_authorized` | **NOT SATISFIED** | `_pap_release_gate_snapshot` → `licensing_authorized: row.licensing_status == "AUTHORIZED"` (`service.py:2773`). Default is `PENDING` (`service.py:2455`); `record_pap_release_licensing` never infers (`service.py:2595`). **License evidence newly obtained:** BMF Datenportal declares **CC BY-ND 4.0**, which textually permits commercial use (`provenance §4`). **BUT** the ND-derivative question (is runtime interpretation a prohibited "Bearbeitung"?) is a **legal** matter. No engineering path sets AUTHORIZED. | **Blocking** | **Yes — legal counsel required.** Record AUTHORIZED only on written legal/BZSt/BMF basis |
| `asset_approved` | **NOT SATISFIED** | Requires `asset.status == "PUBLISHED"` (`service.py:2774`). Lifecycle DRAFT→REVIEW→APPROVED→PUBLISHED→SUPERSEDED enforced (`service.py`; `set_pap_asset_status`). **No asset is PUBLISHED in any persistent DB** — only ephemeral SQLite test transactions publish one. DRAFT/REVIEW/APPROVED are provably non-executable (`resolve_pap_executor` never reads them; `resolve_germany_pap_asset` returns only PUBLISHED, `service.py:2417`). | **Blocking** | Yes — Super Admin ingests + approves + publishes |
| `golden_vectors_passed` | **NOT SATISFIED** | Requires `row.golden_vectors_passed` **and** `golden_vectors_source_sha256 == bound hash` **and** hash_ok (`service.py:2758-2763`); setter rejects wrong hash (`service.py:2643`). Frame exists (`golden_vector.py`; 11 tests). 31/31 exact matches were certified in one-off session runs vs the real artifact (8C-3/8G-2), **not** recorded on any persisted release, and only `LSTLZZ` is BMF-published (no official vector exists for SOLZLZZ/BK → §13 of brief bounds certification). | **Blocking** | Yes — Super Admin records certification for the exact ingested asset hash; legal for ND/vector use |
| `security_certified` | **NOT SATISFIED** | Requires `row.security_certified` (`service.py:2775`). Interpreter security is strong and re-verified this phase (no eval/exec/compile, closed grammar, allow-listed `BigDecimal` methods, XXE-safe, **new execution step/nesting budget** — see report §14), but **no release row records `security_certified=True`**. | **Blocking** | Yes — Super Admin records security certification |
| `release_approved` | **NOT SATISFIED** | Requires distinct approver vs preparer (`service.py:2764-2768`); `approve_pap_release` enforces maker-checker #1 (`service.py:2710`), `activate_pap_release` enforces maker-checker #2 + full gate (`service.py:2815`). **No release row exists / is approved in any persistent DB.** | **Blocking** | Yes — Super Admin (distinct actors) |

---

## Summary

| # | Count |
|---|---|
| Gates satisfied | **0 / 8** |
| Gates blocking | **8 / 8** |
| Engineering-only blockers | 0 (all eight require a persisted release/asset + legal/approval action) |
| Human / legal action required | All eight (ingest asset, record identity/hash/finality/licensing/golden/security, approve, publish, activate) |

**Conclusion:** `resolve_pap_executor()` remains fail-closed (`UnavailablePapExecutor`).
REGULAR and MIDIJOB German wage-tax remain blocked. MINIJOB (no PAP required) remains GO.
No partial/temporary activation, no environment bypass, no hardcoded ACTIVE.
