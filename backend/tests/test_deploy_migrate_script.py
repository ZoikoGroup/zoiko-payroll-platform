"""scripts/deploy_migrate.sh must never change the schema outside Alembic.

Regression for the defect found in origin/main's script (2026-09-29): its
orphan-revision path "checked" drift by calling migrations.sync_schema, which
issues ALTER TABLE ... ADD COLUMN, BEFORE deciding to refuse — a refused
deploy still mutated the schema (PostgreSQL rehearsal: 11 sgp_* columns added
by a run that exited 1), and the next run then saw no drift and re-stamped
over migrations that never ran. After a successful upgrade it also ran
sync_schema as a "safety-net", which can only hide a missing migration.

Static checks of the script text (the PostgreSQL behaviour is rehearsed in
docs/SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md §17). No database is touched.
"""

import re
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy_migrate.sh"


def _code_lines():
    """Script lines without comments (comments may mention sync_schema)."""
    return [ln for ln in _SCRIPT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]


def test_the_deploy_script_never_runs_the_mutating_sync_schema():
    code = "\n".join(_code_lines())
    assert "sync_schema" not in code


def test_drift_is_checked_read_only_before_any_stamp_in_the_orphan_path():
    code = "\n".join(_code_lines())
    body = re.search(r"schema_drift\(\) \{(.*?)\n\}", code, re.S).group(1)
    assert body.strip() == "python -m scripts.check_schema_drift"
    orphan = code.split("orphan version row confirmed", 1)[1]
    assert orphan.index("schema_drift") < orphan.index("alembic stamp")
    refuse = orphan[orphan.index("schema_drift"):orphan.index("alembic stamp")]
    assert "exit 1" in refuse and "Refusing to stamp" in refuse


def test_every_success_path_ends_with_the_read_only_drift_check_and_head_verification():
    code = "\n".join(_code_lines())
    for tail in (code.split('if upgrade_output="$(alembic upgrade head 2>&1)"; then', 1)[1].split("fi", 1)[0],
                 code.rsplit("alembic upgrade head", 1)[1]):
        assert tail.index("check_model_drift") < tail.index("verify_at_head")
