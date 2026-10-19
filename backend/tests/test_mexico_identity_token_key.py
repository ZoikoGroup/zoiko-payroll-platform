"""Mexico Phase 4b — Q7 strict: identity tokens use MX_IDENTITY_TOKEN_KEY;
the PAYROLL_SECRET_KEY-derived fallback exists only in development/test, and
outside them a missing key refuses every Mexican identifier write. The key
value never appears in a response, audit row or log."""

import json
import logging

import pytest

from tests._mx_employer_helpers import enable_mx_onboarding, make_org, new_mx_employee, save_mx_profile

DEDICATED = "synthetic-mx-identity-key-for-tests-only-0123456789"


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    enable_mx_onboarding(monkeypatch)


def _env(monkeypatch, name):
    monkeypatch.delenv("APP_ENV", raising=False)
    if name is None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ENVIRONMENT", name)


def _key(monkeypatch, value):
    from app.config import settings

    monkeypatch.setattr(settings, "MX_IDENTITY_TOKEN_KEY", value)


@pytest.mark.parametrize("env", ["production", "staging", "prod"])
def test_production_mode_without_a_key_refuses(db, monkeypatch, env):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_identity

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    _env(monkeypatch, env)
    _key(monkeypatch, "")
    assert mexico_identity.key_status() == "MISSING"
    with pytest.raises(BadRequestException, match="MX_IDENTITY_TOKEN_KEY is not configured"):
        save_mx_profile(db, emp, t.org.id)


def test_unset_environment_with_debug_off_counts_as_production(db, monkeypatch):
    from app.config import settings
    from app.modules.payroll import mexico_identity

    _env(monkeypatch, None)
    monkeypatch.setattr(settings, "DEBUG", False)
    _key(monkeypatch, "")
    assert mexico_identity.key_status() == "MISSING"


@pytest.mark.parametrize("env", ["development", "test", "testing"])
def test_dev_and_test_use_the_derived_fallback(db, monkeypatch, env):
    from app.modules.payroll import mexico_identity

    _env(monkeypatch, env)
    _key(monkeypatch, "")
    assert mexico_identity.key_status() == "DEV_FALLBACK"
    assert mexico_identity.identity_token("curp", "X").startswith("v1:")


def test_production_with_a_dedicated_key_works_and_never_echoes_it(db, monkeypatch, caplog):
    from app.modules.payroll import mexico_identity
    from app.modules.payroll.models import TaxConfigurationAudit

    t = make_org(db)
    emp = new_mx_employee(db, t.org.id)
    _env(monkeypatch, "production")
    _key(monkeypatch, DEDICATED)
    caplog.set_level(logging.DEBUG)
    row = save_mx_profile(db, emp, t.org.id)
    assert mexico_identity.key_status() == "DEDICATED"
    assert row.mx_curp_token.startswith("v1:") and row.mx_rfc_last4 == "1AB1"
    blob = json.dumps([[a.new_value, a.old_value, a.reason] for a in db.query(TaxConfigurationAudit).all()], default=str)
    assert DEDICATED not in blob and DEDICATED not in caplog.text and DEDICATED not in row.mx_curp_token


def test_tokens_depend_on_the_key_and_are_stable():
    from app.config import settings
    from app.modules.payroll import mexico_identity

    original = settings.MX_IDENTITY_TOKEN_KEY
    try:
        settings.MX_IDENTITY_TOKEN_KEY = "k1"
        a1, a2 = mexico_identity.identity_token("curp", "ABC"), mexico_identity.identity_token("curp", " abc ")
        settings.MX_IDENTITY_TOKEN_KEY = "k2"
        b = mexico_identity.identity_token("curp", "ABC")
    finally:
        settings.MX_IDENTITY_TOKEN_KEY = original
    assert a1 == a2 and a1 != b
    assert mexico_identity.identity_token("rfc", "ABC") != mexico_identity.identity_token("curp", "ABC")
