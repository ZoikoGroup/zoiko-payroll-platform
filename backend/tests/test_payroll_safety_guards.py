"""Regression coverage for payroll fail-closed safety boundaries."""

from decimal import Decimal

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.jurisdictions.germany.pap.core import GermanyCalculationError
from app.modules.payroll.engine.resolver import calculate_payroll


def test_germany_simple_mode_is_blocked_before_statutory_calculation():
    context = PayrollContext(
        gross=Decimal("3000.00"),
        basic=Decimal("3000.00"),
        country="DE",
    )

    with pytest.raises(GermanyCalculationError) as exc_info:
        calculate_payroll(context, "simple")

    assert exc_info.value.code == "GERMANY_SIMPLE_MODE_UNSUPPORTED"


def test_simple_mode_remains_available_for_non_germany_payroll():
    context = PayrollContext(
        gross=Decimal("3000.00"),
        basic=Decimal("3000.00"),
        country="IN",
    )

    result = calculate_payroll(context, "simple")

    assert result.net_pay == Decimal("3000.00")


# NOTE: nikhil's version of this file also carries
# test_paid_transition_rejects_unresolved_payslip_status, covering an
# `advance_payroll_run_status` FAILED/PARTIAL-payslip rejection that does
# not exist in main's current service.py. That behavior is unrelated to
# Germany/DB-guard safety and out of scope for Phase 8DC — not ported here
# to avoid silently introducing an unrelated behavior change. See
# docs/GERMANY_2026_8DC_8DD_8DE_ACTIVATION_HARDENING_REPORT.md.


# ── Phase 8BY: Germany statutory seed/publish scripts refuse non-local DBs ──


@pytest.mark.parametrize("url", [
    "sqlite:///./germany_local.sqlite3",
    "sqlite:///:memory:",
    "postgresql+psycopg://u:p@localhost:5432/zoiko",
    "postgresql+psycopg://u:p@127.0.0.1:5432/zoiko",
    "postgresql+psycopg://u:p@[::1]:5432/zoiko",
])
def test_local_db_guard_accepts_isolated_and_loopback_targets(url):
    from scripts._local_db_guard import is_local_database

    assert is_local_database(url) is True


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://u:p@ep-shared-123.eu-central-1.aws.neon.tech/zoiko",
    "postgresql+psycopg://u:p@db.internal.example.com:5432/zoiko",
    "postgresql+psycopg://u:p@10.0.0.7:5432/zoiko",
    "",  # unconfigured must fail CLOSED, never be treated as local
])
def test_local_db_guard_refuses_non_local_targets(url):
    from scripts._local_db_guard import is_local_database

    assert is_local_database(url) is False


def test_local_db_guard_exits_non_zero_for_remote_target(monkeypatch):
    """The Germany statutory write scripts call this before
    initialize_database(). Against a remote target it must abort the
    process, not merely warn — publishing seed rows to the shared database
    would promote them into live statutory configuration."""
    from scripts import _local_db_guard

    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql+psycopg://u:secret@remote.example.com/zoiko")
    monkeypatch.delenv(_local_db_guard._OVERRIDE_ENV, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        _local_db_guard.assert_local_database("test-script")
    assert exc_info.value.code == 2


def test_local_db_guard_never_prints_the_password(capsys, monkeypatch):
    from scripts import _local_db_guard

    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql+psycopg://u:sup3rsecret@remote.example.com/zoiko")
    monkeypatch.delenv(_local_db_guard._OVERRIDE_ENV, raising=False)

    with pytest.raises(SystemExit):
        _local_db_guard.assert_local_database("test-script")
    assert "sup3rsecret" not in capsys.readouterr().err


def test_local_db_guard_explicit_override_allows_remote_target(monkeypatch):
    """The escape hatch must work for a deliberate operator, and must
    require the exact opt-in value — anything else still refuses."""
    from scripts import _local_db_guard

    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql+psycopg://u:p@remote.example.com/zoiko")
    monkeypatch.setenv(_local_db_guard._OVERRIDE_ENV, _local_db_guard._OVERRIDE_VALUE)
    _local_db_guard.assert_local_database("test-script")  # must not raise

    monkeypatch.setenv(_local_db_guard._OVERRIDE_ENV, "yes")
    with pytest.raises(SystemExit):
        _local_db_guard.assert_local_database("test-script")


def test_every_germany_write_script_calls_the_guard_before_initializing():
    """Structural guard-rail: a future script added to this set must not
    silently skip the check. Asserts the call is present AND ordered
    before initialize_database().

    Phase 8DL: publish_seeded_germany_registries.py and
    seed_germany_compliance_pack_2026.py were reconciled into this
    codebase this phase (previously only existed on the separate
    activation-tooling worktree) — this list now covers all 4 Germany
    write scripts. The guard-call match is intentionally NOT anchored to
    a literal `assert_local_database("` string (seed_germany_compliance_
    pack_2026.py calls it with a `SCRIPT_NAME` variable, not a literal),
    only to the bare `assert_local_database(` call ordered before
    `initialize_database()`."""
    import pathlib

    scripts_dir = pathlib.Path(__file__).resolve().parent.parent / "scripts"
    for name in (
        "seed_germany_2026_registries.py",
        "seed_germany_source_evidence.py",
        "publish_seeded_germany_registries.py",
        "seed_germany_compliance_pack_2026.py",
    ):
        source = (scripts_dir / name).read_text(encoding="utf-8")
        assert "assert_local_database(" in source, f"{name} does not call the local-DB guard"
        # rindex (last occurrence), not index (first) — a module docstring
        # mentioning "assert_local_database()" in prose would otherwise be
        # mistaken for the real call, which always sits near the end of
        # main(), immediately before initialize_database().
        assert source.rindex("assert_local_database(") < source.rindex("initialize_database()"), (
            f"{name} calls the guard after initialize_database()"
        )
