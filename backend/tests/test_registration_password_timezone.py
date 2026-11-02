"""Registration (POST /api/auth/register) password rule and stored timezone.

The sign-up page asks for at least 12 characters with a letter, a number and
a symbol; the API enforces the same rule. The IANA timezone the form sends is
now stored on the organisation (it used to be accepted and dropped). The
30-day trial sign-up is unchanged.
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import (
    REGISTRATION_PASSWORD_RULE, RegisterRequest, TrialRegisterRequest, registration_password_error,
)


def _data(**overrides):
    fields = dict(organization="Tz Co", name="Ada Admin", email="tz-admin@example.com",
                  password="a-strong-password-1", country="IN", terms_accepted=True)
    fields.update(overrides)
    return fields


@pytest.mark.parametrize("password", [
    "Short1!",                    # under 12
    "no-digits-here-at-all",      # no number
    "nosymbols12345",             # no symbol
    "1234567890!@#",              # no letter
])
def test_weak_registration_passwords_are_refused(password):
    assert registration_password_error(password) == REGISTRATION_PASSWORD_RULE
    with pytest.raises(ValidationError, match="at least 12 characters"):
        RegisterRequest(**_data(password=password))


@pytest.mark.parametrize("password", ["a-strong-password-1", "Correct horse 9 battery", "Zoiko#Payroll2026"])
def test_strong_registration_passwords_are_accepted(password):
    assert registration_password_error(password) is None
    assert RegisterRequest(**_data(password=password)).password == password


def test_trial_sign_up_password_rule_is_unchanged():
    TrialRegisterRequest(organization="Trial Co", name="T Rial", email="t@example.com",
                         password="eightchr", country="India")


@pytest.mark.parametrize("tz, stored", [
    ("Asia/Kolkata", "Asia/Kolkata"), ("America/Argentina/Buenos_Aires", "America/Argentina/Buenos_Aires"),
    ("UTC", "UTC"), ("  Europe/Berlin ", "Europe/Berlin"), ("", None), (None, None),
])
def test_timezone_shape(tz, stored):
    assert RegisterRequest(**_data(timezone=tz)).timezone == stored


@pytest.mark.parametrize("tz", ["Asia/Kolkata; DROP TABLE", "../etc/passwd", "x" * 65, "/Asia"])
def test_malformed_timezone_is_refused(tz):
    with pytest.raises(ValidationError, match="IANA time zone"):
        RegisterRequest(**_data(timezone=tz))


def test_registration_stores_the_timezone(db):
    from app.modules.auth.service import register_enterprise
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(pack_id="IN-TZ-TEST", jurisdiction_country="IN", pack_type="tax",
                            version="1.0", status="Active")
    db.add(pack)
    db.commit()
    db.refresh(pack)
    db.add(ContributionRate(organization_id=None, jurisdiction_country="IN", jurisdiction_pack_id=pack.id,
                            component_key="pf", label="PF", employee_share="—", employer_share="—",
                            total="—", employee_rate_pct=Decimal("12.00")))
    db.commit()

    register_enterprise(db, RegisterRequest(**_data(timezone="Asia/Kolkata")))
    org = db.query(Organization).filter(Organization.organization_name == "Tz Co").one()
    assert org.timezone == "Asia/Kolkata"
