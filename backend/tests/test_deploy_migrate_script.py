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


# ── 2026-10-19 (PR #112): the orphan self-heal must survive a deploy that brings new objects ──

def test_the_stamp_point_is_found_before_the_drift_check_and_the_refusal_uses_the_pending_filter():
    code = "\n".join(_code_lines())
    orphan = code.split("orphan version row confirmed", 1)[1]
    head = code.split("orphan version row confirmed", 1)[0]
    assert "STAMP_REV=" in head                                    # computed (read-only) before the check
    refuse = orphan[orphan.index("schema_drift"):orphan.index("alembic stamp")]
    assert "python -m scripts.drift_pending_filter \"$STAMP_REV\"" in refuse
    assert "exit 1" in refuse and "Refusing to stamp" in refuse


def test_the_filter_explains_only_what_the_pending_migrations_create():
    from scripts.drift_pending_filter import unexplained

    report = "\n".join([
        "Schema drift detected:",
        "  - Model table 'payroll_mx_vacation_records' has no matching DB table.",
        "  - Model table 'payroll_other' has no matching DB table.",
        "  - payroll_runs: model has columns not in the DB: ['mx_new']",
        "  - payroll_runs: model has columns not in the DB: ['mx_new', 'mx_other']",
        "  - payslip_items: DB has columns not on the model: ['mystery']",
    ])
    out = unexplained(report, {"payroll_mx_vacation_records"}, {"payroll_runs": {"mx_new"}})
    assert out == ["Model table 'payroll_other' has no matching DB table.",
                   "payroll_runs: model has columns not in the DB: ['mx_new', 'mx_other']",
                   "payslip_items: DB has columns not on the model: ['mystery']"]
    # A change made outside the repository is NEVER explained, whatever is pending.
    assert unexplained("  - payslip_items: DB has columns not on the model: ['x']", {"payslip_items"},
                       {"payslip_items": {"x"}}) == ["payslip_items: DB has columns not on the model: ['x']"]
    assert unexplained("No schema drift detected.", set(), {}) == []


def test_pending_objects_are_read_from_the_real_migration_chain():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(Path(__file__).resolve().parents[1])
    try:
        brazil_tables = {"payroll_br_risk_assignments", "payroll_br_cprb_options", "payroll_br_credential_refs",
                         "payroll_br_concurrent_inss_declarations", "payroll_br_alimony_orders",
                         "payroll_br_vale_transporte_elections"}
        tables, columns = pending_objects("f6c2a9d1e4b7")        # production since PR #125
        assert tables == {"payroll_mx_cfdi_system_concepts"} | brazil_tables
        # Brazil Phases 3-6 (a6ca8aab2043 -> e4ba9fc8c17c) and Phases 1/4.2
        # (135dbbeb9818, 8f90dde5f7b5), on top of production a8e4c1f7d3b5: every
        # table AND every column on an existing table must be explained, or a
        # self-heal refuses.
        tables, columns = pending_objects("a8e4c1f7d3b5")
        assert tables == brazil_tables
        assert columns["payroll_runs"] == {"br_approval_fingerprint", "payment_channel"}
        assert columns["payroll_nl_payment_batches"] == {"pain001_xml", "created_at_utc", "batch_kind",
                                                         "authority_payment_id"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 10
        assert {"version", "previous_version_id", "effective_from", "effective_to",
                "created_by_id"} == columns["payroll_br_employer_profiles"]
        assert {"organization_id", "fpas_status", "fpas_evidence_ref", "active_from", "active_to",
                "created_by_id", "updated_at"} == columns["payroll_br_establishments"]
        tables, columns = pending_objects("8f90dde5f7b5")        # production since PR #129
        assert tables == set() and columns == {"payroll_mx_approved_hours": {"overtime_dates"}}   # Mexico m18
        # Both branches out of f5c1a8d3e9b2 (Mexico M8 and ZP-PRIV) are pending from it.
        tables, columns = pending_objects("f5c1a8d3e9b2")
        assert {"payroll_mx_vacation_records", "pay_groups", "payroll_mx_terminations"} <= tables
        assert "data_region" in columns.get("organizations", set())
        tables, _ = pending_objects("e3b9c2d7f4a1")
        assert {"payroll_mx_run_corrections", "payroll_mx_vacation_records"} <= tables
    finally:
        os.chdir(here)


def test_batch_added_columns_count_and_downgrade_does_not():
    """A column added inside `with op.batch_alter_table(...) as batch:` is
    explained; one a downgrade() re-adds is not."""
    from scripts.drift_pending_filter import _added_columns, _upgrade_body

    src = (
        "def upgrade():\n"
        "    with op.batch_alter_table('organizations') as batch:\n"
        "        batch.add_column(sa.Column('data_region', sa.String(8)))\n"
        "    with op.batch_alter_table('users') as b2:\n"
        "        b2.add_column(sa.Column('is_temporary', sa.Boolean()))\n"
        "    op.add_column('runs', sa.Column('flag', sa.Boolean()))\n"
        "\n"
        "\n"
        "def downgrade():\n"
        "    op.add_column('legacy', sa.Column('old_col', sa.Integer()))\n"
    )
    assert sorted(_added_columns(_upgrade_body(src))) == [
        ("organizations", "data_region"), ("runs", "flag"), ("users", "is_temporary")]
