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
from tests._mx_lifecycle_pending import MX_LIFECYCLE_COLUMNS, MX_LIFECYCLE_TABLES  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy_migrate.sh"


def _code_lines():
    """Script lines without comments (comments may mention sync_schema)."""
    return [ln for ln in _SCRIPT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]


# Mexico final mile X4: the parallel-payroll tables join m20 (d3f8b2a6c1e9).
MX_X4_TABLES = ("payroll_mx_parallel_imports", "payroll_mx_parallel_differences")



# Belgium Block B (2943a0490b5b) adds these columns to Belgium tables (standing re-pin rule).
BE_BLOCK_B_COLUMNS = {"payroll_be_worker_profiles": {"pay_basis"}, "payroll_be_employment_classifications": {"contract_type", "contract_start_date", "contract_end_date"}, "payroll_be_employer_registrations": {"onss_special_160_status", "special_160_evidence_ref"}}

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

    from scripts.drift_pending_filter import pending_objects as _pending_objects

    def pending_objects(stamp):
        tables, columns = _pending_objects(stamp)
        assert MX_LIFECYCLE_TABLES <= tables
        assert {table: columns.get(table) for table in MX_LIFECYCLE_COLUMNS} == MX_LIFECYCLE_COLUMNS
        return tables - MX_LIFECYCLE_TABLES, {table: value for table, value in columns.items()
                                               if table not in MX_LIFECYCLE_COLUMNS}

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
        # Japan P5/P6 (9c1d7e4a2b6f, a7c4e9d1b2f8, a1a748b50902): the run payment
        # kind, the work-conditions table with its calendar columns and the
        # attendance approvals - every one must be visible to the drift filter.
        jp_p6_tables = {"payroll_jp_work_conditions", "payroll_jp_attendance_approvals",
                        # Japan P8 (41a1fafbbfdc)
                        "payroll_jp_run_exceptions", "payroll_jp_obligations",
                        "payroll_jp_yea_declarations", "payroll_jp_yea_cases",
                        # Japan P9 (b8bd939fffca)
                        "payroll_jp_parallel_imports", "payroll_jp_parallel_differences"}
        jp_p6_columns = {"payroll_runs": {"jp_payment_kind"},
                         "payroll_jp_work_conditions": {"scheduled_weekdays", "statutory_day_off_weekday",
                                                        "public_holidays_off"}}
        jp_tables |= jp_p6_tables
        # New Zealand P2 (0e697c2388bf, ZP-NZ-ENG-001): eight payroll_nz_* tables, the
        # payslip snapshot, the run fingerprint and the run payment kind - pending on
        # top of Japan P9, so pending from every revision below.
        nz_tables = {"payroll_nz_employer_profiles", "payroll_nz_ird_vault", "payroll_nz_ird_access_events",
                     "payroll_nz_employee_tax_profiles", "payroll_nz_kiwisaver_elections",
                     "payroll_nz_authority_deductions", "payroll_nz_work_pattern_versions",
                     "payroll_nz_accumulator_entries",
                     # New Zealand P8 (dd8a60634320): filings, remittances, settlements, run exceptions.
                     "payroll_nz_filings", "payroll_nz_remittances", "payroll_nz_remittance_lines",
                     "payroll_nz_settlements", "payroll_nz_run_exceptions",
                     # New Zealand P9 (a8cde2482ef0): parallel cycles.
                     "payroll_nz_parallel_imports", "payroll_nz_parallel_differences",
                     # New Zealand P6 (c6ea8c6c35ce): leave pay, cash-ups, final pay, corrections.
                     "payroll_nz_final_pay_cases", "payroll_nz_leave_pay_calculations",
                     "payroll_nz_cash_up_requests", "payroll_nz_corrections",
                     # New Zealand P5 (ac08988ecd3a): Holidays Act tables.
                     "payroll_nz_employments", "payroll_nz_public_holiday_decisions", "payroll_nz_leave_entitlements",
                     "payroll_nz_gross_earnings_ledger", "payroll_nz_leave_events",
                     # Poland P2 (1ee3bbde33bb, ZP-PL-ENG-001): pending on top of New Zealand P9.
                     "payroll_pl_identifier_vault", "payroll_pl_identifier_access_events",
                     "payroll_pl_employer_registrations", "payroll_pl_worker_profiles", "payroll_pl_declarations",
                     "payroll_pl_ppk_participations", "payroll_pl_accumulator_entries",
                                        "payroll_pl_incapacity_episodes",  # + Poland P6 (e11c2c36df17)
                                        "payroll_pl_filings", "payroll_pl_settlements",
                                        "payroll_pl_reconciliation_variances",  # + Poland P8 (e75b9219e1f8)
                                        "payroll_pl_parallel_imports",
                                        "payroll_pl_parallel_differences",  # + Poland P9 (e7ec6c1933b4)
                                        "payroll_be_identifier_vault", "payroll_be_identifier_access_events",
                                        "payroll_be_employer_registrations", "payroll_be_establishment_units",
                                        "payroll_be_worker_profiles", "payroll_be_work_schedules",
                                        "payroll_be_employment_classifications", "payroll_be_declarations",
                                        "payroll_be_accumulator_entries",  # + Belgium P2 (1d76678ef1a1)
                                        "payroll_be_absence_episodes", "payroll_be_holiday_certificates", "payroll_be_payment_batches", "payroll_be_payment_items", "payroll_be_component_mappings", "payroll_be_filings", "payroll_be_obligations", "payroll_be_reconciliation_variances", "payroll_be_parallel_imports", "payroll_be_parallel_differences", "payroll_payslip_templates", "payroll_payslip_template_versions", "payroll_payslip_template_assignments"}  # + Belgium Block B (2943a0490b5b) + Block C (8a1f5ef9fa5d)
        nz_run_columns = {"nz_approval_fingerprint", "nz_payment_kind", "nz_run_options",   # + P6 options
                          "pl_approval_fingerprint",                                        # + Poland P2
                          "be_approval_fingerprint"}                                        # + Belgium P2
        jp_tables |= nz_tables
        jp_p6_tables |= nz_tables
        jp_columns = {"payslip_items": {"jp_calculation_snapshot", "nz_calculation_snapshot", "nz_correction_of_id",
                                        "pl_calculation_snapshot", "be_calculation_snapshot", "template_version_id"},
                      "payroll_runs": {"jp_approval_fingerprint", "jp_payment_kind", *nz_run_columns},
                      "payroll_jp_work_conditions": jp_p6_columns["payroll_jp_work_conditions"],
                      # New Zealand P6 (c6ea8c6c35ce) adds a column to its P5 table.
                      "payroll_nz_leave_events": {"leave_pay_calculation_id"},
                      # New Zealand P8 (dd8a60634320) adds the journal account map to its P2 table.
                      "payroll_nz_employer_profiles": {"nz_journal_accounts"}}
        # 668472e4eb72 (2026-10-30): organizations.timezone, on top of Japan Phase 2.
        tz_columns = {"organizations": {"timezone"}}
        mx_final_mile = {"payroll_mx_decisions", *MX_X4_TABLES}     # Mexico m20 (d3f8b2a6c1e9)
        # Country entitlement ledger (b4d6f8a0c2e3, joined at d4c8f1a7b2e9 / c2e7a4f9b1d8):
        # pending on top of every production revision below.
        country = {"organization_jurisdictions"}
        google_tables = {"google_pending"}
        google_columns = {"users": {"auth_provider", "google_id", "avatar_url"}}

        def assert_google_pending(tables, columns):
            assert google_tables <= tables
            assert google_columns["users"] <= columns.get("users", set())

        tables, columns = pending_objects("f6c2a9d1e4b7")        # production since PR #125
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == ({"payroll_mx_cfdi_system_concepts"} | brazil_tables | za_tables
                          | mx_final_mile | country | jp_tables | google_tables)
        # Brazil Phases 3-6 (a6ca8aab2043 -> e4ba9fc8c17c) and Phases 1/4.2
        # (135dbbeb9818, 8f90dde5f7b5), on top of production a8e4c1f7d3b5: every
        # table AND every column on an existing table must be explained, or a
        # self-heal refuses.
        tables, columns = pending_objects("a8e4c1f7d3b5")
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == brazil_tables | za_tables | mx_final_mile | country | jp_tables | google_tables
        assert columns["payroll_runs"] == {"br_approval_fingerprint", "payment_channel", "za_approval_fingerprint",
                                           "jp_approval_fingerprint", "jp_payment_kind", *nz_run_columns}
        assert columns["payroll_jp_work_conditions"] == {"scheduled_weekdays", "statutory_day_off_weekday",
                                                         "public_holidays_off"}
        assert columns["payroll_nl_payment_batches"] == {"pain001_xml", "created_at_utc", "batch_kind",
                                                         "authority_payment_id"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 10 + 13 + 3   # + Mexico m21 (union member, SDI + evidence)
        assert "za_calculation_snapshot" in columns["payslip_items"]
        assert {"version", "previous_version_id", "effective_from", "effective_to",
                "created_by_id"} == columns["payroll_br_employer_profiles"]
        assert {"organization_id", "fpas_status", "fpas_evidence_ref", "active_from", "active_to",
                "created_by_id", "updated_at"} == columns["payroll_br_establishments"]
        tables, columns = pending_objects("8f90dde5f7b5")        # production since PR #129
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == za_tables | mx_final_mile | country | jp_tables | google_tables
        assert columns["payroll_mx_approved_hours"] == {"overtime_dates"}                   # Mexico m18
        assert columns["payroll_runs"] == {"za_approval_fingerprint", "jp_approval_fingerprint", "jp_payment_kind", *nz_run_columns}
        assert columns["payslip_items"] == {"za_calculation_snapshot", "jp_calculation_snapshot", "nz_calculation_snapshot", "nz_correction_of_id",
                                            "pl_calculation_snapshot", "be_calculation_snapshot", "template_version_id"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 13 + 3   # + Mexico m21 (union member, SDI + evidence)
        # Production since PR #136 (A18): Mexico m20 (d3f8b2a6c1e9) and South Africa
        # (447f57564983 -> c15d5b87d6f5) both grow from it, joined by merge 92c67cab49fc.
        tables, columns = pending_objects("c7d2e9a4f1b6")
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == (za_tables | mx_final_mile | country | jp_tables | nz_tables | google_tables)
        assert "payroll_mx_approved_hours" not in columns
        assert columns["payroll_runs"] == {"za_approval_fingerprint", "jp_approval_fingerprint", "jp_payment_kind", *nz_run_columns}
        assert columns["payslip_items"] == {"za_calculation_snapshot", "jp_calculation_snapshot", "nz_calculation_snapshot", "nz_correction_of_id",
                                            "pl_calculation_snapshot", "be_calculation_snapshot", "template_version_id"}
        assert len(columns["payroll_employee_statutory_profiles"]) == 13 + 3   # + Mexico m21 (union member, SDI + evidence)
        tables, columns = pending_objects("b9f3d5a1c7e2")
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == (za_tables | mx_final_mile | country | jp_tables | google_tables)
        assert "payroll_mx_approved_hours" not in columns
        # Mexico m21 (efc56f3235e2, sweep S1) is the head: pending from every earlier stamp.
        mx_m21 = {"payroll_mx_terminations": {"indemnity_daily_salary", "indemnity_salary_evidence_ref"},
                  "payroll_mx_labor_policies": {"hourly_rate_daily_hours", "special_pay_withholding_method"},
                  "payroll_employee_statutory_profiles": {"mx_union_member", "mx_sdi_operator_entered",
                                                          "mx_sdi_evidence_ref"}}
        # Across merge 92c67cab49fc each side also runs the OTHER side (scripts.drift_pending_filter
        # counts every head ancestor the stamp lacks, not only the stamp -> head path).
        tables, columns = pending_objects("c15d5b87d6f5")      # a database at South Africa P8
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == mx_final_mile | country | jp_tables | google_tables | {"payroll_za_payroll_overrides",
                                                      "payroll_za_parallel_imports",
                                                      "payroll_za_parallel_differences"}
        assert {t: columns.pop(t, None) for t in BE_BLOCK_B_COLUMNS} == BE_BLOCK_B_COLUMNS  # + Belgium Block B (2943a0490b5b)
        assert columns == {"payroll_court_ordered_deductions": {"za_authority_type", "za_evidence_ref"},
                           "payroll_za_employer_registrations": {"za_journal_accounts"}, **jp_columns,
                           **tz_columns, **google_columns, **mx_m21}
        tables, columns = pending_objects("d3f8b2a6c1e9")      # a database at Mexico m20
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == za_tables | country | jp_tables | google_tables
        # Production since PR #140 (South Africa P9): Phase 10, the country
        # entitlement ledger and Japan Phase 2 are pending.
        tables, columns = pending_objects("3880223bfaa0")
        assert_google_pending(tables, columns)
        assert tables - MX_LIFECYCLE_TABLES == ({"payroll_za_parallel_imports", "payroll_za_parallel_differences"}
                          | country | jp_tables | google_tables)
        assert {t: columns.pop(t, None) for t in BE_BLOCK_B_COLUMNS} == BE_BLOCK_B_COLUMNS  # + Belgium Block B (2943a0490b5b)
        assert columns == {**jp_columns, **tz_columns, **google_columns, **mx_m21}
        # A database already at Japan Phase 2 has the registration timezone and
        # Japan P5/P6 pending.
        tables, columns = pending_objects("f686d5128f8a")
        assert_google_pending(tables, columns)
        assert tables == jp_p6_tables | google_tables
        assert {t: columns.pop(t, None) for t in BE_BLOCK_B_COLUMNS} == BE_BLOCK_B_COLUMNS  # + Belgium Block B (2943a0490b5b)
        assert columns == {**tz_columns, **jp_p6_columns, **google_columns, **mx_m21,
                           "payroll_runs": {"jp_payment_kind", *nz_run_columns},
                           "payslip_items": {"nz_calculation_snapshot", "nz_correction_of_id", "pl_calculation_snapshot",
                                             "be_calculation_snapshot", "template_version_id"},
                           "payroll_nz_leave_events": {"leave_pay_calculation_id"},
                           "payroll_nz_employer_profiles": {"nz_journal_accounts"}}
        # A database at Poland P9 (e7ec6c1933b4, main's head before m21): Mexico m21, the payslip
        # templates (f3a9c1d7e2b4, m21's child) and Belgium (1d76678ef1a1 -> 2943a0490b5b -> 8a1f5ef9fa5d,
        # re-chained onto f3a9c1d7e2b4 when origin/main was merged into nikhil) are pending.
        payslip_template_tables = {"payroll_payslip_templates", "payroll_payslip_template_versions",
                                   "payroll_payslip_template_assignments"}
        be_p2_tables = {"payroll_be_identifier_vault", "payroll_be_identifier_access_events",
                        "payroll_be_employer_registrations", "payroll_be_establishment_units",
                        "payroll_be_worker_profiles", "payroll_be_work_schedules",
                        "payroll_be_employment_classifications", "payroll_be_declarations",
                        "payroll_be_accumulator_entries"}
        be_block_b_tables = {"payroll_be_absence_episodes", "payroll_be_holiday_certificates", "payroll_be_payment_batches", "payroll_be_payment_items", "payroll_be_component_mappings", "payroll_be_filings", "payroll_be_obligations", "payroll_be_reconciliation_variances", "payroll_be_parallel_imports", "payroll_be_parallel_differences"}  # + Belgium Block B (2943a0490b5b) + Block C (8a1f5ef9fa5d)
        be_shared = {"payslip_items": {"template_version_id", "be_calculation_snapshot"},
                     "payroll_runs": {"be_approval_fingerprint"}}
        tables, columns = pending_objects("e7ec6c1933b4")
        assert {t: columns.pop(t, None) for t in BE_BLOCK_B_COLUMNS} == BE_BLOCK_B_COLUMNS  # + Belgium Block B (2943a0490b5b)
        assert tables == payslip_template_tables | be_p2_tables | be_block_b_tables
        assert columns == {**mx_m21, **be_shared}
        # A database at Mexico m21 (efc56f3235e2, production's head after PR #157): the payslip
        # templates and Belgium are pending.
        tables, columns = pending_objects("efc56f3235e2")
        assert {t: columns.pop(t, None) for t in BE_BLOCK_B_COLUMNS} == BE_BLOCK_B_COLUMNS  # + Belgium Block B (2943a0490b5b)
        assert tables == payslip_template_tables | be_p2_tables | be_block_b_tables and columns == be_shared
        # Both branches out of f5c1a8d3e9b2 (Mexico M8 and ZP-PRIV) are pending from it.
        tables, columns = pending_objects("f5c1a8d3e9b2")
        assert_google_pending(tables, columns)
        assert {"payroll_mx_vacation_records", "pay_groups", "payroll_mx_terminations"} <= tables
        assert "data_region" in columns.get("organizations", set())
        tables, columns = pending_objects("e3b9c2d7f4a1")
        assert_google_pending(tables, columns)
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
