"""Belgium (ZP-BE-ENG-001) Block J1: the code-only rollback path is proven end to end, automatically.

Runs scripts/be_rollback_orm_check.py (the Block I1 proof) against throwaway SQLite files:
  * the pre-Belgium code (main before the Belgium merge, default 6081174) behaves identically on a database that
    keeps the Belgian schema;
  * a PLAIN revert is refused by scripts/deploy_migrate.sh (unknown revision + 2 undeclared columns);
  * revert + scripts/belgium_rollback_shim.py: deploy_migrate.sh exits 0, check_schema_drift is clean, the payroll
    operations are identical, and the alembic / drift-set pin tests (>= 135) pass in the shim tree.

Needs the pre-Belgium commit in git history and ~3 minutes, so it runs only with ZP_BE_ROLLBACK_PROOF=1 (CI:
privacy-isolation job, which fetches the commit first). ZP_BE_ROLLBACK_BASE overrides the pre-Belgium commit.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PRE_BELGIUM = os.environ.get("ZP_BE_ROLLBACK_BASE", "6081174560b0613bd11d3eaf3027b8fe359aeb73")

pytestmark = pytest.mark.skipif(os.environ.get("ZP_BE_ROLLBACK_PROOF") != "1",
                                reason="rollback proof: set ZP_BE_ROLLBACK_PROOF=1 (needs the pre-Belgium commit)")


def test_code_only_rollback_with_the_shim_deploys_cleanly(tmp_path):
    reachable = subprocess.run(["git", "cat-file", "-e", f"{PRE_BELGIUM}^{{commit}}"], cwd=BACKEND,
                               capture_output=True)
    assert reachable.returncode == 0, (f"pre-Belgium commit {PRE_BELGIUM} is not in this clone: "
                                       f"git fetch --depth=1 origin {PRE_BELGIUM}")
    env = {k: v for k, v in os.environ.items() if k not in ("ZP_TEST_POSTGRES_URL", "DATABASE_URL")}
    done = subprocess.run([sys.executable, "-m", "scripts.be_rollback_orm_check", "--workdir", str(tmp_path / "rb"),
                           "--old-commit", PRE_BELGIUM], cwd=BACKEND, env=env, capture_output=True, text=True,
                          timeout=1800)
    line = next((ln for ln in reversed(done.stdout.splitlines()) if ln.startswith('{"ormCompatible"')), None)
    assert line, (done.stdout[-3000:], done.stderr[-3000:])
    out = json.loads(line)
    assert out["ormCompatible"] is True, done.stdout[-3000:]
    assert out["plainRevert"]["deployMigrateExit"] != 0                         # a plain revert is refused
    shim = out["revertWithShim"]
    assert shim["deployMigrateExit"] == 0 and shim["driftExit"] == 0, done.stdout[-3000:]
    assert shim["opsIdentical"] is True, done.stdout[-3000:]
    assert shim["pinTestsExit"] == 0 and shim["pinTestsPassed"] >= 135, shim
    assert done.returncode == 0
