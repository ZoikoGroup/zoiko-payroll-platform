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


# Mexico final mile X4: the parallel-payroll tables join m20 (d3f8b2a6c1e9).
MX_X4_TABLES = ("payroll_mx_parallel_imports", "payroll_mx_parallel_differences")


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
        # South Africa foundation (447f57564983, ZP-ZA-ENG-001 Phase 2): four
        # payroll_za_* tables, 13 za_* profile columns, the payslip snapshot and
        # the run fingerprint — all pending on top of every production revision.
        za_tables = {"payroll_za_employer_registrations", "payroll_za_tax_directives", "payroll_za_eti_ledger",
                     "payroll_za_sars_artifacts",
                     # Phase 8 (c15d5b87d6f5): SARS payments + approved reconciliation variances.
                     "payroll_za_sars_payments", "payroll_za_reconciliation_variances",
                     # Phase 9 (3880223bfaa0, on merge 92c67cab49fc): approved result overrides.
                     "payroll_za_payroll_overrides",
                     # Phase 10 (67c8d7454716): G6 parallel payroll cycles.
                     "payroll_za_parallel_imports", "payroll_za_parallel_differences"}
        # Japan foundation (f686d5128f8a, ZP-JP-ENG-001 Phase 2): eight
        # payroll_jp_* tables, the payslip snapshot and the run fingerprint.
        jp_tables = {"payroll_jp_employer_registrations", "payroll_jp_my_number_vault",
                     "payroll_jp_my_number_access_events", "payroll_jp_worker_tax_profiles",
                     "payroll_jp_social_insurance_enrollments", "payroll_jp_social_insurance_events",
                     "payroll_jp_employment_insurance_profiles", "payroll_jp_resident_tax_assessments"}
        jp_columns = {"payslip_items": {"jp_calculation_snapshot"},
                      "payroll_runs": {"jp_approval_fingerprint"}}
        # 668472e4eb72 (2026-10-30): organizations.timezone, on top of Japan Phase 2.
        tz_columns = {"organizations": {"timezone"}}
        mx_final_mile = {"payroll_mx_decisions", *MX_X4_TABLES}     # Mexico m20 (d3f8b2a6c1e9)
        # Country entitlement ledger (b4d6f8a0c2e3, joined at d4c8f1a7b2e9 / c2e7a4f9b1d8):
        # pending on top of every production revision below.
        country = {"organization_jurisdictions"}
        tables, columns = pending_objects("f6c2a9d1e4b7")        # production since PR #125
        assert tables == {"payroll_mx_cfdi_system_concepts"} | brazil_tables | za_tables | mx_final_mile | country | jp_tables
        # Brazil Phases 3-6 (a6ca8aab2043 -> e4ba9fc8c17c) and Phases 1/4.2
        # (135dbbeb9818, 8f90dde5f7b5), on top of production a8e4c1f7d3b5: every
        # table AND every column on an existing table must be explained, or a
        # self-heal refuses.
        tables, columns = pending_objects("a8e4c1f7d3b5")
        assert tables == brazil_tables | za_tables | mx_final_mile | country | jp_tables
        assert columns["payroll_runs"] == {"br_approval_fingerprint", "payment_channel", "za_approval_fingerprint",
                                           "jp_approval_fingerprint"}
        assert columns["payroll_nl_payment_batches"] == {"pain001_xml", "created_at_utc", "batch_kind",
                                                         "authority_payment_id"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 10 + 13
        assert "za_calculation_snapshot" in columns["payslip_items"]
        assert {"version", "previous_version_id", "effective_from", "effective_to",
                "created_by_id"} == columns["payroll_br_employer_profiles"]
        assert {"organization_id", "fpas_status", "fpas_evidence_ref", "active_from", "active_to",
                "created_by_id", "updated_at"} == columns["payroll_br_establishments"]
        tables, columns = pending_objects("8f90dde5f7b5")        # production since PR #129
        assert tables == za_tables | mx_final_mile | country | jp_tables
        assert columns["payroll_mx_approved_hours"] == {"overtime_dates"}                   # Mexico m18
        assert columns["payroll_runs"] == {"za_approval_fingerprint", "jp_approval_fingerprint"}
        assert columns["payslip_items"] == {"za_calculation_snapshot", "jp_calculation_snapshot"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 13
        # Production since PR #136 (A18): Mexico m20 (d3f8b2a6c1e9) and South Africa
        # (447f57564983 -> c15d5b87d6f5) both grow from it, joined by merge 92c67cab49fc.
        tables, columns = pending_objects("c7d2e9a4f1b6")
        assert tables == za_tables | mx_final_mile | country | jp_tables and "payroll_mx_approved_hours" not in columns
        assert columns["payroll_runs"] == {"za_approval_fingerprint", "jp_approval_fingerprint"}
        assert columns["payslip_items"] == {"za_calculation_snapshot", "jp_calculation_snapshot"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 13
        tables, columns = pending_objects("b9f3d5a1c7e2")
        assert tables == za_tables | mx_final_mile | country | jp_tables and "payroll_mx_approved_hours" not in columns
        # Across merge 92c67cab49fc each side also runs the OTHER side (scripts.drift_pending_filter
        # counts every head ancestor the stamp lacks, not only the stamp -> head path).
        tables, columns = pending_objects("c15d5b87d6f5")      # a database at South Africa P8
        assert tables == mx_final_mile | country | jp_tables | {"payroll_za_payroll_overrides",
                                                      "payroll_za_parallel_imports",
                                                      "payroll_za_parallel_differences"}
        assert columns == {"payroll_court_ordered_deductions": {"za_authority_type", "za_evidence_ref"},
                           "payroll_za_employer_registrations": {"za_journal_accounts"}, **jp_columns,
                           **tz_columns}
        tables, columns = pending_objects("d3f8b2a6c1e9")      # a database at Mexico m20
        assert tables == za_tables | country | jp_tables
        # Production since PR #140 (South Africa P9): Phase 10, the country
        # entitlement ledger and Japan Phase 2 are pending.
        tables, columns = pending_objects("3880223bfaa0")
        assert tables == {"payroll_za_parallel_imports", "payroll_za_parallel_differences"} | country | jp_tables
        assert columns == {**jp_columns, **tz_columns}
        # A database already at Japan Phase 2 has only the registration timezone pending.
        tables, columns = pending_objects("f686d5128f8a")
        assert tables == set() and columns == tz_columns
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
