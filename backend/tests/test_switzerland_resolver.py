"""
tests/test_switzerland_resolver.py
----------------------------------
CH Step 6 — resolve_ch_calc_inputs fails closed: a fully configured "world"
resolves READY, and every individual gap yields exactly its own structured
{key, reason} block. Work, residence and QST cantons are independent and come
only from the explicit ch_* fields. Also qst_resolve (advisory, read-only) and
rules_effective, over HTTP.

Every pack value, tariff, scheme rate and salary here is SYNTHETIC.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from tests.test_hong_kong_governance import _http

ON = date(2026, 3, 31)
COMPONENTS = ("ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_uvg", "ch_bvg", "ch_ktg", "ch_qst")


def _pack(db, canton, pack_id, params=None, status="Active"):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="CH", jurisdiction_state=canton, version="1.0",
                            status=status, effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(pack)
    db.flush()
    for key, (amount, text) in (params or {}).items():
        db.add(ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="CH", jurisdiction_state=canton,
                                component_key=key, label=f"TEST {key}", employee_share="—", employer_share="—",
                                total="—", flat_amount=amount, text_value=text))
    db.flush()
    return pack


def _scheme(db, org_id, scheme_type, code, rules, status="LIVE"):
    from app.modules.payroll.models import ChSchemeProfile

    s = ChSchemeProfile(organization_id=org_id, scheme_type=scheme_type, scheme_code=code, name=f"TEST {code}",
                        rules=rules, version="1.0", status=status, effective_from=date(2026, 1, 1))
    db.add(s)
    db.flush()
    return s


@pytest.fixture()
def world(db, organization):
    """Work ZH, residence BE, QST GE — three different cantons, all governed."""
    from app.modules.payroll.models import (
        ChEntityProfile, ChQstTariffFile, EmployeeStatutoryProfile, PayrollEmployee, TaxabilityRule,
    )

    org = organization
    federal = _pack(db, None, "CH-FEDERAL-TEST", {"ch_bvg_entry_threshold": (Decimal("22680"), None)})
    tariff = ChQstTariffFile(canton="CH-GE", file_sha256="a" * 64, status="ACTIVE", row_count=0,
                             effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(tariff)
    db.flush()
    zh = _pack(db, "CH-ZH", "CH-ZH-TEST")
    be = _pack(db, "CH-BE", "CH-BE-TEST")
    ge = _pack(db, "CH-GE", "CH-GE-TEST", {"ch_qst_model": (None, "ANNUAL"),
                                            "ch_qst_tariff_file_id": (None, str(tariff.id))})
    comp = _scheme(db, None, "COMPENSATION_OFFICE", "SVA-TEST", {"admin_cost_pct": "1"})   # catalog scheme
    fak = _scheme(db, org.id, "FAK", "FAK-TEST", {"employer_pct": "1.2"})
    bvg = _scheme(db, org.id, "BVG_PLAN", "BVG-TEST", {"bands": []})
    uvg = _scheme(db, org.id, "UVG_POLICY", "UVG-TEST", {"insurer": "T", "risk_classes": [{"code": "A1"}]})
    ktg = _scheme(db, org.id, "KTG_POLICY", "KTG-TEST", {"rate_pct": "1"})
    db.add(ChEntityProfile(organization_id=org.id, uid="CHE-123.456.789", seat_canton="CH-ZH",
                           compensation_office_scheme_id=comp.id, fak_scheme_id=fak.id,
                           effective_from=date(2026, 1, 1)))
    employee = PayrollEmployee(organization_id=org.id, employee_code="CH1", name="Test Worker", ctc=Decimal("96000"),
                               date_of_birth=date(1990, 5, 1), date_of_joining=date(2025, 1, 1),
                               work_state="CH-BE", pay_frequency="Monthly")
    db.add(employee)
    db.flush()
    profile = EmployeeStatutoryProfile(
        employee_id=employee.id, organization_id=org.id, country_code="CH", effective_from=date(2026, 1, 1),
        ch_work_canton="CH-ZH", ch_residence_canton="CH-BE", ch_residence_country="CH", ch_qst_canton="CH-GE",
        ch_qst_subject="YES", ch_qst_tariff_code="A", ch_children_count=0, ch_church_tax=False,
        ch_bvg_plan_scheme_id=bvg.id, ch_uvg_policy_scheme_id=uvg.id, ch_uvg_risk_class="A1",
        ch_ktg_policy_scheme_id=ktg.id)
    db.add(profile)
    for component in COMPONENTS:
        db.add(TaxabilityRule(jurisdiction_country="CH", earning_type="base_salary", tax_component=component,
                              is_taxable=True, status="Approved", effective_from=date(2026, 1, 1)))
    db.commit()
    return SimpleNamespace(org=org, employee=employee, profile=profile, federal=federal, zh=zh, be=be, ge=ge,
                           tariff=tariff, comp=comp, fak=fak, bvg=bvg, uvg=uvg, ktg=ktg)


def _resolve(db, w, on=ON):
    from app.modules.payroll.switzerland_service import resolve_ch_calc_inputs

    return resolve_ch_calc_inputs(db, w.org.id, w.employee, on)


def _keys(result):
    return [b["key"] for b in result["blocked"]]


def test_fully_configured_worker_resolves_ready(db, world):
    out = _resolve(db, world)
    assert out["ready"] is True and out["blocked"] == []
    i = out["inputs"]
    assert i["cantons"] == {"work": "CH-ZH", "residence": "CH-BE", "residenceCountry": "CH", "qst": "CH-GE"}
    assert i["workCantonPack"]["id"] == world.zh.id and i["qst"]["packId"] == world.ge.id
    assert i["qst"]["tariffFileId"] == world.tariff.id and i["qst"]["model"] == "ANNUAL"
    assert i["federalPack"]["parameters"]["ch_bvg_entry_threshold"]["amount"] == Decimal("22680")
    assert i["bvgEligible"] is True
    assert i["schemes"] == {"COMPENSATION_OFFICE": world.comp.id, "FAK": world.fak.id, "BVG_PLAN": world.bvg.id,
                            "UVG_POLICY": world.uvg.id, "KTG_POLICY": world.ktg.id}
    assert set(i["taxability"]) == set(COMPONENTS)
    assert i["ytd"]["ch_ahv"] == {"wages": Decimal("0"), "withheld": Decimal("0"), "recorded": False}


def _raw_delete(db, model):
    db.execute(sa.delete(model.__table__))      # bypasses the ORM no-delete guards (test setup only)


def _set(attr, value):
    return lambda db, w: setattr(w.profile, attr, value)


def _status(target, value):
    return lambda db, w: setattr(getattr(w, target), "status", value)


def _raw_status(target, value):
    # a LIVE scheme cannot be moved back through the ORM (the immutability
    # guard refuses it), so a non-LIVE state is written straight to the table
    def mutate(db, w):
        from app.modules.payroll.models import ChSchemeProfile

        table = ChSchemeProfile.__table__
        db.execute(sa.update(table).where(table.c.id == getattr(w, target).id).values(status=value))
    return mutate


def _no_rule(component):
    def mutate(db, w):
        from app.modules.payroll.models import TaxabilityRule

        db.query(TaxabilityRule).filter(TaxabilityRule.tax_component == component).update({"status": "Draft"})
    return mutate


def _no_entity(db, w):
    from app.modules.payroll.models import ChEntityProfile

    _raw_delete(db, ChEntityProfile)


def _no_profile(db, w):
    w.profile.effective_from = date(2026, 6, 1)        # nothing in force on ON


def _no_threshold(db, w):
    from app.modules.payroll.models import ContributionRate

    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == w.federal.id).delete()


def _no_model(db, w):
    from app.modules.payroll.models import ContributionRate

    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == w.ge.id,
                                      ContributionRate.component_key == "ch_qst_model").update({"text_value": None})


def _wrong_floor(db, w):
    from app.modules.payroll.models import CollectiveAgreement

    a = CollectiveAgreement(jurisdiction_country="CH", jurisdiction_state="CH-ZH", agreement_code="CH-ZH-FLOOR",
                            name="TEST", agreement_type="CH_CANTON_MINIMUM", version="1.0", status="Approved",
                            effective_from=date(2026, 1, 1), modules={"wage_floor": {"basis": "HOURLY", "amount": "1"}})
    db.add(a)
    db.flush()
    w.profile.ch_wage_floor_agreement_id = a.id


@pytest.mark.parametrize("expected, mutate", [
    ("ch_entity_profile", _no_entity),
    ("ch_worker_profile", _no_profile),
    ("ch_work_canton", _set("ch_work_canton", None)),
    ("ch_residence_country", _set("ch_residence_country", None)),
    ("ch_residence_canton", _set("ch_residence_canton", "BE")),
    ("ch_qst_subject", _set("ch_qst_subject", None)),
    ("ch_qst_subject_review", _set("ch_qst_subject", "REVIEW_REQUIRED")),
    ("ch_qst_canton", _set("ch_qst_canton", None)),
    ("ch_qst_tariff_code", _set("ch_qst_tariff_code", None)),
    ("ch_children_count", _set("ch_children_count", None)),
    ("ch_church_tax", _set("ch_church_tax", None)),
    ("ch_federal_pack", _status("federal", "Draft")),
    ("ch_work_canton_pack", _status("zh", "Draft")),
    ("ch_qst_canton_pack", _status("ge", "Draft")),
    ("ch_qst_model", _no_model),
    ("ch_qst_tariff_file", _status("tariff", "SUPERSEDED")),
    ("ch_compensation_office", _status("comp", "RETIRED")),
    ("ch_fak_scheme", _raw_status("fak", "APPROVED")),
    ("ch_bvg_entry_threshold", _no_threshold),
    ("ch_date_of_birth", lambda db, w: setattr(w.employee, "date_of_birth", None)),
    ("ch_annual_salary", lambda db, w: setattr(w.employee, "ctc", Decimal("0"))),
    ("ch_bvg_plan", _set("ch_bvg_plan_scheme_id", None)),
    ("ch_uvg_policy", _set("ch_uvg_policy_scheme_id", None)),
    ("ch_uvg_risk_class", _set("ch_uvg_risk_class", "Z9")),
    ("ch_ktg_policy", _status("ktg", "RETIRED")),
    ("ch_wage_floor", _wrong_floor),
    *[(f"ch_taxability:{c}", _no_rule(c)) for c in COMPONENTS],
    ("ch_pay_frequency", lambda db, w: setattr(w.employee, "pay_frequency", "Weekly")),
])
def test_each_gap_blocks_with_exactly_its_own_key(db, world, expected, mutate):
    mutate(db, world)
    db.commit()
    out = _resolve(db, world)
    assert out["ready"] is False
    keys = _keys(out)
    assert expected in keys, out["blocked"]
    # a gap never cascades into unrelated blocks (a missing worker profile
    # necessarily hides the worker-level facts that depend on it)
    if expected != "ch_worker_profile":
        assert keys == [expected], out["blocked"]
    assert all(b["reason"] for b in out["blocked"])


def test_missing_worker_profile_blocks_without_inventing_worker_facts(db, world):
    _no_profile(db, world)
    db.commit()
    keys = _keys(_resolve(db, world))
    assert keys[0] == "ch_worker_profile"
    assert not {"ch_work_canton", "ch_qst_subject", "ch_uvg_policy"} & set(keys)   # never re-reported as defaults


def test_tariff_file_must_be_the_qst_cantons_own_and_in_force(db, world):
    world.tariff.canton = "CH-VD"
    db.commit()
    out = _resolve(db, world)
    assert _keys(out) == ["ch_qst_tariff_file"] and "belongs to CH-VD" in out["blocked"][0]["reason"]
    world.tariff.canton, world.tariff.effective_to = "CH-GE", date(2026, 2, 28)
    db.commit()
    assert "not in force" in _resolve(db, world)["blocked"][0]["reason"]


def test_bvg_and_ktg_are_only_required_when_they_apply(db, world):
    world.employee.ctc = Decimal("20000")                   # below the entry threshold
    world.profile.ch_bvg_plan_scheme_id = None
    world.profile.ch_ktg_policy_scheme_id = None
    db.commit()
    out = _resolve(db, world)
    assert out["ready"] is True and out["inputs"]["bvgEligible"] is False
    assert "ch_bvg" not in out["inputs"]["taxability"] and "ch_ktg" not in out["inputs"]["taxability"]
    world.employee.ctc, world.employee.date_of_birth = Decimal("96000"), date(2009, 6, 1)   # turns 17 in 2026
    db.commit()
    assert _resolve(db, world)["inputs"]["bvgEligible"] is False


def test_qst_facts_are_not_required_when_not_liable(db, world):
    p = world.profile
    p.ch_qst_subject, p.ch_qst_canton, p.ch_qst_tariff_code, p.ch_children_count, p.ch_church_tax = (
        "NO", None, None, None, None)
    world.ge.status = "Draft"
    db.commit()
    out = _resolve(db, world)
    assert out["ready"] is True and out["inputs"]["qst"] is None and "ch_qst" not in out["inputs"]["taxability"]


# ── canton independence ─────────────────────────────────────────────────

def test_work_residence_and_qst_cantons_resolve_independently(db, world):
    world.zh.status = "Draft"                               # only the WORK canton's pack is missing
    db.commit()
    assert _keys(_resolve(db, world)) == ["ch_work_canton_pack"]
    world.zh.status, world.be.status = "Active", "Draft"    # residence pack is not a calculation input
    db.commit()
    assert _resolve(db, world)["ready"] is True
    world.ge.status = "Draft"                               # only the QST canton's pack is missing
    db.commit()
    assert _keys(_resolve(db, world)) == ["ch_qst_canton_pack"]


def test_a_canton_is_never_inferred_from_work_state_or_the_seat_canton(db, world):
    world.profile.ch_work_canton = None
    world.employee.work_state = "CH-ZH"                     # present, but never used
    db.commit()
    out = _resolve(db, world)
    assert _keys(out) == ["ch_work_canton"] and "never used" in out["blocked"][0]["reason"]
    assert out["inputs"]["workCantonPack"] is None and out["inputs"]["cantons"]["work"] is None


def test_a_canton_pack_never_falls_back_to_the_federal_pack(db, world):
    world.zh.status = "Draft"
    db.commit()
    out = _resolve(db, world)
    assert out["inputs"]["workCantonPack"] is None and out["inputs"]["federalPack"]["id"] == world.federal.id


def test_cross_border_worker_needs_no_residence_canton(db, world):
    world.profile.ch_residence_country, world.profile.ch_residence_canton = "FR", None
    db.commit()
    assert _resolve(db, world)["ready"] is True


def test_resolver_is_read_only(db, world):
    from app.modules.payroll.models import PayrollYtdAccumulator, TaxConfigurationAudit

    before = (db.query(TaxConfigurationAudit).count(), db.query(PayrollYtdAccumulator).count())
    _resolve(db, world)
    assert not db.new and not db.dirty and not db.deleted
    assert (db.query(TaxConfigurationAudit).count(), db.query(PayrollYtdAccumulator).count()) == before


def test_ytd_reads_recorded_ch_totals(db, world):
    from app.modules.payroll.models import PayrollYtdAccumulator

    db.add(PayrollYtdAccumulator(employee_id=world.employee.id, tax_year="CH-CY-2026", tax_component="ch_qst",
                                 ytd_taxable_wages=Decimal("16000"), ytd_tax_withheld=Decimal("880")))
    db.add(PayrollYtdAccumulator(employee_id=world.employee.id, tax_year="CH-CY-2025", tax_component="ch_qst",
                                 ytd_taxable_wages=Decimal("1"), ytd_tax_withheld=Decimal("1")))
    db.commit()
    ytd = _resolve(db, world)["inputs"]["ytd"]
    assert ytd["ch_qst"] == {"wages": Decimal("16000"), "withheld": Decimal("880"), "recorded": True}


# ── qst_resolve (advisory) + rules_effective, over HTTP ─────────────────

@pytest.fixture()
def admin(organization):
    return SimpleNamespace(id=501, organization_id=organization.id, role="org_admin", is_active=True)


@pytest.mark.parametrize("facts, applicability", [
    ({"nationality": "CH", "residenceCountry": "CH"}, "NOT_SUBJECT"),
    ({"nationality": "DE", "residenceCountry": "CH", "permitType": "C"}, "NOT_SUBJECT"),
    ({"nationality": "DE", "residenceCountry": "CH", "permitType": "B"}, "SUBJECT"),
    ({"nationality": "DE", "residenceCountry": "CH", "permitType": "B", "maritalStatus": "MARRIED",
      "spouseSwissOrPermitC": True}, "NOT_SUBJECT"),
    ({"nationality": "DE", "residenceCountry": "CH", "permitType": "B", "maritalStatus": "MARRIED"},
     "REVIEW_REQUIRED"),
    ({"nationality": "FR", "residenceCountry": "FR", "permitType": "G"}, "REVIEW_REQUIRED"),
    ({"nationality": "ES", "residenceCountry": "ES"}, "SUBJECT"),
    ({"nationality": "DE"}, "UNDETERMINED"),
    ({"nationality": "DE", "residenceCountry": "CH"}, "UNDETERMINED"),
])
def test_qst_resolve_applicability_is_advisory(db, admin, facts, applicability):
    with _http(db, admin) as c:
        res = c.post("/api/payroll/switzerland/qst/resolve", json=facts)
    body = res.json()
    assert res.status_code == 200 and body["applicability"] == applicability and body["advisory"] is True


def test_qst_resolve_lists_required_and_missing_tariff_facts(db, admin):
    with _http(db, admin) as c:
        body = c.post("/api/payroll/switzerland/qst/resolve", json={
            "nationality": "IT", "residenceCountry": "CH", "permitType": "B", "maritalStatus": "MARRIED",
            "spouseSwissOrPermitC": False, "childrenCount": 2, "qstCanton": "CH-TI"}).json()
    assert body["applicability"] == "SUBJECT"
    assert body["requiredTariffFacts"] == ["qst_canton", "marital_status", "children_count", "church_tax",
                                           "spouse_employed"]
    assert body["missingFacts"] == ["church_tax", "spouse_employed"]
    assert body["model"] == {"value": "ANNUAL", "source": "reference list (S9) — no Active canton pack sets it",
                             "authoritative": False, "conflict": False}


def test_qst_model_prefers_the_active_canton_pack_and_flags_a_conflict(db, world, admin):
    world.ge.effective_from = date(2025, 1, 1)
    _pack(db, "CH-ZH", "CH-ZH-QST-TEST", {"ch_qst_model": (None, "ANNUAL")})    # ZH is a monthly-model canton
    world.zh.status = "Draft"
    db.commit()
    with _http(db, admin) as c:
        body = c.post("/api/payroll/switzerland/qst/resolve", json={
            "nationality": "DE", "residenceCountry": "ES", "qstCanton": "CH-ZH", "onDate": "2026-03-31"}).json()
    assert body["model"]["value"] == "ANNUAL" and body["model"]["authoritative"] is True
    assert body["model"]["conflict"] is True


def test_qst_resolve_rejects_unknown_fields_and_writes_nothing(db, admin):
    from app.modules.payroll.models import TaxConfigurationAudit

    with _http(db, admin) as c:
        assert c.post("/api/payroll/switzerland/qst/resolve", json={"qstSubject": "YES"}).status_code == 422
        assert c.post("/api/payroll/switzerland/qst/resolve", json={"qstCanton": "GE"}).json()["missingFacts"] \
            == ["nationality", "qst_canton", "residence_country"]
    assert db.query(TaxConfigurationAudit).count() == 0


def test_rules_effective_reports_what_is_in_force(db, world, admin):
    with _http(db, admin) as c:
        seat = c.get("/api/payroll/switzerland/rules/effective", params={"on": "2026-03-31"}).json()
        ge = c.get("/api/payroll/switzerland/rules/effective", params={"on": "2026-03-31", "canton": "CH-GE"}).json()
        assert c.get("/api/payroll/switzerland/rules/effective", params={"canton": "GE"}).status_code == 400
        later = c.get("/api/payroll/switzerland/rules/effective", params={"on": "2027-03-31"}).json()
    assert seat["canton"] == "CH-ZH" and seat["cantonPack"]["id"] == world.zh.id and seat["qstTariffFiles"] == []
    assert seat["federalPack"]["id"] == world.federal.id
    assert {s["id"] for s in seat["schemes"]} == {world.comp.id, world.fak.id, world.bvg.id, world.uvg.id, world.ktg.id}
    assert seat["taxability"]["ch_ahv"] == {"base_salary": True}
    assert ge["cantonPack"]["id"] == world.ge.id and [t["id"] for t in ge["qstTariffFiles"]] == [world.tariff.id]
    assert later["federalPack"] is None and later["cantonPack"] is None
