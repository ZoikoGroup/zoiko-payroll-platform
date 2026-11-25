"""Gate removal P1 (owner decision 2026-11-25): ZA, JP, NZ, PL, MY and BE have no dormancy switch and no canary list.

Like Spain, they are ordinary countries:

  * the old ``<CC>_TENANT_ONBOARDING_ENABLED`` / ``<CC>_CANARY_ORG_IDS`` settings and the ``*_dormancy`` modules are gone;
  * moving an organisation into one of them is never refused with the dormancy message (the registry / Active-pack
    check still applies);
  * each country's employee validator is an ordinary registered strategy;
  * each organisation API admits an organisation whose payroll jurisdiction is that country and refuses others;
  * the South African tenant guard no longer refuses.
"""
import importlib

import pytest

from app.core.exceptions import NotFoundException

COUNTRIES = {"ZA": "South Africa", "JP": "Japan", "NZ": "New Zealand", "PL": "Poland", "MY": "Malaysia",
             "BE": "Belgium"}
DORMANCY_MODULES = ("south_africa_dormancy", "japan_dormancy", "nz_dormancy", "poland_dormancy", "malaysia_dormancy",
                    "belgium_dormancy")
DORMANT_TEXT = "not open for onboarding"


def test_the_switches_and_modules_are_gone():
    from app.config import settings

    for code in COUNTRIES:
        assert not hasattr(settings, f"{code}_TENANT_ONBOARDING_ENABLED")
        assert not hasattr(settings, f"{code}_CANARY_ORG_IDS")
    for name in DORMANCY_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"app.modules.payroll.{name}")


def test_old_environment_variables_are_ignored(monkeypatch):
    from app.config import Settings

    for code in COUNTRIES:
        monkeypatch.setenv(f"{code}_TENANT_ONBOARDING_ENABLED", "false")
        monkeypatch.setenv(f"{code}_CANARY_ORG_IDS", "1,2")
    Settings()                                                           # extra="ignore": no startup failure


@pytest.mark.parametrize("code,name", sorted(COUNTRIES.items()))
def test_entering_the_country_is_never_refused_as_dormant(db, code, name):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    for new in (name, code):
        reason = get_jurisdiction_change_block_reason(db, "India", new, organization_id=1)
        assert DORMANT_TEXT not in (reason or "")
    assert get_jurisdiction_change_block_reason(db, name, name) is None   # already in the country


@pytest.mark.parametrize("code", ["JP", "NZ", "PL", "MY", "BE"])
def test_company_jurisdiction_can_be_set_to_the_country(db, code):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CompanyDetailsUpdate
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name=f"{code} Company", code=f"CJ{code}", country=None)
    service.get_company_details(db, t.org.id)
    service.update_company_details(db, t.org.id, CompanyDetailsUpdate(jurisdictionCountry=code))
    assert service.get_company_details(db, t.org.id).jurisdiction_country == code


@pytest.mark.parametrize("code", ["JP", "NZ", "PL", "MY", "BE"])
def test_backfill_follows_the_organisation_country(db, code):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name=f"{code} Backfill", code=f"BF{code}", country=None)
    db.get(Organization, t.org.id).country = COUNTRIES[code]
    db.commit()
    assert service.get_company_details(db, t.org.id).jurisdiction_country == code


@pytest.mark.parametrize("code", ["ZA", "NZ", "PL", "MY", "BE"])
def test_employee_validation_is_an_ordinary_strategy(code):
    from app.modules.payroll import employee_validation as ev

    assert code in ev._STRATEGIES and code not in ev._DORMANT_STRATEGIES
    assert ev.is_supported_employee_country(code) is True
    assert ev.get_employee_validation_strategy(code) is ev._STRATEGIES[code]


ROUTER_GUARDS = {
    "JP": ("japan_org_router", "require_japan_tenant"),
    "NZ": ("nz_org_router", "require_nz_tenant"),
    "PL": ("pl_org_router", "require_pl_tenant"),
    "MY": ("my_org_router", "require_my_tenant"),
    "BE": ("be_org_router", "require_be_tenant"),
}


@pytest.mark.parametrize("code", sorted(ROUTER_GUARDS))
def test_organisation_api_is_scoped_by_jurisdiction_only(db, code):
    from tests._mx_employer_helpers import make_org, principal

    module, name = ROUTER_GUARDS[code]
    guard = getattr(importlib.import_module(f"app.modules.payroll.{module}"), name)
    own = make_org(db, name=f"{code} Ltd", code=f"GR{code}1", country=COUNTRIES[code])
    other = make_org(db, name="Other Ltd", code=f"GR{code}2", country="Australia")
    assert guard(principal(own.org.id), db) is None
    with pytest.raises(NotFoundException, match="only available"):
        guard(principal(other.org.id), db)


def test_south_africa_tenant_guard_admits_the_organisation():
    from app.modules.payroll.tenant_statutory_router import _za_org

    assert _za_org(organization_id=7) == 7
