# Mexico (MX) — Phase 10d Implementation Report: Release gates

Spec ZP-MX-ENG-001 v1.0 §22 · plan `MEXICO_PHASE_10_PLAN.md` (approved 2026-10-21; this is 10d, built under D9 and D10).

**Base.** `nikhil` = `cdd53d2` (10c), on top of 10a and 10b, none of which is merged yet. Production is at `e7a2c4f9b1d6`.

**Alembic.** No migration. The head stays `b3f7c1e9d5a2`.

**Git.** Committed on `nikhil`, **not pushed**.

**What it is.** 10d *prepares* the go-live: the evidence register, the checklists, the runbook and a readiness view driven by real evidence. **It signs nothing, and nothing in it switches Mexico on (D10).**

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,120 passed**, 4 failed: all local-only, none Mexico (§5). |
| 10d tests | `test_mexico_release_gates.py` (6), plus the updated readiness pins. All pass. |
| Browser | **off 8/8** (§4). |
| ESLint / `check:undefined` / `vite build` | 0 errors in the changed file; 561 files have no undefined names; the build passes. |
| Migration / routes | None. The existing readiness route returns more fields; no route registry change. |

## 2. What was built

### Gates and legal decisions from evidence

Before, `gate_states` returned all eight gates as OPEN, hard-coded.

Now a gate or legal decision is decided by its **evidence**, using the same rule as the Netherlands. The evidence is a source artifact tagged `MX-GATE-Gn` (or `MX-DECISION-…`). It must be:
- not superseded;
- backed by an **uploaded document**;
- **reviewed by a Super Admin other than its creator** (the review API already refuses the creator; an artifact with no creator on record never counts).

| State | Meaning |
|---|---|
| OPEN | No evidence. |
| SUBMITTED | Evidence created or uploaded, not yet independently reviewed. |
| SIGNED / RECORDED | Uploaded and reviewed by a second Super Admin. |

**Legal decisions.**
- `MX-D-RETENTION-PERIOD`, `MX-D-RETENTION-END` and `MX-D-HOSTING` (plan D9).
- Recording the retention period **only allows proposing** a period; a second Super Admin must still approve it, and until then every purge is refused (tested).

### Readiness view

`GET /super-admin/compliance/mexico/readiness` and the **Readiness G1–G8** tab now show:
- each gate's §22 definition, evidence tag and state, linked to its source;
- the number of gates signed;
- the service registry state, the onboarding flag and whether Mexico is available;
- the 3 legal decisions;
- the 8 retention categories (from 10c) with why each is blocked;
- the release documents.

**`available`** was hard-coded as `false`. It is now true only when the registry is AVAILABLE **and** `MX_TENANT_ONBOARDING_ENABLED` is on. A test proves that with all 8 gates signed, the registry can open, but Mexico stays unavailable while the flag is off.

### Documents

| Document | Contents |
|---|---|
| `docs/mexico/release-gates/README.md` | The evidence register: how a gate is signed (with the real screen names), the gates, and the legal decisions. |
| `docs/mexico/release-gates/G1…G8/CHECKLIST.md` | One per gate: §22 definition, evidence tag, the sources it needs (by register number, checked against the spec's S1–S23 table and the addendum's S24–S33), the evidence checklist, what Zoiko already provides, and a sign-off table. |
| `docs/mexico/MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md` | In order, each step with its check: sources and content, gates and decisions, external setup, switching on, rollback. |
| `docs/mexico/MEXICO_RELEASE_CHECKLIST.md` | Gates, the legal decisions including **hosting and cross-border transfers (D9)**, Rugvedh's review items, external items, engineering items. |

A test checks that every document the readiness view names exists.

**One finding recorded in G4.** S22 (Mexico City Fiscal Code) is saved but marked `WRONG_VERSION` in the manifest: it is the 2022 text with a 3% ISN rate, while the spec says 4%. The current consolidated text is still needed.

## 3. What this does in production when merged

| Change | Production effect |
|---|---|
| Readiness | The Super Admin readiness tab shows evidence-driven gates, all OPEN (no `MX-GATE-*` artifacts exist), with decisions, retention and documents. |
| `available` | Stays false (registry PLANNED, flag off). |
| Retention | Unchanged: no decision is recorded, so every category stays BLOCKED_UNDECIDED. |

**Net:** no behaviour change for any jurisdiction, and Mexico stays dormant.

## 4. Browser

**off 8/8.** Run with installed Chrome against the current build and a scratch backend, with the flag off as in production, and two SYNTHETIC Super Admins. No 4xx or 5xx responses, and no console errors. Screenshots inspected (`phase10d-evidence/`).

| Check | Result |
|---|---|
| The Readiness G1–G8 tab lists G1–G8 with their evidence tags, every gate OPEN | PASS |
| 0/8 signed, onboarding flag off, not available; 3 legal decisions OPEN; 8 retention categories BLOCKED_UNDECIDED | PASS |
| The four release documents are named | PASS |
| A G1 evidence pack created and uploaded by Super Admin A shows **SUBMITTED** | PASS |
| Super Admin A cannot review their own pack (400) | PASS |
| Super Admin B clicks **Mark reviewed** on the Sources tab: G1 shows **SIGNED (source #1)** | PASS |
| 1/8 signed and Mexico still not available | PASS |
| No 5xx and no page errors | PASS |

## 5. Full suite

Five sequential chunks on scratch SQLite, run 2026-10-22: **7,120 passed**, 104 skipped, 2 xfailed, **4 failed**. **None of the 4 is Mexico's, and none comes from 10d.**

| Chunk | Result |
|---|---|
| 0 | 853 passed, 15 skipped, 3 failed |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed |
| 2 | 1,321 passed, 31 skipped |
| 3 | 1,621 passed, 51 skipped (includes the 6 Phase 10d tests) |
| 4 | 1,042 passed, 6 skipped |

The 4 failures:
- **`tests/privacy/test_route_registry.py`, 3 tests:** caused only by the 4 uncommitted `/health/version` and `/health/ready` routes in the working-tree `main.py`. CI does not have them.
- **`test_hong_kong_configuration.py::test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed`:** it checks the uncommitted Hong Kong docs in the working tree. Not Mexico.

## 6. Decision for the owner

**Should onboarding also require the registry to be AVAILABLE?** Today `MX_TENANT_ONBOARDING_ENABLED` alone opens Mexico. Making `onboarding_enabled()` also require registry AVAILABLE (refused until all 8 gates are signed) would make a premature flag change harmless. It is a small change, but every test and harness that sets the flag would also need to seed the registry. **Recommended.** Listed in the release checklist.

## 7. Phase 10 is complete

10a payments · 10b journal · 10c privacy and retention · 10d release gates. Mexico's **buildable scope is complete**; it is **not code-complete**. The integration code still to write once its inputs arrive (content transcription and golden vectors, the CFDI builder and XSD, the PAC adapter, the SPEI generator, the IDSE / SUA layouts) is listed in `PRODUCTION_STATE.md` §0.
