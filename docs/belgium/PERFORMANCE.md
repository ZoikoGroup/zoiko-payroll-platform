# Belgium (ZP-BE-ENG-001) — performance at scale (Block I2)

For: engineers and whoever signs off Belgian capacity. Belgian code only, measured on local SQLite with synthetic
DEMO data (mixed white-collar and manual workers, the DEMO pack).

## How it was measured

`backend/tests/perf/be_scale_harness.py` builds a demo organisation with N employees on a throwaway SQLite file,
then runs and times each step:

| Step | What it covers |
|------|----------------|
| preview | 1.93 / 18.0 | 2.60 / 17.5 | 1.02 / 8.2 | 5.22 / 7.1 | 19.48 / 7.0 |
| generate | 2.04 / 21.6 | 3.21 / 21.3 | 1.53 / 14.8 | 15.32 / 14.1 | 63.19 / 14.0 |
| preflight | 1.07 / 9.1 | 1.82 / 9.1 | 0.33 / 3.2 | 3.02 / 3.0 | 13.15 / 3.0 |
| acknowledge | acknowledging every engine exception |
| approve | 2.79 / 31.8 | 6.95 / 31.4 | 1.31 / 14.4 | 14.03 / 13.6 | 75.02 / 13.5 |
| payslip view ×50 | 0.22 / 2.0 | 0.29 / 2.0 | 0.27 / 2.0 | 0.27 / 2.0 | 0.51 / 2.0 |
| payslip PDF ×50 | 0.76 / 5.0 | 0.96 / 5.0 | 0.75 / 5.0 | 0.75 / 5.0 | 1.45 / 5.0 |
| DmfA | one quarter build |
| Belcotax | the 281.10 build for the year |
| parallel import | 0.23 / 2.3 | 0.42 / 2.1 | 0.26 / 2.3 | 2.07 / 2.0 | 10.20 / 2.0 (2,000 rows) |

For each step it records:
- wall time;
- SQL statements, and statements per item (per employee or per payslip);
- Python peak memory, with `--memory` (tracemalloc; slower, so measured in a separate run).

```bash
cd backend
python -m tests.perf.be_scale_harness --employees 2000 --db /tmp/be_scale_2000.db [--memory]
```

`BE_SCALE_TOP=1` also prints the most frequent SELECT tables per step; that is how the batching candidates were
found.

**Before** = committed code at `edfec72`, run from an export with the same harness. **After** = this block.

## Results

Each cell is seconds / statements per item.

| Step | Before, N=50 | Before, N=100 | After, N=50 | After, N=500 | After, N=2,000 |
|------|-------------:|--------------:|------------:|-------------:|---------------:|
| preview | 1.93 / 18.0 | 2.60 / 17.5 | 1.02 / 8.2 | 5.22 / 7.1 | 19.48 / 7.0 |
| generate | 2.04 / 21.6 | 3.21 / 21.3 | 1.53 / 14.8 | 15.32 / 14.1 | 63.19 / 14.0 |
| preflight | 1.07 / 9.1 | 1.82 / 9.1 | 0.33 / 3.2 | 3.02 / 3.0 | 13.15 / 3.0 |
| **acknowledge exceptions** | **104.25 / 457** | **553.27 / 907** | 0.36 / 4.0 | 4.67 / 4.0 | 41.37 / 4.0 |
| approve | 2.79 / 31.8 | 6.95 / 31.4 | 1.31 / 14.4 | 14.03 / 13.6 | 75.02 / 13.5 |
| payslip view ×50 | 0.22 / 2.0 | 0.29 / 2.0 | 0.27 / 2.0 | 0.27 / 2.0 | 0.51 / 2.0 |
| payslip PDF ×50 | 0.76 / 5.0 | 0.96 / 5.0 | 0.75 / 5.0 | 0.75 / 5.0 | 1.45 / 5.0 |
| DmfA quarter | 0.57 / 6.8 | 1.39 / 6.7 | 0.61 / 3.3 | 2.92 / 3.0 | 12.96 / 3.0 |
| Belcotax 281.10 | 0.37 / 6.1 | 0.88 / 6.0 | 0.35 / 5.1 | 2.92 / 5.0 † | 13.19 / 4.0 |
| parallel import | 0.23 / 2.3 | 0.42 / 2.1 | 0.26 / 2.3 | 2.07 / 2.0 | 10.20 / 2.0 (2,000 rows) |

Notes on the before columns:
- They stop at 100 employees. A before run at 500 was stopped after 16 minutes, still inside the acknowledgement
  step, with 1.1 GB of RAM and 950 s of CPU.
- The acknowledgement step is the N+1 / O(N²) pattern. Its statements per item doubled when the organisation
  doubled (457 → 907), and the time went up 5.3×.

† measured before fix 5 (the Belcotax fiche lookup); at 2,000 employees that fix took Belcotax from 17.05 s / 5.0 to 13.19 s / 4.0.

After the fixes, **statements per item are flat from 50 to 2,000 employees** in every step: no N+1 remains. At 2,000 employees, approval is 6,041 SELECTs (3 per employee) and 21,002 INSERTs (ledger entries and audit). The writes are inherent.

Peak Python memory (tracemalloc, after the fixes):

Peak Python allocations per step at **500 employees** (tracemalloc), plus the whole process at 2,000:

| Step | Peak MiB at N=500 |
|------|------------------:|
| preview | 16 |
| generate | 651 |
| preflight | 642 |
| acknowledge (all) | 2 |
| **approve** | **1,100** |
| payslip view ×50 | 47 |
| payslip PDF ×50 | 10 |
| DmfA quarter | 648 |
| Belcotax | 651 |
| parallel import | 643 |

**Process peak at 2,000 employees: 4,323 MiB** (psutil peak working set, timing run).

The tracemalloc run at 2,000 was stopped: it is about 6× slower, and acknowledging alone took 326 s.

**This was the main capacity finding (Block I2). It is resolved by Block J2: see the J2 section.** Every step that reads the whole run loads every payslip's 240 KB snapshot
into Python objects:
- preflight;
- approval (preflight, fingerprint and ledger);
- DmfA and Belcotax (employer totals and the demo flag).

Memory therefore grows at about 2 MB per employee. **A 2,000-employee approval needs about 4 GB on one worker.**
The fix is the snapshot slimming in "Remaining super-linear wall time" below; it is an owner decision because it
changes the stored audit format. Until then, size the backend worker's memory for the largest Belgian organisation
(about 2.2 MB × employees, plus headroom), or cap the run size per organisation. A code-only stop-gap, reading only
the needed JSON paths instead of whole snapshots, was considered and not done in this block. It would have to
reproduce the approval fingerprint byte for byte and the empty-snapshot semantics, and it is best done together with
the slimming.

## Block J2 — snapshot version 2 and memory (owner decision: fix now)

### The version-2 format (JSON shape only, no migration)

`payslip_items.be_calculation_snapshot` now carries `"snapshot_version": 2`. The changes from version 1:

| Part | Version 1 | Version 2 |
|------|-----------|-----------|
| Pack rows in `frozenContext` | Full copy: `rateMap` + `slabs`, about 110 KB | `frozenContext.version: 2` + `packRef`: pack row id, `packVersion`, the exact rate / slab **row ids** the resolver handed to the engine (in order), and `rowsHash` (sha256 of their frozen fields, the same fields version 1 copied) |
| Used content rows | Twice: `usedRows` + `trace.contentUsed`, about 60 KB each | Once, in `usedRows`, compact and lossless: null fields omitted, `"usedRowsFormat": "compact"`. `trace.contentUsedRef: "usedRows"` points at them |
| Size (one payslip) | about 238 KB | about 50 KB |

How each version is read:
- **Replay of version 2** (`be_thaw_context(frozen, db)`, `be_replay`) reloads the referenced rows by id. It
  refuses if a row is missing or if `rowsHash` no longer matches: a payslip is never replayed with rules that
  differ from the ones it was calculated with.
- **Version 1** replays from its own copy, as before.
- `be_snapshot_used_rows()` and the payslip API (`be_payslip_view`) return the used rows in their full form for
  both versions. The expanded list hashes to the engine's own `hashes.content`, so the compact form is verified
  on every payslip.
- A row that cannot be referenced (no id or pack) falls back to the version-1 copy, so nothing is ever left
  unreplayable.

No auditable fact is removed:
- every version-1 top-level key is still present;
- the rows are recoverable exactly, and hash-verified;
- the engine output, and with it `hashes`, the approval fingerprint and golden certification, is unchanged.

`tests/test_belgium_snapshot_v2.py` replays a **captured version-1 snapshot**
(`tests/fixtures/belgium_snapshot_v1.json`) through every reader:
- replay;
- the payslip view and PDF;
- the DmfA / Belcotax employer totals and the demo flag;
- the parallel-run amounts.

It also proves the version-2 properties:
- exact replay, and refusal without the database;
- refusal when a referenced row has changed;
- a correction of a version-2 payslip is itself version 2.

### Readers no longer materialise every snapshot

| Change | Where |
|--------|-------|
| Run-wide readers fetch only the JSON paths they need (`be_snapshot_facts`, JSON-path extraction) | preflight, approval hook, fingerprint (byte-identical payload), ledger posting, DmfA / Belcotax / FinProf totals and the demo flag, the payment batch demo check, the parallel import |
| `be_calculation_snapshot` is a **deferred** column, so a `PayslipItem` query, including shared ones (the approval e-mail notification, any country's listings), no longer loads Belgian snapshots | `models.py` (the Belgian column only) |
| Belgian loops that need whole snapshots load them in one query (`undefer`) | payment preview, correction checks |
| Template freezing skips Belgian payslips in SQL, so it doesn't load them | `payslip_template_service.freeze_run_templates` (the H1 Belgian guard, moved into the query) |

Cost: the single-payslip view and PDF read their deferred snapshot with one extra query (3 and 6 statements per
payslip, from 2 and 5).

### Before / after (J2)

Python peak per step (tracemalloc), MiB at 500 employees, with MiB per employee in brackets:

| Step | Before J2 | After J2 |
|------|----------:|---------:|
| generate | 651 (1.30) | **236 (0.47)** |
| approve | 1,100 (2.20) | **231 (0.46)** |
| preflight | 642 | 4.5 |
| DmfA quarter | 648 | 10.2 |
| Belcotax | 651 | 11.8 |
| parallel import | 643 | 5.4 |
| payslip view ×50 / PDF ×50 | 47 / 10 | 31 / 9 |

Process peak (psutil):
- **2,000 employees: 4,323 MiB → 1,435 MiB.**
- At 500 employees after J2: 847 MiB.
- Marginal cost between 500 and 2,000: **0.39 MiB per employee**, against the about 0.5 MiB target.

Wall time at 2,000 employees (seconds; statements per item unchanged and flat):

| Step | After I2 | After J2 |
|------|---------:|---------:|
| generate | 63.2 | 49.8 |
| preflight | 13.2 | 5.0 |
| approve | 75.0 | 24.6 |
| DmfA | 13.0 | 6.6 |
| Belcotax | 13.2 | 7.3 |
| parallel import (2,000 rows) | 10.2 | 2.7 |
| acknowledge, one by one | 41.4 | 31.4 |
| **acknowledge, bulk (J3)**, all 4,000 exceptions in one request | — | **2.36** (3 SELECT + 1 UPDATE + 4,000 audit rows) |

Guard: `tests/perf/test_belgium_scale.py` (slow, `ZP_BE_SCALE=1`) now also asserts generation and approval stay at
or under **0.6 MiB per employee**. The view / PDF statement ceilings are 4 / 7.

## What was fixed (Belgian code only)

| # | Pattern | Where | Fix |
|---|---------|-------|-----|
| 1 | **O(N²)**: each exception acknowledgement re-ran the whole-run preflight. That loaded every payslip and resolved every employee's classification, including the whole pack, only to check one employee | `belgium_service.acknowledge_be_run_exception` | Reads only that employee's payslip in the run: 4 statements, flat |
| 2 | Pack resolved once per employee in the preflight; the acknowledgement set rebuilt once per payslip | `be_run_preflight`, `resolve_be_classification(pack=…)` | Once per run |
| 3 | Ledger posting checked each entry with its own query. Each check also autoflushed the pending inserts | `post_be_accumulators` | One read of the entries already posted, plus one of the employees |
| 4 | DmfA built the worker block, including a vault query, for **every ledger entry**: `setdefault` evaluated its argument every time. It also read the payslips twice | `build_be_dmfa`, `_employer_contributions` | Once per employee; payslips read once (employer totals and demo flag) |
| 5 | Belcotax rescanned the year's entries three times per employee. Each fiche's "latest version" lookup scanned every fiche of the year, because the index has no subject | `build_be_belcotax`, `upsert_filing(latest=…)` | Entries grouped once; the year's fiches read once (`_latest_by_subject`) |
| 6 | The preview resolved the whole pack (every rate and slab) per employee | `calc_inputs` → `_be_cached_active_pack` | Once per session and pay date. Only an Active row is kept, re-checked on use |
| 7 | One query per Belgian record table per employee: classifications, schedules, declarations, profiles, absence episodes, holiday certificates, and the org-level component-mapping index | `_be_records`, `_be_holiday_absence_inputs`, `be_component_mapping_index` | Session read cache: one org-wide read per table. It is cleared on commit, rollback, and any flush that writes a Belgian record; pending Belgian records are flushed first, as a plain query would |

**Why `BePack` is still built per employee:** it only wraps the run's already-resolved rows; it issues no query.
It also records which content rows that employee's calculation used (`usedRows`, the payslip trace). One shared
instance would mix the traces of different employees. Building it costs microseconds.

**Still per employee, by design:** the in-force lookups (the profile and registration in force on the pay date,
with SQL date windows) and the ledger aggregates (YTD, the holiday service year). These are about 10 indexed
SELECTs per employee, linear. Reimplementing the date-window rules in Python to batch them would risk diverging
from the SQL. Writes (payslips, ledger, audit, filings) are inherent.

## Remaining super-linear wall time (not N+1)

Statements per item are flat. From 500 to 2,000 employees (4×), generate grows 4.1× (linear), but:

| Step | Growth | Cause | Recommendation |
|------|--------|-------|----------------|
| acknowledge (one by one) | 8.9× | **Bulk acknowledge (Block J3): 2.36 s for 4,000 at 2,000 employees.** Each one-by-one acknowledgement rewrites the run's JSON list of acknowledgements, so one click is O(N): about 24 ms at 2,000 | A **bulk acknowledge** ("acknowledge every `BE_BSSC_PENDING` in this run"; new route and UI), or an acknowledgement table (schema). Owner decision |
| approve, DmfA | 5.3×, 4.4× | **Snapshot size.** Each Belgian payslip stores about 240 KB of JSON: the frozen context holds the whole pack (slabs about 82 KB, rates about 27 KB), and the used content rows are stored twice (`trace.contentUsed` and `usedRows`, about 60 KB each). At 2,000 employees that is about 480 MB per run, written at generation and decoded, more than once, at approval. **The same cause drives the memory peak above** | Freeze a content-addressed pack reference instead of a pack copy (pack rows are immutable once Active), and keep the used rows once. **Done in Block J2** (owner decision): version-2 snapshots, see the J2 section |

## PostgreSQL / staging should measure

SQLite has no row-level security and runs in-process. On PostgreSQL, measure in CI or staging:
- **RLS overhead:** every `payroll_be_*` table has a FORCED tenant policy, evaluated on each statement. With the
  statement counts above that is a per-statement constant; confirm with `EXPLAIN ANALYZE` on the org-wide cached
  reads (fix 7) and the ledger reads.
- **Network round trips:** the statement counts become latency. About 14 statements per employee at generation is
  about 28,000 at 2,000 employees.
- **TOAST and IO for the 240 KB snapshots**, and the payslip list endpoints that load them.
- **The Belcotax and DmfA builds** against a realistic filings table, where the index without a subject matters
  more.

## Regression guard

`tests/perf/test_belgium_scale.py` is marked `slow` and skipped unless `ZP_BE_SCALE=1`. It runs the harness at 50 and
`ZP_BE_SCALE_N` employees (default 200) in a fresh interpreter on throwaway SQLite, and asserts:
- statements per item stay under a ceiling for every step (preview ≤ 9, generate ≤ 16, preflight ≤ 4,
  acknowledge ≤ 5, approve ≤ 16, view ≤ 3, PDF ≤ 6, DmfA ≤ 4, Belcotax ≤ 6, parallel ≤ 3);
- statements per item do **not** grow with size (large ≤ small × 1.10): the N+1 guard;
- wall time per employee stays under a generous SQLite ceiling, to catch a quadratic regression.

```bash
ZP_BE_SCALE=1 python -m pytest -q tests/perf            # ZP_BE_SCALE_N=500 for a bigger run
```
