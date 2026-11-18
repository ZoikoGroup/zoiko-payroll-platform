"""Belgium (ZP-BE-ENG-001) Block I2: scale thresholds for the Belgian code paths (slow; ZP_BE_SCALE=1).

The harness (tests/perf/be_scale_harness.py) runs in a fresh interpreter against its own throwaway SQLite file, so
nothing of the test session's database is touched. Two sizes are measured (small = 50, large = ZP_BE_SCALE_N,
default 200); documented thresholds (docs/belgium/PERFORMANCE.md):

* SQL statements per item stay under a ceiling for every step (measured after the I2 fixes, with headroom);
* statements per item do NOT grow with organisation size (large <= small x 1.10): no N+1 / O(N^2) pattern —
  before I2, acknowledging exceptions went from 457 to 907 statements per item between 50 and 100 employees;
* wall time per employee stays under a generous SQLite ceiling (catches a quadratic regression, not noise).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

BACKEND = Path(__file__).resolve().parents[2]

# statements per item ceilings (after-I2 measurement in parentheses)
MAX_STATEMENTS_PER_ITEM = {
    "preview": 9,                   # (7.1)
    "generate": 16,                 # (14.1)
    "preflight": 4,                 # (3.0)
    "acknowledge exceptions": 5,    # (4.0)
    "approve": 16,                  # (13.6)
    "payslip view x50": 4,          # (3.0: + the deferred Belgian snapshot loaded for the one payslip, J2)
    "payslip PDF x50": 7,           # (6.0: idem)
    "DmfA quarter build": 4,        # (3.0)
    "Belcotax 281.10 build": 6,     # (5.0)
}
# wall seconds per employee ceilings on local SQLite (after-I2 at 500: preview 0.010, generate 0.031, approve 0.028)
MAX_SECONDS_PER_EMPLOYEE = {"preview": 0.05, "generate": 0.12, "preflight": 0.03, "acknowledge exceptions": 0.05,
                            "approve": 0.10, "DmfA quarter build": 0.03, "Belcotax 281.10 build": 0.03}


def _measure(n: int, tmp_path: Path, memory: bool = False) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("ZP_TEST_POSTGRES_URL", "DATABASE_URL")}
    env["ENVIRONMENT"] = "development"
    args = [sys.executable, "-m", "tests.perf.be_scale_harness", "--employees", str(n),
            "--db", str(tmp_path / f"be_scale_{n}{'_mem' if memory else ''}.db")] + (["--memory"] if memory else [])
    done = subprocess.run(args, cwd=BACKEND, env=env, capture_output=True, text=True, timeout=3600)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("BE-SCALE ")), None)
    assert done.returncode == 0 and line, (done.stdout[-2000:], done.stderr[-3000:])
    out = json.loads(line[len("BE-SCALE "):])
    return {r["step"].split(" ")[0] if r["step"].startswith("parallel") else r["step"]: r for r in out["steps"]}


def test_belgian_paths_scale_linearly_without_n_plus_one(tmp_path):
    large_n = int(os.environ.get("ZP_BE_SCALE_N", "200"))
    small, large = _measure(50, tmp_path), _measure(large_n, tmp_path)
    for step, ceiling in MAX_STATEMENTS_PER_ITEM.items():
        assert large[step]["perItem"] <= ceiling, (step, large[step])
        assert large[step]["perItem"] <= small[step]["perItem"] * 1.10 + 0.05, (step, small[step], large[step])
    for step, ceiling in MAX_SECONDS_PER_EMPLOYEE.items():
        assert large[step]["seconds"] / large_n <= ceiling, (step, large[step])
    assert large["parallel"]["perItem"] <= 3, large["parallel"]


# Block J2: Python peak memory per employee (tracemalloc) for the two steps that hold a whole run — after J2
# 0.47 / 0.46 MiB at 500 employees (before: 1.30 / 2.20 MiB).
MAX_MIB_PER_EMPLOYEE = {"generate": 0.6, "approve": 0.6}


def test_belgian_run_memory_stays_under_the_per_employee_ceiling(tmp_path):
    n = int(os.environ.get("ZP_BE_SCALE_N", "200"))
    steps = _measure(n, tmp_path, memory=True)
    for step, ceiling in MAX_MIB_PER_EMPLOYEE.items():
        assert steps[step]["peakMiB"] / n <= ceiling, (step, steps[step])
