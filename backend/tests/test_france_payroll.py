"""
tests/test_france_payroll.py
----------------------------
France payroll (ZP-FR-ENG-001) — engine golden vectors, fail-closed block
paths, dispatch safety, jurisdiction-gate + employee-validation wiring, and
the Phase 7 DSN/PAS/establishment/readiness service layer.

Engine tests are pure (rate_map in / PayrollResult out), mirroring
test_engine_standard.py's in-memory vsqlite db* pattern. Service tests use
the conftest `db` fixture (in-memory SQLite, fresh per test).
"""
from datetime import date
from decimal import Decimal
from dataclasses import dataclass

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.engine.resolver import calculate_payroll
from app.modules.payroll.engine.countries.france import (
    FranceCalculationBlockedError,
    calculate as france_calculate,
)


@dataclass
class Rate:
    """Minimal stand-in for a ContributionRate row — only the attributes
    the engine reads (same shape as test_engine_standard.py)."""
    component_key: str = ""
    employee_rate_pct: Decimal = None
    employer_rate_pct: Decimal = None
    flat_amount: Decimal = None


def _rate(key, pct):
    return Rate(key, Decimal(str(pct)), Decimal(str(pct)))


# ── 2026 published France contribution rates (content-as-data map) ───────
# Mirrors the _FR_* hardcoded fallbacks; a France calculation REQUIRES a
# configured rate_map row for every mandatory contribution (FR-027 fail-
# closed), so this is what the golden vectors run on.
FR_RATES = {key: _rate(key, pct) for key, pct in [
    ("fr_vieillesse_capped_ee", 6.90), ("fr_vieillesse_capped_er", 8.55),
    ("fr_vieillesse_uncapped_ee", 0.40), ("fr_vieillesse_uncapped_er", 2.11),
    ("fr_agirc_t1_ee", 3.15), ("fr_agirc_t1_er", 4.72),
    ("fr_agirc_t2_ee", 8.64), ("fr_agirc_t2_er", 12.95),
    ("fr_ceg_t1_ee", 0.86), ("fr_ceg_t1_er", 1.29),
    ("fr_ceg_t2_ee", 1.08), ("fr_ceg_t2_er", 1.62),
    ("fr_cet_ee", 0.14), ("fr_cet_er", 0.21),
    ("fr_apec_ee", 0.024), ("fr_apec_er", 0.036),
    ("fr_csg_deductible", 6.80), ("fr_csg_nondeductible", 2.40), ("fr_crds", 0.50),
    ("fr_sante_er", 13.00), ("fr_sante_er_reduced", 7.00),
    ("fr_famille_er", 5.25), ("fr_csa_er", 0.50),
    ("fr_chomage_er", 4.00), ("fr_ags_er", 0.25),
    ("fr_fnal_er_0p10", 0.10), ("fr_fnal_er_0p50", 0.50),
    ("fr_cfp_er_0p55", 0.55), ("fr_cfp_er_1p00", 1.00),
    ("fr_apprentissage_er", 0.59), ("fr_apprentissage_balance_er", 0.09),
]}

FR_ESTABLISHMENT = dict(
    siret="55210055400021", at_mp_rate_pct="2.09", vm_rate_pct="2.80",
    fnal_class="0p10", cfp_class="0p55", effectif=36, commune_insee="75056",
)
FR_PAS = {"rate_type": "PERSONALIZED", "rate_pct": Decimal("10"), "rate_id": "DGFIP-2026-0001"}
FR_YTD = dict(rgdu_remuneration="15000", rgdu_smic_reference="109383.2", rgdu_relief="1500", pass_used="15000")


def fr_result(gross=3000, *,
              cadre=True, pas=None, ytd=None, establishment=None,
              payroll_date=date(2026, 6, 30), rate_map=None, **ctx_kw):
    """Build a France PayrollContext through StandardStrategy."""
    ctx = PayrollContext(
        country="FR", gross=Decimal(str(gross)), basic=Decimal(str(gross)),
        rate_map=rate_map if rate_map is not None else FR_RATES,
        pay_date=payroll_date, france_payroll_date=payroll_date,
        france_social_coverage=ctx_kw.get("france_social_coverage", "GENERAL"),
        france_establishment=establishment if establishment is not None else FR_ESTABLISHMENT,
        france_pas=pas if pas is not None else dict(FR_PAS),
        france_ytd=ytd if ytd is not None else dict(FR_YTD),
        france_cadre=cadre,
        france_idcc_minimum=ctx_kw.get("france_idcc_minimum"),
        france_working_hours=ctx_kw.get("france_working_hours"),
        france_overtime_hours=ctx_kw.get("france_overtime_hours"),
        france_employee_id=1, france_organization_id=1,
    )
    return StandardStrategy().calculate(ctx)


# ── A. Engine golden vectors (frozen from the verified June-2026 runs) ──

def test_fr_golden_vector_cadre_june_2026():
    r = fr_result(3000)
    assert r.net_pay == Decimal("2129.59")
    assert r.total_deductions == Decimal("870.41")
    assert r.fr_net_social == Decimal("2374.07")
    assert r.fr_net_imposable == Decimal("2444.81")
    assert r.fr_employee_total == Decimal("870.41")
    assert r.fr_employer_total == Decimal("1377.78")
    assert r.fr_pas_withheld == Decimal("244.48")
    assert r.fr_pas_rate_type == "PERSONALIZED"
    assert r.fr_pas_rate_pct == Decimal("10")


def test_fr_golden_net_identity_three_values_never_one_net():
    """FR-042: the three France nets reconcile. net à payer = net social -
    PAS = gross - fr_employee_total; net imposable = net social + CSGN."""
    r = fr_result(3000)
    contrib = {c["code"]: c for c in r.fr_contributions}
    csg_nondeductible = contrib["CSGN"]["ee"]
    assert r.fr_net_imposable == r.fr_net_social + csg_nondeductible
    net_a_payer = r.fr_calculation_snapshot["net_a_payer"]
    assert net_a_payer == r.fr_net_social - r.fr_pas_withheld
    assert net_a_payer == r.net_pay
    # net_pay = gross - fr_employee_total (combined EE SS + PAS)
    assert r.fr_employee_total == r.fr_bases["gross"] - net_a_payer


def test_fr_golden_independent_bases_fr005():
    """FR-005: every contribution rides its OWN base, exposed in fr_bases."""
    r = fr_result(3000)
    b = r.fr_bases
    assert b["gross"] == Decimal("3000.00")
    assert b["vieillesse_capped"] == Decimal("3000.00")   # <= PSS 4005
    assert b["vieillesse_uncapped"] == Decimal("3000.00")
    assert b["chomage_ags_4x_pass"] == Decimal("3000.00")  # <= 4xPASS envelope
    assert b["agirc_t1"] == Decimal("3000.00")
    assert b["agirc_t2"] == Decimal("0.00")
    assert b["cet"] == Decimal("0.00")                    # gross <= PSS → no CET
    assert b["csg_crds"] == Decimal("2947.50")            # 3000 x 98.25%
    assert b["pas"] == r.fr_net_imposable
    # contribution amount = rate x ITS OWN base
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["YG000"]["ee"] == (b["vieillesse_capped"] * Decimal("6.90") / 100).quantize(Decimal("0.01"))
    assert contrib["CSGD"]["base"] == b["csg_crds"]


def test_fr_golden_contributions_trace_21_lines():
    r = fr_result(3000)
    assert len(r.fr_contributions) == 21
    codes = {c["code"] for c in r.fr_contributions}
    assert {"YG000", "YH000", "PB000", "PA000", "YALT", "AC1P", "AGSP", "FNAL",
            "CFP", "APP", "ATMP", "VMRR", "RE1B", "REFV", "CET", "APEC",
            "CSGD", "CSGN", "CRDS"} <= codes


def test_fr_rgdu_fresh_month_relief_applies():
    """Month 1, zero YTD: full RGDU delta materialises and the employer
    total drops by exactly the computed relief."""
    r = fr_result(3000, ytd={}, payroll_date=date(2026, 1, 31))
    rgdu = r.fr_calculation_snapshot["rgdu"]
    assert rgdu["eligible"] is True
    assert rgdu["coefficient"] == Decimal("0.3981")
    assert rgdu["theoretical_relief"] == Decimal("1194.30")
    assert rgdu["monthly_delta"] == Decimal("1194.30")
    assert rgdu["relief_urssaf"] == Decimal("1018.34")
    assert rgdu["relief_agirc"] == Decimal("175.96")
    assert r.fr_calculation_snapshot["employer_before_relief"] == Decimal("1377.78")
    assert r.fr_employer_total == Decimal("1377.78") - Decimal("1194.30")


def test_fr_rgdu_already_granted_zero_delta():
    """YTD relief already exceeds theoretical → no double payment this period."""
    r = fr_result(3000)
    rgdu = r.fr_calculation_snapshot["rgdu"]
    assert rgdu["already_granted"] == Decimal("1500.00")
    assert rgdu["monthly_delta"] == Decimal("0.00")
    assert r.fr_employer_total == r.fr_calculation_snapshot["employer_before_relief"]


def test_fr_non_cadre_apec_zero():
    r = fr_result(3000, cadre=False)
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["APEC"]["ee"] == Decimal("0.00")
    assert contrib["APEC"]["er"] == Decimal("0.00")
    assert r.fr_employee_total == Decimal("869.76")
    assert r.fr_employer_total == Decimal("1376.70")
    assert r.net_pay == Decimal("2130.24")


def test_fr_under_11_reduced_sante():
    """FEWER than 11 employees → reduced salud rate up to 2.5x SMIC band."""
    est = {**FR_ESTABLISHMENT, "effectif": 8}
    r = fr_result(3000, establishment=est)
    contrib = {c["code"]: c for c in r.fr_contributions}
    # 13% → 7% band on full 3000 (< 4557.63 band ceiling)
    assert contrib["PB000"]["er"] == Decimal("210.00")
    assert r.fr_employer_total == Decimal("1197.78")
    assert r.fr_employee_total == Decimal("870.41")  # employee side untouched


def test_fr_t2_cet_above_pss():
    """Gross above PSS → Agirc T2 + CEG T2 + CET all engage."""
    r = fr_result(6000, ytd=dict(rgdu_remuneration="30000", rgdu_smic_reference="50000",
                                 rgdu_relief="0", pass_used="30000"))
    b = r.fr_bases
    assert b["agirc_t2"] == Decimal("1995.00")   # 6000 - 4005 PSS
    assert b["cet"] == Decimal("6000.00")        # gross > PSS
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["RE2B"]["ee"] > 0
    assert contrib["CET"]["ee"] == Decimal("8.40")   # 6000 x 0.14%
    assert r.fr_employee_total == Decimal("1727.03")
    assert r.fr_pas_withheld == Decimal("490.50")
    assert r.fr_employer_total == Decimal("293.40")  # after 2462.00 RGDU relief


def test_fr_csg_4x_pass_envelope_boundary():
    """CSG/CRDS uses the 98.25% factor on the 4xPASS annual envelope
    remainder and the FULL base above it (FR-016)."""
    r = fr_result(20000, ytd=dict(rgdu_remuneration="170000", rgdu_smic_reference="230000",
                                  rgdu_relief="13000", pass_used="177240"),
                  payroll_date=date(2026, 12, 31))
    # 4xPASS annual 192240.00 - 177240.00 used = 15000 still inside envelope
    assert r.fr_calculation_snapshot["csg_base"] == Decimal("19737.50")
    assert r.fr_calculation_snapshot["csg_base_factor"] == Decimal("98.25")
    assert r.fr_bases["csg_crds"] == Decimal("19737.50")


def test_fr_neutral_short_contract_748_abatement():
    pas = {"rate_type": "NEUTRAL", "rate_pct": Decimal("7.5"), "grid_version": "GRID-2026-05",
           "short_contract": True}
    r = fr_result(2000, pas=pas)
    assert r.fr_pas_rate_type == "NEUTRAL"
    assert r.fr_bases["pas"] == Decimal("881.87")   # 1629.87 - 748 abatement
    assert r.fr_pas_withheld == Decimal("66.14")
    assert r.net_pay == Decimal("1516.57")


def test_fr_apprentice_exemption():
    pas = {"rate_type": "NEUTRAL", "rate_pct": Decimal("7.5"), "grid_version": "GRID-2026-05",
           "apprentice": True}
    r = fr_result(2000, pas=pas)
    assert r.fr_pas_withheld == Decimal("0.00")
    assert r.net_pay == r.fr_net_social     # PAS fully exempt → net à payer = net social


# ── B. Fail-closed block paths (FR-027) ─────────────────────────────────

def test_fr_block_payroll_date_missing():
    ctx = PayrollContext(country="FR", gross=Decimal("3000"), basic=Decimal("3000"),
                         rate_map=FR_RATES, france_establishment=FR_ESTABLISHMENT,
                         france_pas=dict(FR_PAS), france_ytd=dict(FR_YTD))
    with pytest.raises(FranceCalculationBlockedError) as exc:
        StandardStrategy().calculate(ctx)
    assert exc.value.code == "PAYROLL_DATE_MISSING"


def test_fr_block_pas_not_resolved():
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, pas={})
    assert exc.value.code == "PAS_NOT_RESOLVED"


def test_fr_block_establishment_incomplete():
    est = dict(FR_ESTABLISHMENT)
    del est["siret"]
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, establishment=est)
    assert exc.value.code == "ESTABLISHMENT_INCOMPLETE"


def test_fr_block_alsace_moselle_not_enabled():
    est = {**FR_ESTABLISHMENT, "commune_insee": "67000"}
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, establishment=est)
    assert exc.value.code == "ALSACE_MOSELLE_NOT_ENABLED"


def test_fr_block_social_coverage_unsupported():
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, france_social_coverage="MSA")
    assert exc.value.code == "SOCIAL_COVERAGE_UNSUPPORTED"


def test_fr_block_smic_minimum_breach():
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(1500)
    assert exc.value.code == "SMIC_MINIMUM_BREACH"
    assert "FR-044" in exc.value.message


def test_fr_block_idcc_minimum_breach():
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, france_idcc_minimum=Decimal("4000"))
    assert exc.value.code == "IDCC_MINIMUM_BREACH"


def test_fr_block_mandatory_rate_not_configured():
    """FR-027: an empty rate_map blocks the whole run — hardcoded fallbacks
    are provenance, never silently sufficient."""
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, rate_map={})
    assert exc.value.code == "MANDATORY_RATE_NOT_CONFIGURED"
    assert "fr_vieillesse_capped_ee" in exc.value.message


# ── C. Dispatch safety + wiring ─────────────────────────────────────────

def test_fr_dispatched_by_standard():
    from app.modules.payroll.engine.standard import _COUNTRY_CALC
    assert _COUNTRY_CALC["FR"] is france_calculate


def test_fr_via_public_resolver():
    ctx = PayrollContext(
        country="FR", gross=Decimal("3000"), basic=Decimal("3000"), rate_map=FR_RATES,
        pay_date=date(2026, 6, 30), france_payroll_date=date(2026, 6, 30),
        france_establishment=FR_ESTABLISHMENT, france_pas=dict(FR_PAS),
        france_ytd=dict(FR_YTD), france_cadre=True,
    )
    result = calculate_payroll(ctx)
    assert result.net_pay == Decimal("2129.59")


def test_fr_additive_defaults_for_other_countries():
    """Adding France never mutates another country's result shape."""
    from tests.test_engine_standard import calc  # the shared harness helper
    r = calc("IN", 20000)
    assert r.net_pay > 0
    assert r.fr_net_social is None          # untouched France fields
    assert r.fr_employee_total == Decimal("0")


def test_fr_registered_in_core_jurisdiction():
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, JURISDICTION_TAX_SCHEMAS
    assert "France" in REGISTRATION_COUNTRIES          # dropdown is by country name
    schema = JURISDICTION_TAX_SCHEMAS["FR"]
    assert schema["currency"] == "EUR"
    fields = {f["key"]: f for f in schema["fields"]}
    assert fields["siren"]["pattern"] == r"^\d{9}$"      # SIREN: 9 digits
    assert fields["siret"]["pattern"] == r"^\d{14}$"     # SIRET: 14 digits (9+5 NIC)
    assert fields["siret"]["primary"] is False           # primary stays SIREN
    assert fields["vat_intracom"]["pattern"] == r"^FR[0-9]{11}$"


def test_fr_employee_validation_strategy():
    from app.modules.payroll.employee_validation import get_employee_validation_strategy
    strategy = get_employee_validation_strategy("FR")
    cleaned = strategy.validate({"nir": "175087812345678", "siret": "55210055400021"})
    assert cleaned["nir"] == "175087812345678"
    with pytest.raises(Exception):
        strategy.validate({"nir": "1750878123456", "siret": "55210055"})
    with pytest.raises(Exception):
        strategy.validate({"nir": "", "siret": ""})


# ── D. Service layer (DB) — Phase 7 ─────────────────────────────────────

def _mk_employee(db, org_id, code="E001"):
    from app.modules.payroll.models import PayrollEmployee
    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Emp {code}",
                          email=f"{code}@acme.fr", country_code="FR", basic=Decimal("3000"))
    db.add(emp)
    db.commit()
    return emp


def _configure_france(db, org_id, emp, siren="552100554", *,
                      due_class="M15", effectif_year=2025, effectif_value=36,
                      at_mp="2.09", pas_effective=date(2026, 1, 1), pas_pct=Decimal("10")):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import (
        EmployerFranceProfileUpsert, FranceEffectifRecord,
        FranceEstablishmentRatePackUpsert, FrancePASRateUpsert,
    )
    s.upsert_employer_france_profile(
        db, org_id, EmployerFranceProfileUpsert(
            siren=siren, legalName="ACME SAS", legalForm="SAS", idcc="1596",
            urssafAccount="7500000000001", dsnDeclarant="ACME",
            filingDueDateClass=due_class, readinessStatus="READY"), actor_id=1)
    s.record_france_effectif(db, org_id, FranceEffectifRecord(
        year=effectif_year, value=effectif_value, source="DSN"), actor_id=1)
    s.upsert_france_establishment_rate_pack(
        db, org_id, FranceEstablishmentRatePackUpsert(
            siret="55210055400021", atMpRatePct=Decimal(at_mp), atMpSource="Urssaf decision",
            fnalClass="UNDER_50", cfpClass="OVER_11", effectif=36,
            effectiveFrom=date(2026, 1, 1)), actor_id=1)
    s.ingest_france_pas_rate(
        db, org_id, FrancePASRateUpsert(
            employeeId=emp.id, rateType="PERSONALIZED", ratePct=pas_pct,
            dgfipRateId="DGFIP-2026-0001", source="CRM",
            receivedDate=date(2026, 1, 10), effectiveFrom=pas_effective), actor_id=1)


def test_fr_service_profile_upsert_and_validation(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import EmployerFranceProfileUpsert
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
            siren="55210055400021", filingDueDateClass="M15"), actor_id=1)   # SIREN is 9 digits
    p = s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
        siren="552100554", legalName="ACME", filingDueDateClass="M15", readinessStatus="READY"), actor_id=1)
    assert p.siren == "552100554"
    assert p.filing_due_date_class == "M15"
    assert p.readiness_status == "READY"
    with pytest.raises(BadRequestException):
        s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
            siren="552100554", filingDueDateClass="M99"), actor_id=1)


def test_fr_service_effectif_threshold_history(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import EmployerFranceProfileUpsert, FranceEffectifRecord
    s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
        siren="552100554", filingDueDateClass="M15"), actor_id=1)
    s.record_france_effectif(db, 1, FranceEffectifRecord(year=2025, value=36, source="DSN"), actor_id=1)
    s.record_france_effectif(db, 1, FranceEffectifRecord(year=2026, value=49, source="DSN"), actor_id=1)
    p = s.get_employer_france_profile(db, 1)
    state = p.effectif_state
    assert state["2025"]["value"] == 36
    assert state["2026"]["value"] == 49
    assert state["2026"]["source"] == "DSN"


def test_fr_service_rate_pack_effective_dated_auto_close(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceEstablishmentRatePackUpsert
    from app.core.exceptions import BadRequestException

    p1 = s.upsert_france_establishment_rate_pack(db, 1, FranceEstablishmentRatePackUpsert(
        siret="55210055400021", atMpRatePct=Decimal("2.09"), atMpSource="S1",
        effectiveFrom=date(2026, 1, 1)), actor_id=1)
    p2 = s.upsert_france_establishment_rate_pack(db, 1, FranceEstablishmentRatePackUpsert(
        siret="55210055400021", atMpRatePct=Decimal("2.50"), atMpSource="S2",
        effectiveFrom=date(2026, 7, 1)), actor_id=1)
    assert p1.effective_to == date(2026, 6, 30)   # previous period auto-closed
    assert p2.at_mp_rate_pct == Decimal("2.50")
    assert len(s.list_france_establishment_rate_packs(db, 1)) == 2
    with pytest.raises(BadRequestException):
        s.upsert_france_establishment_rate_pack(db, 1, FranceEstablishmentRatePackUpsert(
            siret="55210055400021", atMpRatePct=Decimal("2.60"), atMpSource="S3",
            effectiveFrom=date(2026, 7, 1)), actor_id=1)   # same period → collision → BadRequest


def test_fr_service_pas_intake_guards_and_supersede(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FrancePASRateUpsert
    from app.core.exceptions import BadRequestException

    emp = _mk_employee(db, 1)
    # PERSONALIZED requires a percentage
    with pytest.raises(BadRequestException):
        s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
            employeeId=emp.id, rateType="PERSONALIZED", source="CRM",
            effectiveFrom=date(2026, 1, 1)), actor_id=1)
    # NEUTRAL forbids a percentage (engine resolves the statutory grid)
    with pytest.raises(BadRequestException):
        s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
            employeeId=emp.id, rateType="NEUTRAL", ratePct=Decimal("7.5"),
            source="NEUTRAL_GRID", effectiveFrom=date(2026, 1, 1)), actor_id=1)
    r1 = s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
        employeeId=emp.id, rateType="PERSONALIZED", ratePct=Decimal("10"),
        dgfipRateId="R1", source="CRM", effectiveFrom=date(2026, 1, 1)), actor_id=1)
    assert r1.status == "ACTIVE"
    r2 = s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
        employeeId=emp.id, rateType="PERSONALIZED", ratePct=Decimal("12"),
        dgfipRateId="R2", source="CRM", effectiveFrom=date(2026, 6, 1),
        correctionOfId=r1.id), actor_id=1)
    assert r1.status == "STALE"                          # superseded, never deleted
    assert r1.effective_to == date(2026, 5, 31)
    assert s.get_active_france_pas_rate(db, 1, emp.id, as_of=date(2026, 6, 30)).rate_pct == Decimal("12")
    # Fail-closed: a corrected/superseded rate is STALE forever — historical
    # lookups inside the old window return None, never the corrected-away row.
    assert s.get_active_france_pas_rate(db, 1, emp.id, as_of=date(2026, 3, 1)) is None
    # STALE rows stay on the ledger for audit (FR-008 lineage).
    assert {r.status for r in s.list_france_pas_rates(db, 1, emp.id)} == {"ACTIVE", "STALE"}


def test_fr_service_dsn_validated_and_due_date(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceDsnSubmissionCreate

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp, due_class="M15")
    dsn = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606"), actor_id=1)
    assert dsn.status == "VALIDATED"
    assert dsn.period_end == date(2026, 6, 30)
    assert dsn.due_date == date(2026, 7, 15)   # M15 → 15th of M+1
    assert dsn.validation_errors == []
    assert len(dsn.payload_hash) == 64

    # M5 class (50+ employees: 5th of M+1) on a second org
    emp5 = _mk_employee(db, 2, "E501")
    _configure_france(db, 2, emp5, due_class="M5")
    dsn_m5 = s.create_france_dsn_submission(db, 2, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606"), actor_id=1)
    assert dsn_m5.due_date == date(2026, 7, 5)


def test_fr_service_dsn_blocked_without_pas_coverage(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceDsnSubmissionCreate

    emp1 = _mk_employee(db, 1, "E001")
    _configure_france(db, 1, emp1)
    _mk_employee(db, 1, "E002")          # no PAS rate → FR-031 blocks
    dsn = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 7, 1), releaseRef="FR-202607"), actor_id=1)
    assert dsn.status == "DRAFT"
    assert any("no active PAS rate" in e for e in dsn.validation_errors)
    assert dsn.blocked_reason


def test_fr_service_dsn_lifecycle_state_machine(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceDsnSubmissionCreate, FranceDsnStatusUpdate
    from app.core.exceptions import BadRequestException

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp)
    dsn = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606"), actor_id=1)
    assert dsn.status == "VALIDATED"

    with pytest.raises(BadRequestException):
        s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(
            status="TRANSMITTED"), actor_id=1)   # VALIDATED can only → QUEUED

    s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="QUEUED"), actor_id=1)
    dsn = s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(
        status="TRANSMITTED", technicalAck="OK"), actor_id=1)
    dsn = s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(
        status="ACKNOWLEDGED", businessCrm={"anomalies": []}), actor_id=1)
    dsn = s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(
        status="SETTLED", paymentState="SEPA_OK"), actor_id=1)
    assert dsn.status == "SETTLED"
    assert dsn.technical_ack == "OK"                    # separate lifecycle columns
    assert dsn.business_crm == {"anomalies": []}
    assert dsn.payment_state == "SEPA_OK"
    assert dsn.acknowledged_at is not None


def test_fr_service_outbox_idempotency(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import (
        FranceDsnSubmissionCreate, FranceDsnOutboxCreate, FranceDsnStatusUpdate,
    )
    from app.core.exceptions import BadRequestException

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp)
    dsn = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606"), actor_id=1)

    with pytest.raises(BadRequestException):
        s.create_france_dsn_outbox_item(db, 1, FranceDsnOutboxCreate(
            submissionId=dsn.id, action="DELETE_IT"), actor_id=1)

    i1 = s.create_france_dsn_outbox_item(db, 1, FranceDsnOutboxCreate(
        submissionId=dsn.id, action="TRANSMIT", payload={"dsn": dsn.payload_hash}), actor_id=1)
    i2 = s.create_france_dsn_outbox_item(db, 1, FranceDsnOutboxCreate(
        submissionId=dsn.id, action="TRANSMIT", payload={"dsn": dsn.payload_hash}), actor_id=1)
    assert i1.id == i2.id                               # idempotent replay

    i3 = s.transition_france_dsn_outbox_item(db, 1, i1.id, "SENT", actor_id=1)
    assert i3.attempts == 1

    s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="QUEUED"), actor_id=1)
    outbox = s.list_france_dsn_outbox_items(db, 1)
    assert len(outbox) == 1
    assert outbox[0].submission_id == dsn.id


def test_fr_service_readiness_dry_run(db):
    from app.modules.payroll import service as s

    rd_before = s.get_france_readiness(db, 1)
    assert rd_before["ready"] is False
    assert rd_before["profileConfigured"] is False
    assert rd_before["readinessStatus"] == "NOT_READY"

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp)
    rd_after = s.get_france_readiness(db, 1)
    assert rd_after["ready"] is True
    assert rd_after["profileConfigured"] is True
    assert rd_after["readinessStatus"] == "READY"
    assert rd_after["effectiveRatePacks"] >= 1
    assert rd_after["effectifGoverned"] is True
    assert rd_after["missing"] == []


def test_fr_router_routes_registered():
    """The France endpoint surface exists on both routers (import-time
    smoke — full HTTP auth flow is covered by the platform's route tests)."""
    from app.modules.payroll.router import payroll_router
    from app.modules.super_admin.router import router as super_admin_router
    from fastapi.routing import APIRoute

    payroll_paths = {r.path for r in payroll_router.routes if isinstance(r, APIRoute)}
    admin_paths = {r.path for r in super_admin_router.routes if isinstance(r, APIRoute)}

    assert "/payroll/france/dsn-submissions" in payroll_paths
    assert "/payroll/france/dsn-submissions/{submission_id}/status" in payroll_paths
    assert "/payroll/france/dsn-outbox" in payroll_paths
    assert "/payroll/france/readiness" in payroll_paths

    assert "/super-admin/compliance/france/employer-profile" in admin_paths
    assert "/super-admin/compliance/france/effectif" in admin_paths
    assert "/super-admin/compliance/france/establishment-rate-packs" in admin_paths
    assert "/super-admin/compliance/france/pas-rates" in admin_paths
    assert "/super-admin/compliance/france/readiness" in admin_paths