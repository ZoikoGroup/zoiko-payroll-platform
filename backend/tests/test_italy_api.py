"""Italy (ZP-IT-ENG-001) seed script, Super Admin readiness/preview, the Org
Admin employer profile and statutory-profile validation. SQLite `db` fixture
only — nothing here reaches a real database."""
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import italy_service, service
from app.modules.payroll.models import (
    CollectiveAgreement, ContributionRate, JurisdictionPack, PayrollEmployee, TaxSlab,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate, ItalyCalculationPreviewRequest, ItalyEmployerProfileUpsert,
)
from scripts import seed_italy_canonical_pack as seed

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "it_golden" / "italy_golden_2026.json")
                    .read_text(encoding="utf-8"))


@pytest.fixture()
def seeded(db):
    out = seed.seed_italy(db)
    db.commit()
    return out


def _pack(db):
    return db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == italy_service.IT_PACK_ID).one()


def _preview(**kw):
    defaults = dict(payDate=date(2026, 1, 31), gross=D("2500"), workerClass="IMPIEGATO",
                    taxDomicileRegion="03", taxDomicileComune="F205", cscCode="70501", fund="CIG",
                    addregSaldoDue=D("0"), addcomSaldoDue=D("0"), addcomAccontoDue=D("0"))
    defaults.update(kw)
    return ItalyCalculationPreviewRequest(**defaults)


# ── seed script ──────────────────────────────────────────────────────────────
def test_seed_writes_a_draft_pack_and_a_planned_registry_row(db, seeded):
    from app.modules.billing.models import JurisdictionServiceRegistry

    pack = _pack(db)
    assert (pack.status, pack.jurisdiction_country, pack.pack_type) == ("Draft", "IT", "tax")
    assert seeded["availability"] == "PLANNED"
    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "IT").one()
    assert registry.availability == "PLANNED"
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert any(r.jurisdiction_state == "CSC_70501" and r.component_key == "it_inps_ivs" for r in rates)
    brackets = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                         TaxSlab.rule_type == "IT_IRPEF_BRACKET").all())
    assert sorted(b.rate_pct for b in brackets) == [D("23"), D("33"), D("43")]


def test_seed_is_idempotent_and_never_changes_an_existing_registry_row(db, seeded):
    from app.modules.billing.models import JurisdictionServiceRegistry

    before = (db.query(ContributionRate).count(), db.query(TaxSlab).count())
    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "IT").one()
    registry.availability = "BETA"
    db.commit()
    again = seed.seed_italy(db)
    db.commit()
    assert again["availability"] == "BETA"
    assert (db.query(ContributionRate).count(), db.query(TaxSlab).count()) == before


def test_seed_refuses_a_pack_that_left_draft(db, seeded):
    _pack(db).status = "In Review"
    db.commit()
    with pytest.raises(ValueError):
        seed.seed_italy(db)


# ── Super Admin readiness ───────────────────────────────────────────────────
def test_readiness_without_a_pack_says_so(db):
    out = italy_service.get_it_readiness(db)
    assert out["ready"] is False and out["packId"] is None


def test_readiness_is_never_ready_on_seeded_draft_content(db, seeded):
    out = italy_service.get_it_readiness(db)
    items = {i["key"]: i for i in out["items"]}
    assert out["ready"] is False and out["packStatus"] == "Draft"
    assert items["parameters"]["complete"] and items["tax_tables"]["complete"]
    assert items["inps_matrix"]["complete"]
    # Only Lombardia/Milano are staged — every other launch commune is named.
    assert not items["local_tax"]["complete"]
    assert "Roma" in items["local_tax"]["detail"] and "Milano" not in items["local_tax"]["detail"]
    assert not items["no_placeholders"]["complete"]
    for gate in ("statutory_review", "inail", "parallel_payroll", "approval"):
        assert not items[gate]["complete"], gate


def test_readiness_reports_delivered_capabilities_as_complete(db, seeded):
    """F24 derivation and the LUL ledger are built and tested, so the checklist
    must say so. These gates previously reported 'not built' after 3A/3C landed;
    a gate that denies delivered work trains a reviewer to ignore it. Asserting
    the positive case also catches a silent regression back to a hardcoded False."""
    items = {i["key"]: i for i in italy_service.get_it_readiness(db)["items"]}
    assert items["f24_lines"]["complete"] is True
    assert items["lul"]["complete"] is True


def test_readiness_separates_f24_builtness_from_its_empty_causale_catalog(db, seeded):
    """The code is built, but IT-043 forbids inventing causali, so the catalog is
    empty and therefore no F24 can actually be emitted. Those are two different
    facts and collapsing them is how 'built' came to mean 'file generation is not
    built' in the first place."""
    items = {i["key"]: i for i in italy_service.get_it_readiness(db)["items"]}
    assert not items["f24_causale_catalog"]["complete"]
    assert "IT-043" in items["f24_causale_catalog"]["detail"]
    # UniEmens is genuinely unbuilt and must not be confused with either of those.
    assert not items["uniemens"]["complete"]
    assert "v4.32.0" in items["uniemens"]["detail"]


# ── Super Admin preview ─────────────────────────────────────────────────────
def test_preview_runs_the_production_engine_and_matches_the_golden_case(db, seeded):
    golden = next(c for c in GOLDEN if c["name"] == "jan_2500")
    out = italy_service.preview_italy_calculation(db, _preview(
        gross=D(golden["gross"]), fund=golden["fund"], fisBand=golden["fisBand"]))
    assert out["blocked"] is False, (out.get("blockedKey"), out.get("blockedReason"))
    assert out["readOnly"] is True
    assert D(out["result"]["netPay"]) == D(golden["expected"]["netPay"])
    assert D(out["italy"]["irpef"]["withheld"]) == D(golden["expected"]["irpef"])


def test_preview_blocks_for_a_domicile_with_no_local_tax_content(db, seeded):
    out = italy_service.preview_italy_calculation(db, _preview(taxDomicileRegion="12", taxDomicileComune="H501"))
    assert out["blocked"] is True
    assert out["blockedKey"] in ("it_addregionale", "it_addcomunale")


def test_preview_blocks_for_an_unconfigured_inps_classification(db, seeded):
    out = italy_service.preview_italy_calculation(db, _preview(cscCode="99999"))
    assert out["blocked"] is True and out["blockedKey"] == "it_inps_classification"


def test_preview_writes_nothing(db, seeded):
    before = (db.query(ContributionRate).count(), db.query(TaxSlab).count(), db.query(JurisdictionPack).count())
    italy_service.preview_italy_calculation(db, _preview())
    assert (db.query(ContributionRate).count(), db.query(TaxSlab).count(),
            db.query(JurisdictionPack).count()) == before


# ── Org Admin employer profile ──────────────────────────────────────────────
def _employer(**kw):
    defaults = dict(matricolaInps="1234567890", cscCode="70501", cnelCode="H011",
                    fundStatus={"fund": "CIG"}, priorYearAvgHeadcount=12,
                    f24OperatingModel="EMPLOYER", lulMethod="ELECTRONIC")
    defaults.update(kw)
    return ItalyEmployerProfileUpsert(**defaults)


def test_employer_readiness_is_recomputed_and_stays_not_ready_without_inail_facts(db, organization, seeded):
    db.add(CollectiveAgreement(jurisdiction_country="IT", agreement_code="H011", version="1",
                               agreement_type="SECTOR", status="Active", name="Commercio"))
    db.commit()
    profile = italy_service.upsert_employer_profile(db, organization.id, _employer(), actor_id=None)
    items = {i["key"]: i for i in profile.readiness_evidence["items"]}
    assert profile.readiness_status == "NOT_READY"
    for key in ("inps_identity", "inps_classification", "fund_status", "headcount", "ccnl", "operating_models"):
        assert items[key]["complete"], key
    assert not items["inail"]["complete"]


def test_employer_becomes_ready_once_inail_is_recorded(db, organization, seeded):
    from app.modules.payroll.models import EmployerTaxProfile

    db.add(CollectiveAgreement(jurisdiction_country="IT", agreement_code="H011", version="1",
                               agreement_type="SECTOR", status="Active", name="Commercio"))
    db.add(EmployerTaxProfile(organization_id=organization.id, jurisdiction_id="IT",
                              component_code="IT_INAIL_0722", agency_account_id="12345678",
                              employer_rate_pct=D("0.7000"), effective_from=date(2026, 1, 1)))
    db.commit()
    profile = italy_service.upsert_employer_profile(db, organization.id, _employer(), actor_id=None)
    assert profile.readiness_status == "READY", profile.readiness_evidence
    # The PLATFORM gates are separate: Italy itself is still not ready.
    assert italy_service.get_it_readiness(db)["ready"] is False


def test_employer_profile_flags_an_uncovered_classification(db, organization, seeded):
    profile = italy_service.upsert_employer_profile(db, organization.id, _employer(cscCode="11101"), actor_id=None)
    items = {i["key"]: i for i in profile.readiness_evidence["items"]}
    assert not items["inps_classification"]["complete"]
    assert "CSC_11101" in items["inps_classification"]["detail"]


def test_employer_profile_update_keeps_one_row(db, organization, seeded):
    italy_service.upsert_employer_profile(db, organization.id, _employer(), actor_id=None)
    italy_service.upsert_employer_profile(db, organization.id, _employer(priorYearAvgHeadcount=70), actor_id=None)
    profile = italy_service.get_employer_profile(db, organization.id)
    assert profile.prior_year_avg_headcount == 70


@pytest.mark.parametrize("fund_status", [{"fund": "PRIVATE"}, {"fund": "FIS"}, {"fund": "FIS", "fisBand": "HUGE"}])
def test_employer_profile_rejects_an_invalid_fund_position(db, organization, fund_status):
    with pytest.raises(BadRequestException):
        italy_service.upsert_employer_profile(db, organization.id, _employer(fundStatus=fund_status), actor_id=None)


def test_readiness_status_cannot_be_set_from_the_request(db, organization, seeded):
    data = ItalyEmployerProfileUpsert(**_employer().model_dump(), readinessStatus="READY")
    profile = italy_service.upsert_employer_profile(db, organization.id, data, actor_id=None)
    assert profile.readiness_status == "NOT_READY"


# ── statutory-profile validation (§18) ──────────────────────────────────────
def _it_employee(db, organization):
    employee = PayrollEmployee(organization_id=organization.id, employee_code="IT1", name="Mario Rossi",
                               country_code="IT", ctc=D("32500"))
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _profile(**kw):
    defaults = dict(effective_from=date(2026, 1, 1), country_code="IT", it_worker_class="impiegato",
                    it_contract_type="indeterminato", it_tax_domicile_region="03",
                    it_tax_domicile_comune="f205", it_tfr_destination="fondo_tesoreria")
    defaults.update(kw)
    return EmployeeStatutoryProfileCreate(**defaults)


def test_statutory_profile_stores_upper_case_codes(db, organization):
    employee = _it_employee(db, organization)
    row = service.create_employee_statutory_profile_version(db, employee.id, organization.id, _profile(),
                                                            actor_id=None)
    assert (row.it_worker_class, row.it_contract_type, row.it_tax_domicile_comune, row.it_tfr_destination) == \
        ("IMPIEGATO", "INDETERMINATO", "F205", "FONDO_TESORERIA")
    assert row.it_tax_domicile_region == "03"


@pytest.mark.parametrize("bad", [
    {"it_tax_domicile_region": "Lombardia"},                 # a name, not an ISTAT code
    {"it_tax_domicile_comune": "Milano"},                    # a name, not a cadastral code
    {"it_tax_domicile_comune": None},                        # half a domicile (IT-013)
    {"it_contract_type": "FREELANCE"},
    {"it_tfr_destination": "IN_PAGAMENTO"},                  # not a legal destination
    {"it_tfr_destination": "FONDO_PENSIONE"},                # fund not named
    {"it_contributory_cap_cohort": "HIGH_EARNER"},           # IT-017: no recognised evidence
    {"it_contractual_weekly_hours": D("60")},
])
def test_statutory_profile_rejects_values_the_engine_would_block_on(db, organization, bad):
    employee = _it_employee(db, organization)
    with pytest.raises(BadRequestException):
        service.create_employee_statutory_profile_version(db, employee.id, organization.id, _profile(**bad),
                                                          actor_id=None)


def test_routes_are_registered():
    from app.modules.payroll.router import payroll_router
    from app.modules.super_admin.router import router as super_admin_router

    payroll_paths = {r.path for r in payroll_router.routes}
    admin_paths = {r.path for r in super_admin_router.routes}
    assert any(p.endswith("/italy/employer-profile") for p in payroll_paths)
    assert any(p.endswith("/compliance/italy/readiness") for p in admin_paths)
    assert any(p.endswith("/compliance/italy/calculation-preview") for p in admin_paths)
