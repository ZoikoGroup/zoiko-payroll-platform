# Mexico (MX) — Phase 11c Implementation Report: border-zone Fecha, overtime days, validate-only preview

Requested 2026-10-23: three items. (1) Border-zone time zones from the pinned c_CodigoPostal catalog. (2) The dates on which overtime was worked, recorded on the approved hours and emitted as `HorasExtra` (S4 p. 51). (3) 11c, the validate-only preview (D5).

> **Review required: Rugvedh (ZP-PRIV).** This touches worker data: the preview reads identifiers in memory to build each receipt, and the hours record gains a column.

**Base and production.**
- **PR #128 (11b) was merged into `main` at 10:06Z by NikhilZoiko, with no review on the PR.** It was described to me as a draft awaiting Rugvedh's approval.
- Its deploy, run **39936691189**, is green (10:06–10:35Z). 11b had no migration, so production stays at `a8e4c1f7d3b5`.
- Recorded in `PRODUCTION_STATE.md`, with 11b added to the after-the-fact review list.
- `nikhil` = `6efb642`.

**Merged with `main` (approved 2026-10-26).** While 11c was waiting, `main` gained Venu's Brazil / NL migrations (PRs #124 and #129; #129 deployed green on 2026-10-24, so production should be at `8f90dde5f7b5`). His chain starts at 11a's `a8e4c1f7d3b5`, the parent m18 also had, so merging 11c as built would have left **two alembic heads** and failed the deploy. With your approval:
1. 11c was committed locally as `6513477`.
2. `origin/main` was merged into `nikhil` (`4bdaf00`). The three conflicts were all migration bookkeeping (the manifest and two pin tests).
3. **m18 was re-parented onto `8f90dde5f7b5`.**
4. The manifest was rebuilt from `main`'s (+1 line); the pins moved to 228 revisions, plus the pending objects from the new production head.
5. The route registry was checked against a fresh generation: identical.
- Nothing was pushed. Your uncommitted files were not touched.

**Alembic.**
- Before (`main`): a single head, `8f90dde5f7b5` (227 revisions).
- Now: a single head, **`b9f3d5a1c7e2`** (228 revisions), revising `8f90dde5f7b5`.

**Git.**
- `nikhil` = `4bdaf00`: two local commits (11c and the merge), **not pushed**.
- The follow-up after the merge (the m18 test's parent, this report, the regenerated browser evidence) is **staged, not committed**.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | §8 |
| Border-zone Fecha | 11 change-over cases at the 2026 boundaries, plus the catalog checks, pass |
| Overtime days | `test_mexico_overtime_dates.py`: 4 passed |
| Preview | `test_mexico_cfdi_preview.py`: 4 passed |
| Migration `b9f3d5a1c7e2` on PostgreSQL 17 | 5/5, three runs, before and again after the merge. After the merge: production upgrade path, m17, m16 and named RLS exceptions 17/17 |
| Browser | §7 |
| ESLint / `check:undefined` / `vite build` | The changed components are clean. `payrollService.js` keeps its 32 pre-existing problems (the same count as in 10f). After the merge: 579 files with no undefined names, and the build passes |
| Route registry | +2 routes only: the org preview (worker, org_admin) and the Super Admin summaries (platform) |

## 2. Item 1 — border-zone time zones: **the catalog does carry the rules**

**The columns** under c_CodigoPostal's "Referencias del Huso Horario" header:

| # | SAT's header | Holds |
|---|---|---|
| 1 | Descripción del Huso Horario | the zone's name |
| 2 | Mes_Inicio_Horario_Verano | month summer starts |
| 3 | Día_Inicio_Horario_Verano | the day, e.g. "Segundo domingo" |
| 4 | **Día_Inicio_Horario_Verano** (repeated) | the hour, e.g. "02:00" |
| 5 | Diferencia_Horaria_Verano | summer UTC offset |
| 6 | Mes_Inicio_Horario_Invierno | month winter starts |
| 7 | Día_Inicio_Horario_Invierno | the day |
| 8 | **Día_Inicio_Horario_Invierno** (repeated) | the hour |
| 9 | Diferencia_Horaria_Invierno | winter UTC offset |

**An 11a defect, fixed.** SAT's header gives the hour column (4 and 8) the same name as the day column. My 11a generator keyed attributes by header name, so the hour overwrote the day: the border rows had lost "Segundo domingo" / "Primer domingo".
- The generator now keeps every column. A repeated header gets a positional suffix (`… #2`), and every repeat is listed in the manifest (`duplicateHeaders`).
- The extract (`catalogs.json.gz`) was regenerated. The XSDs and their checksum are unchanged, so a release loaded from `sat_2026_08` still verifies.
- **A release already loaded from the old extract keeps the old catalog entries.** The time-zone lookup reads the pinned set, not the release entries, so Fecha is unaffected. Production has no release loaded.

**The six rules across all 95,748 postal codes:**

| Postal codes | States | Rule |
|---|---|---|
| 81,888 | 27 states | Tiempo del Centro, −6 all year |
| 7,990 | BCS, NAY, SIN, SON | Tiempo del Pacífico, −7 all year |
| 1,000 | ROO | Tiempo del Sureste, −5 all year |
| 2,040 | COA, NLE, TAM | Centro en Frontera: summer −5 from the 2nd Sunday of March 02:00, winter −6 from the 1st Sunday of November 02:00 |
| 2,000 | BCN | Noroeste: summer −7 / winter −8, same dates |
| **830** | **CHH** | **Centro en Frontera: summer −7, winter −6** |

**Implemented** (`mexico_cfdi_input.local_issue_time`):
- Fecha uses the place of issue's own row: its offsets and, where it observes summer time, the month, the "Nth weekday" and the hour each season starts.
- **`MX_CFDI_TIMEZONE_UNSUPPORTED` is removed.** A row that cannot be read, or is inconsistent, refuses with `MX_CFDI_TIMEZONE_RULE_INVALID`.

**One interpretation, stated:** SAT gives the change-over hour as "02:00" without saying on which clock. It is read as local time just before the change: standard time when summer starts, summer time when it ends. This is the usual DST convention.

**Tests.** One second either side of each 2026 boundary, for both seasonal groups:
- Tijuana 21000: 01:59:59 → 03:00 on 8 March; 01:59:59 → 01:00 on 1 November.
- Piedras Negras 26000: the same two jumps.
- Mid-summer and mid-winter instants, and a fixed-offset control (06600).

**Source anomaly, for the G1 owner:** the **830 CHH rows** give a summer offset (−7) *behind* their winter offset (−6), the opposite of every other summer-time rule in the file. They are refused as inconsistent (`MX_CFDI_TIMEZONE_RULE_INVALID`) rather than corrected. A test pins the count (830) and the state.

## 3. Item 2 — overtime dates and `HorasExtra`

**Record (four-eyes, as today).**
- `payroll_mx_approved_hours` gains `overtime_dates` (migration **`b9f3d5a1c7e2`**, nullable JSON). `POST …/hours` accepts `overtimeDates`.
- Each date must fall inside the recorded week, with no repeats, and only together with overtime hours.
- The DRAFT row is approved as before, by someone other than the recorder.
- The dates are optional; rows recorded before keep `[]`.

**Engine.** Each approved overtime week in the result now carries its `dates` and the first-tier (double-rate) amount, next to the existing tier hours.

**Builder** (S4 pp. 48, 51–53). A perception 019 gets one `HorasExtra` node:
- `Dias` = the distinct recorded dates;
- `TipoHoras` = the c_TipoHoras code SAT describes as "Dobles", read from the pinned catalog;
- `HorasExtra` = the hours, rounded as S4 p. 52 instructs;
- `ImportePagado` = the amount.

**019 stays refused** (`R-DETAIL-NODE`), with the reason named, when:
- any approved week has no dates recorded;
- **a week has triple-rate hours.** S4 counts days per hour type, and dates alone don't tell which days the triple-rate hours fell on. That would need hours per date.

**What can't run yet:** the engine still blocks any approved overtime with `MX_HOURLY_RATE_RULE_MISSING`, because no rule derives an hourly rate (S26). So the path is proven in parts:
- the record, through the service;
- the engine's tier and dates split, with synthetic tier content;
- the detail assembly and the builder, with a validated document containing the node.

**Migration `b9f3d5a1c7e2` on PostgreSQL 17** (three runs, 5/5 each):
- ACCESS EXCLUSIVE on `payroll_mx_approved_hours` only; no other table is locked exclusively.
- organisations and employees stay readable in flight (about 90–120 ms including the test's own probing);
- with a reader on the table it fails fast in 5.11–5.14 s, with nothing applied;
- the table's RLS policy is unchanged;
- the real CLI and the schema-drift check pass.
- The production upgrade path from `e1a3c5e7f9b2` now also adds the column (`AFTER_E1A3_COLUMNS`): 11/11.
- **The migration names its table literally.** The deploy's drift filter (`drift_pending_filter.pending_objects`) only reads literal names, and it now reports the pending column, which a test pins.

## 4. Item 3 — the validate-only preview (11c, D3 + D5)

**`POST /api/payroll/mexico/runs/{id}/cfdi/validate`** (org admin). On a committed Mexican run, every payslip's receipt is assembled and built **in memory** with the real SAT builder, then validated against the pinned XSDs.
- It uses the newest **Approved** or Active release whose pinned set still verifies (D3: Approved is enough).
- Nothing is signed, stored, queued or sent.
- It returns, per payslip: VALID / REFUSED, the refusal code, the findings (rule id + text, value-free by construction and scrubbed again) and the **SHA-256 of the would-be payload**. **Never the XML.**
- When no such release exists it refuses (`MX_CFDI_NO_APPROVED_RELEASE`), and likewise for a run that isn't committed (`MX_CFDI_RUN_NOT_COMMITTED`).

**Stored:** one audited summary per preview (`mx_cfdi_validation`): counts, codes, rule ids, payload hashes, the release and set. No names and no identifiers; a test checks both.

**Super Admin:** `GET /api/super-admin/compliance/mexico/cfdi/validations` and a new "Validate-only previews (G1 evidence)" table on the CFDI lifecycle tab. Both show summaries only.

**The SDI refusal is shown first.** Any finding waiting for a G1 decision is collected into `awaitingDecisions` and shown as a banner above the results: "Waiting for a G1 decision — no receipt can pass until it is recorded". Today that is the source of SalarioDiarioIntegrado. The Super Admin row says "awaiting a G1 decision".

**Tests:**
- Today's state: every receipt shows the SDI refusal, `awaitingG1Decision`.
- With a (test-only) SDI source: valid, a 64-hex hash, and no XML or identifier in the response.
- No document, outbox item or stored file is created.
- The audit summary carries no name or identifier.
- An Approved release works; no release or an uncommitted run refuses.
- Via HTTP with the invalid CURP from 11b: the finding is exactly `Receptor@Curp: SCHEMAV_CVC_PATTERN_VALID`, and neither the CURP nor its middle characters appear in the org response or the Super Admin summaries.

## 5. Files

- **Backend:**
  - `mexico_cfdi_input.py`: Fecha from the catalog's rules; `HorasExtra` detail.
  - `mexico_cfdi_xml.py`: `HorasExtra`, plus two cited constants: `OVERTIME_PERCEPTION` 019 and `OVERTIME_TYPE_DOUBLE` "Dobles".
  - `mexico_cfdi_preview.py`: new.
  - `mexico_run_service.py`: overtime dates on the record.
  - `engine/…/labor.py`: dates and first-tier amount per week.
  - `models.py`: the column.
  - Routes in `mexico_org_router.py` and `mexico_router.py`.
  - `scripts/mx_build_cfdi_schema_set.py`: repeated headers.
  - The regenerated `catalogs.json.gz` and `manifest.json`.
- **Migration:** `b9f3d5a1c7e2_mx_overtime_dates_m18.py`; manifest +1 line.
- **Tests:** `test_mexico_overtime_dates.py`, `test_mexico_overtime_dates_migrations.py`, `test_mexico_cfdi_preview.py`, and additions to `test_mexico_cfdi_builder.py`. Pins: head and 222, pending columns, production-path columns.
- **Frontend:**
  - `MXCfdiStagePanel.jsx`: Validate CFDI and the preview.
  - `MXCfdiLifecycleTab.jsx`: the summaries.
  - The service calls.
- **Registry and inventory:** +2 routes.
- **Docs:** this report; `PRODUCTION_STATE.md` (PR #128).

## 6. Decisions still open (unchanged from 11b, plus one)

- The source of SalarioDiarioIntegrado: every real-shaped receipt shows this refusal.
- INFONAVIT credit, vacation payout, annual refund mappings; the subsidy (needs a new source); separation receipts.
- **New:** the 830 CHH postal codes whose SAT rows are inconsistent.
- **New:** hours per date, if triple-rate overtime is to be reported.
- Before any overtime can be calculated at all: the hourly-rate rule (S26).

## 7. Browser

Real Chrome (headless) against a scratch database: a committed Mexican run, a release loaded from `sat_2026_08` and approved by two Super Admins, and the ISR / IMSS mappings approved. The harness is in `phase11c-evidence/harness/`. **on 7/7 PASS**, with no 4xx / 5xx responses and no console errors.

| # | Check |
|---|---|
| on-1 | The org admin clicks **Validate CFDI (no stamping)**. The preview shows the "Waiting for a G1 decision" banner first, naming SalarioDiarioIntegrado |
| on-2 | The payslip is REFUSED with `MX_CFDI_INPUT_MISSING` and no payload hash |
| on-3 | The preview response carries no XML and no identifier |
| on-4 | Nothing was signed, stored or queued (document and outbox counts unchanged) |
| on-5 | The Super Admin's CFDI lifecycle tab lists the summary: run, release, 0/1 valid, the code, "awaiting a G1 decision", and no worker name |
| on-z1 / z2 | NL unchanged; no 5xx, no page errors |

**Re-run after the merge with `main`: 7/7, no 4xx / 5xx, no console errors; screenshots re-inspected.** The first run also passed, but its screenshot showed "REFUSED" running into the code, with the code printed twice. The table was fixed (cell spacing; the code shown once) and the whole run repeated.

Screenshots, inspected:
- `on_01_preview_awaiting_g1.png`: the banner and the refused row;
- `on_02_sa_validation_summary.png`: the Super Admin summary row.

**The throwaway PostgreSQL cluster was rebuilt (2026-10-26).** After the session gap its system-catalog files were partly missing (`could not open file "global/2964"`): the cluster lives in the OS temp folder and came back from an unclean shutdown. A fresh PostgreSQL 17 cluster was initialised in the scratchpad, on the same local-only port, and every PostgreSQL result above comes from it.

## 8. Full suite, and the CI failure on PR #130

**PR #130 (`4bdaf00`, 11c plus the merge) was pushed and merged into `main` at 02:56Z (2026-10-26), before this verification finished.** Its CI test job failed, and **the deploy job was skipped**: production is unchanged at `8f90dde5f7b5` (PR #129's code), and m18 has not run. CI: 7,414 passed, 2 failed. Both failures are mine:

| Failing test | Cause | Fix (staged) |
|---|---|---|
| `test_mexico_overtime_dates_migrations::test_revision_links` | The test's expected parent was updated after the merge commit, so it was not in what was pushed | `PARENT = "8f90dde5f7b5"` |
| `test_mexico_dormancy::test_every_route_is_listed` | The new org route `POST /runs/{id}/cfdi/validate` was not added to `ORG_ROUTES`, the list proving every Mexico org route refuses while dormant. Missed by me | Added; the parametrised dormancy test now covers it too |

**Full suite with the fix**, five sequential chunks on scratch SQLite, run alone: **7,413 passed**, 128 skipped, 2 xfailed, and **4 local-only failures**, none Mexico. These are the same four as in 10f–11b, and they come from uncommitted local files, so CI does not see them.

| Chunk | Result |
|---|---|
| 0 | 867 passed, 15 skipped, 3 failed (route registry: only the uncommitted `/health/version`, `/health/ready` routes in `main.py`) |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed (`test_hong_kong_configuration…`: uncommitted Hong Kong docs) |
| 2 | 1,478 passed, 37 skipped (includes `test_mexico_dormancy.py` and `main`'s new Brazil / NL tests) |
| 3 | 1,726 passed, 69 skipped (includes the 11b / 11c CFDI, overtime and preview tests) |
| 4 | 1,059 passed, 6 skipped |

`test_communications_dispatch::test_deactivate_organization_response_precedes_email_send` failed once in an earlier, interrupted run. It is a known flaky timing test (1 failure in 3 reruns, then green), not Mexico.

## 9. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `b9f3d5a1c7e2` | One nullable column on the empty `payroll_mx_approved_hours`; a brief exclusive lock on that table only; fails fast after about 5 s |
| Overtime dates | An optional field on the hours record; nothing else changes. Overtime is still blocked by the missing hourly-rate rule |
| Preview route and Super Admin summaries | Mexico is dormant, so the org route refuses (`MX_DORMANT`). No release is Approved, so even a pilot would see `MX_CFDI_NO_APPROVED_RELEASE` |
| Fecha | Code only; no CFDI is generated in production |
| Catalog extract | Regenerated with the repeated columns; the XSD checksum is unchanged |

**Net:** additive. Mexico stays dormant; no other jurisdiction changes.
