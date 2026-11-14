# Belgium — merge plan against main (Block F5)

Status 2026-11-13 after `git fetch origin` (read-only). **Nothing merged or rebased.** Decision needed: the
merge step below.

## Where the branches stand

| | Commit | Note |
|---|---|---|
| Pre-Belgium base | `1af3d44` | on main (merge-base of nikhil and origin/main) |
| origin/main | `6081174` (PR #158) | **6 commits** past the base: payslip templates (PDF / Word / PDF import, organisation layouts), restored payroll-run screens, re-parent onto Mexico m21 |
| nikhil (local, unpushed) | `fa800d0` + this doc | **42 commits** past the base (Belgium Phases 0-3, Blocks A-F) |

Main adds **one migration**: `f3a9c1d7e2b4_payslip_templates` (child of `efc56f3235e2`). Our first Belgian migration
`1d76678ef1a1` is also a child of `efc56f3235e2` → a plain merge would leave **two Alembic heads**
(`f3a9c1d7e2b4` and `8a1f5ef9fa5d`). **Re-chain needed: yes.**

## Simulated merge (`git merge-tree`, read-only)

Conflicts (all "both sides added lines at the same place"):

| File | Resolution |
|------|------------|
| backend/app/modules/payroll/models.py | keep both: `template_version_id` (main) and `be_calculation_snapshot` (ours) on payslip_items |
| frontend/src/modules/payroll/PaySlips/PayslipStub.jsx | keep both imports: `getPayslipById, getPayslipRenderedHtml` (main) + the BE payslip-line helpers (ours); then check the Belgian section still renders inside main's template-aware stub |
| backend/tests/test_alembic_metadata.py | head `8a1f5ef9fa5d` (after re-chain), revision count **263**, comments for both |
| backend/tests/test_deploy_migrate_script.py | union of both pending sets (template tables + BE tables; `template_version_id` + `be_calculation_snapshot`); the e7ec6c1933b4 / efc56f3235e2 block becomes: pending from e7ec6c1933b4 = templates + all BE tables, columns m21 + `template_version_id` + `be_calculation_snapshot` + `be_approval_fingerprint` + BE Block B columns; pending from efc56f3235e2 = templates + BE (same columns minus m21) |
| tests/test_japan_migrations.py, test_nz_*_migration.py (5), test_poland_migrations.py, test_south_africa_migrations.py | union of both sides' set additions (re-pin rule: exact lists only) |
| Auto-merged cleanly | MIGRATIONS_MANIFEST.txt, route_registry.json, router.py, service.py |

## Re-chain (inside the merge commit)

1. `backend/alembic/versions/1d76678ef1a1_be_foundation.py`: `down_revision` `efc56f3235e2` → **`f3a9c1d7e2b4`**
   (and the "Revises:" line). Allowed: every Belgian migration is unpushed and was never applied anywhere shared.
2. MIGRATIONS_MANIFEST.txt: the `1d76678ef1a1` line gets the new down revision and the new SHA-256.
3. tests/test_belgium_migrations.py: `PARENT = "f3a9c1d7e2b4"`.
4. Resulting chain: `efc56f3235e2 → f3a9c1d7e2b4 → 1d76678ef1a1 → 2943a0490b5b → 8a1f5ef9fa5d` — single head.

**Trial (scratch copy of the merge tree + the resolutions for models.py / test_alembic_metadata.py + the re-chain;
the branch untouched):** Alembic heads = `['8a1f5ef9fa5d']`; test_belgium_migrations + block B + block C +
test_alembic_metadata (incl. manifest): **72 passed, 3 skipped** (PostgreSQL round trips, CI only).
Main's test_payslip_templates: 15 failed / 68 passed locally — only because main's new requirements
(`mammoth`, `pdfplumber`, `xhtml2pdf`) are not installed on this machine; install them before the real run.
The drift-pin tests were not run in the trial (they need the hand resolution above).

## Recommended method: merge commit (not rebase)

- **Merge origin/main into nikhil** with one merge commit that also carries the re-chain and the pin
  resolutions. Rebasing 42 commits would replay the same pin-test conflicts in many commits (each Belgian block
  re-pinned them) and rewrite every Belgian commit hash referenced in PROGRESS.md / PR_DESCRIPTION.md.
- Expected conflicts: the 13 files above; nothing in Belgian-only files.

## Exact steps (after your go-ahead)

1. `git fetch origin` and confirm origin/main is still `6081174` (re-plan if it moved).
2. `pip install -r backend/requirements.txt` (main's new packages).
3. On nikhil: `git merge --no-ff origin/main`; resolve the 13 files as above; apply the re-chain (steps 1-3);
   recompute the manifest SHA.
4. Check: `alembic heads` = `8a1f5ef9fa5d` only.
5. Regenerate the route registry; diff it (main added 14 inventory rows: they must appear as-is; no existing
   route's class / roles / data changed by the merge).
6. Tests (safe SQLite env): all test_belgium_*; the migration pin suites (alembic metadata, deploy drift, JP / NZ /
   PL / SA migrations); test_payslip_templates; tests/privacy; then the **full chunked suite with reconciliation**
   (re-chained migrations).
7. Frontend: `npm test`, lint on changed files, `npm run build`; browser check of a Belgian payslip in main's
   template-aware PayslipStub.
8. Commit the merge locally. **No push** until you decide; CI gates (PostgreSQL job incl. the Belgium round trips,
   Python 3.12, frontend build) run on the PR.
