"""
tests/test_ca_golden_test_certification.py
----------------------------------------------
Coverage for service.py's run_golden_test_certification/
list_test_certification_runs generalization to Canada (ZP-TAX-CA-2026-001
§20/AC-29, gap-closure Phase 8, 2026-09-11) — the jurisdiction_country
param and per-country fixtures-directory selection specifically (the
underlying harness/case correctness is covered by tests/test_cra_golden.py
and tests/test_hmrc_golden.py separately).
"""

from app.core.exceptions import BadRequestException
from app.modules.payroll import service


def test_run_golden_test_certification_defaults_to_uk(db):
    run = service.run_golden_test_certification(db)
    assert run.jurisdiction_country == "UK"


def test_run_golden_test_certification_runs_ca_fixtures(db):
    run = service.run_golden_test_certification(db, jurisdiction_country="CA")
    assert run.jurisdiction_country == "CA"
    # The 7 real fixtures in tests/fixtures/cra_golden/ must actually be
    # discovered and run, not silently skipped as "no real cases" (federal-
    # only, Ontario, Quebec, BC H2, NL H2, PE H2, NWT territorial tax).
    assert run.total_cases == 7
    assert run.status == "PASS"
    assert run.passed_cases == 7
    assert run.failed_cases == 0


def test_run_golden_test_certification_rejects_unknown_jurisdiction(db):
    import pytest
    with pytest.raises(BadRequestException):
        service.run_golden_test_certification(db, jurisdiction_country="DE")


def test_run_golden_test_certification_is_case_insensitive(db):
    run = service.run_golden_test_certification(db, jurisdiction_country="ca")
    assert run.jurisdiction_country == "CA"


def test_list_test_certification_runs_filters_by_jurisdiction(db):
    service.run_golden_test_certification(db, jurisdiction_country="UK")
    service.run_golden_test_certification(db, jurisdiction_country="CA")
    service.run_golden_test_certification(db, jurisdiction_country="CA")

    ca_runs = service.list_test_certification_runs(db, jurisdiction_country="CA")
    assert len(ca_runs) == 2
    assert all(r.jurisdiction_country == "CA" for r in ca_runs)

    uk_runs = service.list_test_certification_runs(db, jurisdiction_country="UK")
    assert len(uk_runs) == 1

    all_runs = service.list_test_certification_runs(db)
    assert len(all_runs) == 3
