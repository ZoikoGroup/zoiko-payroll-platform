"""Belgium (ZP-BE-ENG-001) Block H2a: rehearse the production deploy migration on a throwaway SQLite file.

Usage (from backend/; the argument is a NEW SQLite file path - it is deleted first; no other database is touched):
    python -m scripts.be_deploy_rehearsal /tmp/be_rehearsal.db


Production today = main's head f3a9c1d7e2b4 with every model object except the Belgian ones. We build that
state (create_all, then remove the 19 payroll_be_* tables and the 2 shared columns, stamp f3a9c1d7e2b4), then
run exactly what scripts/deploy_migrate.sh runs, as subprocesses against that file only.
"""
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

DB = pathlib.Path(sys.argv[1]).resolve()
if DB.suffix not in (".db", ".sqlite", ".sqlite3"):
    raise SystemExit("Refused: pass a throwaway SQLite file path ending in .db / .sqlite / .sqlite3.")
URL = f"sqlite:///{DB.as_posix()}"
ENV = {**os.environ, "PAYROLL_DATABASE_URL": URL}
ENV.pop("ZP_TEST_POSTGRES_URL", None)
PY = sys.executable
PARENT, HEAD = "f3a9c1d7e2b4", "8a1f5ef9fa5d"
SHARED = {"payslip_items": "be_calculation_snapshot", "payroll_runs": "be_approval_fingerprint"}


def run(*args, check=True, stdin=None):
    out = subprocess.run(list(args), cwd=".", env=ENV, capture_output=True, text=True, input=stdin)
    if check and out.returncode != 0:
        print(out.stdout[-3000:], out.stderr[-3000:])
        raise SystemExit(f"FAILED: {' '.join(args)}")
    return out


def alembic(*args, check=True):
    return run(PY, "-m", "alembic", *args, check=check)


def be_objects():
    con = sqlite3.connect(DB)
    tables = sorted(r[0] for r in con.execute("select name from sqlite_master where type='table' and name like 'payroll_be_%'"))
    cols = {t: c for t, c in SHARED.items() if c in {r[1] for r in con.execute(f"pragma table_info({t})")}}
    version = [r[0] for r in con.execute("select version_num from alembic_version")]
    rows = sum(con.execute(f"select count(*) from {t}").fetchone()[0] for t in tables)
    con.close()
    return tables, cols, version, rows


def drift():
    out = run(PY, "-m", "scripts.check_schema_drift", check=False)
    return out.returncode, (out.stdout + out.stderr)


def unexplained(report, stamp):
    return run(PY, "-m", "scripts.drift_pending_filter", stamp, stdin=report).stdout.strip()


if DB.exists():
    DB.unlink()
print("DB:", URL)
# 1. production-like state at f3a9c1d7e2b4
run(PY, "-c", "from app.database import Base, engine; import app.main; Base.metadata.create_all(engine)")
con = sqlite3.connect(DB)
for (t,) in con.execute("select name from sqlite_master where type='table' and name like 'payroll_be_%'").fetchall():
    con.execute(f'drop table "{t}"')
for t, c in SHARED.items():
    con.execute(f'alter table {t} drop column {c}')
con.commit()
con.close()
alembic("stamp", PARENT)
t, c, v, _ = be_objects()
print(f"1. start: version={v} be_tables={len(t)} shared_cols={c}")
assert v == [PARENT] and not t and not c

# 2. the read-only drift check before upgrade: everything missing is explained by the pending migrations
code, report = drift()
missing = [line for line in report.splitlines() if "payroll_be_" in line or "be_calculation_snapshot" in line
           or "be_approval_fingerprint" in line]
left = unexplained(report, PARENT)
print(f"2. drift before upgrade: exit={code}, BE drift lines={len(missing)}, unexplained={left!r}")
assert left == ""

# 3. normal path: alembic upgrade head, then drift check + head verification
alembic("upgrade", "head")
t, c, v, rows = be_objects()
code, report = drift()
print(f"3. upgrade head: version={v} be_tables={len(t)} shared_cols={sorted(c)} drift_exit={code}")
assert v == [HEAD] and len(t) == 19 and len(c) == 2 and code == 0, report[-2000:]

# 4. idempotent: a second deploy run (upgrade head) is a no-op
alembic("upgrade", "head")
t2, c2, v2, _ = be_objects()
code, _r = drift()
print(f"4. second upgrade head: version={v2} unchanged={t2 == t and c2 == c} drift_exit={code}")
assert v2 == [HEAD] and t2 == t and c2 == c and code == 0

# 4b. orphan path idempotency: the script's stamp-point walk on the upgraded DB finds HEAD
script = pathlib.Path("../scripts/deploy_migrate.sh").read_text(encoding="utf-8")
walk = re.search(r'STAMP_REV="\$\(python - <<\'PY\'\n(.*?)\nPY\n\)"', script, re.S).group(1)
stamp = run(PY, "-", stdin=walk).stdout.strip()
print(f"4b. orphan-path stamp point on the upgraded DB: {stamp}")
assert stamp == HEAD

# 5. downgrade of the three Belgian revisions on empty tables
assert rows == 0
for target, expect_tables in (("2943a0490b5b", 14), ("1d76678ef1a1", 9), (PARENT, 0)):
    alembic("downgrade", target)
    t, c, v, _ = be_objects()
    print(f"5. downgrade {target}: version={v} be_tables={len(t)} shared_cols={sorted(c)}")
    assert v == [target] and len(t) == expect_tables
assert not c
code, report = drift()
print(f"5b. after full downgrade: drift explained by pending = {unexplained(report, PARENT) == ''}")
stamp = run(PY, "-", stdin=walk).stdout.strip()
print(f"5c. orphan-path stamp point on the pre-Belgium schema: {stamp} (must be {PARENT}, never the head)")
assert stamp == PARENT
alembic("upgrade", "head")
t, c, v, _ = be_objects()
code, _r = drift()
print(f"6. re-upgrade: version={v} be_tables={len(t)} shared_cols={len(c)} drift_exit={code}")
assert v == [HEAD] and len(t) == 19 and code == 0
print("REHEARSAL OK")
