# Mexico (MX) — Phase 10f Implementation Report: Option B transfer, PILOT markers, go-live failures

Requested 2026-10-22 after the 10e report: option B for the D5 master-data copy (a tenant-run handshake with four safeguards), plus four follow-ups.

> **Sign-off required: Rugvedh, as ZP-PRIV owner, must approve this change before it is used in production.** It moves worker rows between two tenants (tenant-run, authorised by a release), and it gives one table, `payroll_mx_master_releases`, an RLS predicate that also admits a named second organisation (§3). The retired Super Admin copy routes **stay retired**.

**Base.**
- `main` = `5fa61c6` (PR #122, Phase 10e) plus Venu's PR #120 (NL report templates, no migration).
- The PR #122 deploy (run 39755905874) is **green**; production should be at **`d2a7c9e4f1b8`**.
- `nikhil` = `7982778` (10e), **5 commits behind `main`**: Venu's three NL files and merge commits, no overlap with Mexico. It was not fast-forwarded without asking; the PR merges cleanly either way.

**Alembic.**
- Before: a single head, `d2a7c9e4f1b8` (218 revisions).
- Now: a single head, **`e5b1d8f3a7c2`** (219 revisions).

**Git.** **Staged on `nikhil`, not committed**, as instructed.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,157 passed**, 4 local-only failures, none Mexico (§7). |
| 10f tests | `test_mexico_transfer.py` (9) and `test_mexico_transfer_migrations.py` (7, of which 5 run on PostgreSQL). All pass. The 10e pilot tests still pass (11). |
| Migration on PostgreSQL 17 | 7/7, three runs. |
| Production upgrade path on PostgreSQL 17 | `test_privacy_mexico_merge_migration.py` 2/2, from `e1a3c5e7f9b2` with a live reader on `users`, to `e5b1d8f3a7c2`. |
| Browser | **on 12/12** (§6). |
| ESLint / `check:undefined` / `vite build` | The new and changed files are clean; `payrollService.js` keeps its 32 pre-existing problems; 564 files have no undefined names; the build passes. |
| Route registry | Regenerated. It adds **only the 8 transfer routes**, all `org_admin`, `worker` wherever they touch worker rows. No other route changed. |

## 2. Option B — the tenant-run master-data handshake

`mexico_transfer_service.py` and `mexico_transfer_router.py` (`/api/payroll/mexico-transfer/...`).

**The four safeguards:**

| # | Safeguard | How it is enforced | Test |
|---|---|---|---|
| 1 | **Same employer RFC on both organisations** | The live organisation first records its own employer profile(s). Their open RFCs must **equal** the pilot's exactly (`MX_TRANSFER_RFC_MISMATCH`, with RFCs masked in the message). The pilot's profiles are **never copied**: the live organisation's own profiles stand in for them, matched by RFC, and everything beneath is remapped to them. | `test_the_live_org_must_have_recorded_the_same_employer` |
| 2 | **A one-time release, expiring after 7 days, revocable before use** | The release names one target. It **expires 7 days after it is released**, can be **revoked (with a reason) until it is used**, and is **USED** after one import. An expired, revoked or used release refuses (`MX_TRANSFER_RELEASE_UNAVAILABLE`); a used one cannot be revoked. | `…release_is_four_eyes_expires_in_7_days_and_is_revocable…`, `…uses_the_release_once` |
| 3 | **Two pilot-org admins release; two live-org admins import after reviewing the diff** | Pilot: one admin proposes, **a different admin** releases. Live: one admin proposes the import **with the hash of the diff preview they reviewed** (`MX_TRANSFER_DIFF_NOT_REVIEWED` otherwise), and **a different admin** approves and executes it (`MX_FOUR_EYES_REQUIRED`). The source must be unchanged since the release (`MX_COPY_SOURCE_CHANGED`). The copy runs in one transaction, and the diff report compares every copied row with its source. | `…needs_the_reviewed_diff_and_a_second_admin…`, `…change_to_the_pilot_after_the_release…` |
| 4 | **Audited on both sides, identifiers masked** | Every step writes **one audit row per organisation** (`organizationId`, `side` pilot or live). RFCs are masked (`mask_identifier`). No CURP, NSS, CLABE or name reaches an audit row. The diff preview masks RFC, CURP and NSS and shows the CLABE's last 4 only. | `test_every_step_is_audited_for_both_organisations_with_identifiers_masked` |

**Tenant scope.**
- Each side reads the other's rows **only inside an explicit `tenant_session` of that organisation**, authorised by the release. A test runs the import under the live organisation's real tenant context (where worker reads are filtered to the live organisation) and proves the pilot's rows are still read, through the pilot's own scope.
- The release row belongs to the pilot, so it is marked USED inside the pilot's scope.

**Guards.**
- **Release:** the kill switch is on, general availability is open, and the caller is a **pilot** organisation. Its grant may have ended, because releasing is its last act. That is why these routes sit outside `/mexico`'s guard and carry their own.
- **Import:** an open, live (non-pilot), Mexican organisation.

**Never copied:** payroll results, risk-premium approvals, credential references, INFONAVIT notices, collective agreements (refused), and the employer stamp test (reset).

**The Super Admin copy routes stay retired.** Their service path still exists and is tested; it shares the new copy engine.

**The copy engine** (shared by both paths) now reads the source **once as plain snapshots** and creates the target's rows from them. The 10e Super Admin path still passes its tests on it.

## 3. Data — migration `e5b1d8f3a7c2` (mx_transfer_m15)

- **A new table, `payroll_mx_master_releases`.** Its RLS predicate is the tenant predicate **plus `OR target_organization_id = tenant`**, so the pilot and the named live organisation can both read the release (counts, masked RFCs, a hash; never a worker value). **WITH CHECK is the owner-only predicate:** only the pilot writes it. Proven on PostgreSQL with a non-bypass role: owner 1 row, named target 1, a third organisation 0, and the target's insert for the owner refused. **For the ZP-PRIV owner:** this departs from the generic predicate on purpose; a future re-run of `apply_rls()` would narrow it back to the owner only, which fails closed.
- **A nullable `release_id` column** on the Mexico-only, empty `payroll_mx_master_copies`. The model's foreign key has the same explicit name as the migration's, so a schema built from the models downgrades cleanly.

| Measurement (PostgreSQL 17, three runs) | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `organizations` / `users` | 47–133 ms |
| ACCESS EXCLUSIVE | Only on the empty `payroll_mx_master_copies` (the column add); no other table |
| A writer holding `organizations` | Gives up after 5.09–5.14 s with nothing created |
| RLS | Two-party read, owner-only write (above); `classify()` treats the table as tenant |

## 4. PILOT on the run screen and the payslip view (not only the PDF)

- **Run screen:** `GET /mexico/runs/{id}/status` now returns `payroll.pilot`. `MXRunStatusBadges` shows a **PILOT banner** and a **Mode: PILOT** badge.
- **Payslip view:** a payslip generated in a pilot organisation records `pilot: true` in its snapshot. It is derived from the employee's Mexican statutory profile, so nothing is added to the calculation context or the input hash. The payslip's trace (`MXRunCalculationTrace`) shows a **PILOT banner**.
- Screenshots: §6.

## 5. Documents

- **Runbook §6, "When a go-live check fails":**
  - Contain (UNKNOWN runbook; no retry, no second filing, no edit).
  - Decide: the release owner, with the two Super Admins who signed the gate. If Zoiko is at fault, the gate's signature is reopened.
  - Pause new organisations.
  - Support the affected employer: an agreed outside-Zoiko filing or payment to meet the deadline, recorded afterwards.
  - Fix and prove, then close.

  **Stated honestly:** pausing is **all-or-nothing** today (the registry closes live employers too). A "no new Mexican organisations" switch is recorded as a **follow-up, not built**.
- **`OUT_OF_SCOPE_DEFECTS.md` OOS-11:** every Mexico refusal is worded "Mexico calculation blocked (…)", even when it is not a calculation (four-eyes, payments, filings, pilot, transfer, journal; 109 call sites). Cosmetic, Mexico-only, not fixed.
- **`PRODUCTION_STATE.md`:**
  - Rows for #120 and #122 (10e deploy green, production at `d2a7c9e4f1b8`).
  - **§7:** your uncommitted `/health/version` and `/health/ready` routes need route-registry entries, a `KNOWN_PUBLIC` update and a reviewed inventory diff **before they are ever committed**. Otherwise CI fails or the probes return 403.

## 6. Browser

**on 12/12.** Run with installed Chrome against the current build and a scratch backend. The scratch DB has general availability and an approved pilot grant, a pilot organisation with a committed pilot run, and a live PRODUCTION organisation of the same employer (its own employer profile, an active subscription, two admins). Everything is SYNTHETIC. Screenshots inspected (`phase10f-evidence/`).

| Check | Result |
|---|---|
| on-1 The **run screen** of a pilot run shows PILOT: banner plus "Mode PILOT" badge (`01_pilot_run_screen.png`) | PASS |
| on-2 The **payslip view** of a pilot payslip shows PILOT above its trace (`02_pilot_payslip_view.png`) | PASS |
| on-3 The proposing pilot admin cannot release (`MX_FOUR_EYES_REQUIRED`) | PASS |
| on-4 A second pilot admin releases: AVAILABLE, 7 days, employer RFC masked (`03_released.png`) | PASS |
| on-5 The live admin reviews the diff: both employees listed, RFC, CURP and NSS masked, CLABE last 4 only (`04_import_diff.png`) | PASS |
| on-6 The proposing live admin cannot approve the import (`MX_FOUR_EYES_REQUIRED`) | PASS |
| on-7 A second live admin approves: **EXECUTED, 8 rows copied, 0 differences** (`05_imported.png`) | PASS |
| on-8 The live organisation has the pilot's 2 employees and **no payroll result** | PASS |
| on-9 The pilot sees its release **USED** | PASS |
| on-10 Audit rows exist for the live side too; no RFC, NSS or name in any of them | PASS |
| on-z1 The NL compliance page is unchanged | PASS |
| on-z2 No 5xx and no page errors | PASS |

**Notes.**
- **Expected 4xx responses:** the only two are the deliberate four-eyes refusals.
- **The first attempt was a harness error:** it clicked the corrections panel's checkbox instead of the payslip row, so on-2 failed. The data was already right (both pilot payslips stored `pilot: true`). After the harness fix, run alone, the check passed 12/12.

## 7. Full suite

Five sequential chunks on scratch SQLite: **7,157 passed**, 113 skipped, 2 xfailed, and **4 local-only failures**, none Mexico.

| Chunk | Result |
|---|---|
| 0 | 852 passed, 15 skipped; the 3 `/health` registry tests and 1 manifest test (fixed, see below) |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed (Hong Kong docs) |
| 2 | 1,335 passed, 35 skipped |
| 3 | 1,633 passed, 56 skipped (includes the 10f tests) |
| 4 | 1,054 passed, 6 skipped |

**The 4 local-only failures:**
- **3 route-registry tests:** caused only by the uncommitted `/health/version` and `/health/ready` routes in `main.py` (see `PRODUCTION_STATE.md` §7).
- **`test_hong_kong_configuration…`:** it reads the uncommitted Hong Kong docs.

**The manifest failure, fixed:** `test_alembic_migration_manifest::test_no_registered_migration_is_deleted_renamed_or_edited` failed once, because I edited the new m15 (its downgrade index drop) after generating the manifest. Regenerated: the manifest differs from `HEAD` by the one added m15 line only. The manifest and alembic tests then passed, 10/10.

## 8. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `e5b1d8f3a7c2` | One new, empty table with its two-party RLS policy, and one nullable column on the empty `payroll_mx_master_copies`. About 0.05–0.13 s of SHARE ROW EXCLUSIVE on `organizations` / `users`, a brief ACCESS EXCLUSIVE on the empty copy table only; fails fast after about 5 s. |
| Transfer routes | 8 new, org admins only. Production has the flag off and the registry not AVAILABLE, so the release side refuses (`MX_DORMANT`) and the import side refuses (`MX_TRANSFER_NOT_LIVE`). |
| Run status and payslip snapshot | A new `pilot` field, false everywhere: no pilot organisation exists. |
| Screens | A transfer panel and the PILOT markers; nothing renders as pilot in production. |

**Net:** additive, Mexico stays dormant, and no other jurisdiction's behaviour changes.

## 9. Open

- **Rugvedh's sign-off** (above).
- The "no new Mexican organisations" switch (runbook §6 follow-up).
- OOS-11 wording.
