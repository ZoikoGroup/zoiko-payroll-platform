"""Belgium (ZP-BE-ENG-001) Block I1: the schema shim for a code-only rollback.

`git revert -m 1 <Belgium merge>` alone cannot be deployed while the database keeps the Belgian schema: the
reverted tree no longer knows alembic revision 8a1f5ef9fa5d (`alembic upgrade head` fails), and
scripts/deploy_migrate.sh then refuses to stamp because payslip_items / payroll_runs carry two columns the
reverted models do not declare (proved by scripts/be_rollback_orm_check.py). This tool, run on the revert
branch right after the revert, puts back ONLY what keeps the schema in place without any database operation:

  * the three Belgian revision files (1d76678ef1a1, 2943a0490b5b, 8a1f5ef9fa5d) and their manifest lines,
    so alembic's head stays 8a1f5ef9fa5d and `upgrade head` is a no-op;
  * the two nullable column declarations (payroll_runs.be_approval_fingerprint, payslip_items.be_calculation_snapshot),
    so the drift check is clean (the 19 payroll_be_* tables need no model: extra tables are not drift);
  * the alembic / drift-set pin tests as re-pinned for Belgium, so CI's head / revision-count pins agree.

Everything else Belgian stays reverted: no Belgian route, service, engine, setting or screen remains.

Usage (repository root, on the revert branch, after `git revert -m 1 <merge>`):
    python backend/scripts/belgium_rollback_shim.py --merge <Belgium merge commit> [--dry-run]
It refuses when a file it would restore was changed on main after the merge (restore that one by hand).
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

MIGRATIONS = ("backend/alembic/versions/1d76678ef1a1_be_foundation.py",
              "backend/alembic/versions/2943a0490b5b_be_absence_holiday_payment.py",
              "backend/alembic/versions/8a1f5ef9fa5d_be_filing_parallel.py")
PIN_TESTS = ("backend/tests/test_alembic_metadata.py", "backend/tests/test_deploy_migrate_script.py",
             "backend/tests/test_japan_migrations.py", "backend/tests/test_nz_filings_migration.py",
             "backend/tests/test_nz_holidays_act_migration.py", "backend/tests/test_nz_leave_pay_migration.py",
             "backend/tests/test_nz_migrations.py", "backend/tests/test_nz_parallel_migration.py",
             "backend/tests/test_poland_migrations.py", "backend/tests/test_south_africa_migrations.py")
MANIFEST = "backend/alembic/MIGRATIONS_MANIFEST.txt"
MODELS = "backend/app/modules/payroll/models.py"
REVISIONS = ("1d76678ef1a1", "2943a0490b5b", "8a1f5ef9fa5d")
COLUMNS = (
    ("    pl_approval_fingerprint = Column(JSON, nullable=True)\n",
     "    # Belgium rollback shim: kept so the retained Belgian schema is not drift (nullable, unused).\n"
     "    be_approval_fingerprint = Column(JSON, nullable=True)\n"),
    ("    pl_calculation_snapshot = Column(JSON, nullable=True)\n",
     "    # Belgium rollback shim: kept so the retained Belgian schema is not drift (nullable, unused).\n"
     "    be_calculation_snapshot = Column(JSON, nullable=True)\n"),
)


def git_show(repo: pathlib.Path, rev: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{rev}:{path}"], cwd=repo, capture_output=True, check=True,
                          text=True, encoding="utf-8").stdout


def apply(repo: pathlib.Path, target: pathlib.Path, merge: str, pre_merge: str | None, dry_run: bool) -> list:
    """Restore the shim into `target` (a checkout of the reverted tree). `pre_merge` = main before the merge;
    when given, a pin test that main changed after the merge is refused."""
    actions = []
    for path in MIGRATIONS + PIN_TESTS:
        content = git_show(repo, merge, path)
        dest = target / path
        if path in PIN_TESTS and pre_merge is not None and dest.exists():
            if dest.read_text(encoding="utf-8") != git_show(repo, pre_merge, path):
                raise SystemExit(f"Refused: {path} changed on main after the merge; restore it by hand.")
        actions.append(f"restore {path} from {merge}")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", newline="")
    manifest = target / MANIFEST
    lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
    wanted = [ln for ln in git_show(repo, merge, MANIFEST).splitlines(keepends=True)
              if any(f"|{rev}|" in ln for rev in REVISIONS)]
    missing = [ln for ln in wanted if ln not in lines]
    actions += [f"insert manifest line {ln.split('|')[1]}" for ln in missing]
    if missing and not dry_run:
        import bisect

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        for ln in missing:                                   # the manifest is sorted by file name: keep it so
            bisect.insort(lines, ln if ln.endswith("\n") else ln + "\n")
        manifest.write_text("".join(lines), encoding="utf-8", newline="")
    models = target / MODELS
    src = models.read_text(encoding="utf-8")
    for anchor, addition in COLUMNS:
        column = addition.splitlines()[-1].strip().split(" ")[0]
        if f"    {column} = Column(" in src:
            continue
        if src.count(anchor) != 1:
            raise SystemExit(f"Refused: anchor for {column} not found exactly once in {MODELS}; add it by hand.")
        src = src.replace(anchor, anchor + addition)
        actions.append(f"declare {column} in {MODELS}")
    if not dry_run:
        models.write_text(src, encoding="utf-8", newline="")
    return actions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merge", required=True, help="the Belgium merge commit that was reverted")
    ap.add_argument("--target", default=".", help="repository root of the revert checkout (default: .)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    repo = pathlib.Path(a.target).resolve()
    pre_merge = subprocess.run(["git", "rev-parse", f"{a.merge}^1"], cwd=repo, capture_output=True, text=True,
                               check=True).stdout.strip()
    for action in apply(repo, repo, a.merge, pre_merge, a.dry_run):
        print(("PLAN " if a.dry_run else "DONE ") + action)
    print("Next: cd backend && alembic heads   # expect 8a1f5ef9fa5d; then commit the shim with the revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
