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
from datetime import date, timedelta
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
from app.modules.payroll.engine.countries.france_content import (
    FR_2026_CONTENT, content_rows_in_force,
)


@dataclass
class Rate:
    """Minimal stand-in for a ContributionRate row — only the attributes
    the engine reads (same shape as test_engine_standard.py)."""
    component_key: str = ""
    employee_rate_pct: Decimal = None
    employer_rate_pct: Decimal = None
    flat_amount: Decimal = None


def fr_rate_map(as_of=date(2026, 6, 30)):
    """The France content catalog rows in force on `as_of` (row-level
    dating, e.g. the 1 June SMIC), shaped like ContributionRate rows — the
    exact rows scripts/seed_france_canonical_packs.py writes."""
    rows = {}
    for key, _label, _cat, kind, value, *_rest in content_rows_in_force(as_of).values():
        rows[key] = Rate(
            key,
            employee_rate_pct=value if kind == "ee" else None,
            employer_rate_pct=value if kind == "er" else None,
            flat_amount=value if kind == "amount" else None,
        )
    return rows


# ── 2026 France content (content-as-data map) ─────────────────────────
# A France calculation REQUIRES a configured rate_map row for every
# mandatory rate AND parameter (FR-027 fail-closed), so the golden vectors
# run on the shared content catalog, never on the hardcoded fallbacks.
FR_RATES = fr_rate_map()

FR_ESTABLISHMENT = dict(
    siret="55210055400021", at_mp_rate_pct="2.09", vm_rate_pct="2.80",
    fnal_class="0p10", cfp_class="0p55", effectif=36, commune_insee="75056",
)
FR_PAS = {"rate_type": "PERSONALIZED", "rate_pct": Decimal("10"), "rate_id": "DGFIP-2026-0001"}
# Five prior months at 3000: SMIC reference = 5 × (21876.64 / 12) frozen annual.
FR_YTD = dict(rgdu_remuneration="15000", rgdu_smic_reference="9115.27", rgdu_relief="1500",
              csg_gross="15000", periods=5)


def fr_result(gross=3000, *,
              cadre=True, pas=None, ytd=None, establishment=None,
              payroll_date=date(2026, 6, 30), rate_map=None, **ctx_kw):
    """Build a France PayrollContext through StandardStrategy."""
    ctx = PayrollContext(
        country="FR", gross=Decimal(str(gross)), basic=Decimal(str(gross)),
        rate_map=rate_map if rate_map is not None else fr_rate_map(payroll_date),
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
    assert r.net_pay == Decimal("2128.11")
    assert r.total_deductions == Decimal("871.89")
    assert r.fr_net_social == Decimal("2374.07")
    # net imposable = net social + CSG non-déductible 70.74 + CRDS 14.74 (FR-017)
    assert r.fr_net_imposable == Decimal("2459.55")
    assert r.fr_employee_total == Decimal("871.89")
    # 1377.78 before relief − 299.05 RGDU delta (YTD theoretical 1799.05 − 1500 granted)
    assert r.fr_employer_total == Decimal("1078.73")
    assert r.fr_pas_withheld == Decimal("245.96")
    assert r.fr_pas_rate_type == "PERSONALIZED"
    assert r.fr_pas_rate_pct == Decimal("10")


def test_fr_golden_net_identity_three_values_never_one_net():
    """FR-042: the three France nets reconcile. net à payer = net social -
    PAS = gross - fr_employee_total; net imposable = net social + CSGN + CRDS
    (both non-deductible levies return to the taxable base, FR-017)."""
    r = fr_result(3000)
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert r.fr_net_imposable == r.fr_net_social + contrib["CSGN"]["ee"] + contrib["CRDS"]["ee"]
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
    """Month 1, zero YTD: the SMIC reference is ONE month of the frozen
    annual SMIC (21876.64 / 12 = 1823.05), so at 3000 gross the coefficient
    is ~0.0999 — not the 0.3981 cap the old annual-SMIC-per-period bug hit."""
    r = fr_result(3000, ytd={}, payroll_date=date(2026, 1, 31))
    rgdu = r.fr_calculation_snapshot["rgdu"]
    assert rgdu["eligible"] is True
    assert rgdu["annual_smic_reference"] == Decimal("1823.05")
    assert rgdu["coefficient"].quantize(Decimal("0.0001")) == Decimal("0.0999")
    assert rgdu["theoretical_relief"] == Decimal("299.84")
    assert rgdu["monthly_delta"] == Decimal("299.84")
    # split on in-scope contributions: Agirc T1 + CEG T1 = 180.30 of 1185.60
    assert rgdu["relief_urssaf"] == Decimal("254.24")
    assert rgdu["relief_agirc"] == Decimal("45.60")
    assert r.fr_calculation_snapshot["employer_before_relief"] == Decimal("1377.78")
    assert r.fr_employer_total == Decimal("1377.78") - Decimal("299.84")


def test_fr_rgdu_already_granted_zero_delta():
    """YTD relief already exceeds theoretical → no double payment this period."""
    r = fr_result(3000, ytd={**FR_YTD, "rgdu_relief": "2000"})
    rgdu = r.fr_calculation_snapshot["rgdu"]
    assert rgdu["already_granted"] == Decimal("2000.00")
    assert rgdu["monthly_delta"] == Decimal("0.00")
    assert r.fr_employer_total == r.fr_calculation_snapshot["employer_before_relief"]


def test_fr_non_cadre_apec_zero():
    r = fr_result(3000, cadre=False)
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["APEC"]["ee"] == Decimal("0.00")
    assert contrib["APEC"]["er"] == Decimal("0.00")
    assert r.fr_employee_total == Decimal("871.24")
    assert r.fr_employer_total == Decimal("1077.65")
    assert r.net_pay == Decimal("2128.76")


def test_fr_under_11_reduced_sante():
    """FEWER than 11 employees → reduced salud rate up to 2.5x SMIC band."""
    est = {**FR_ESTABLISHMENT, "effectif": 8}
    r = fr_result(3000, establishment=est)
    contrib = {c["code"]: c for c in r.fr_contributions}
    # 13% → 7% band on full 3000 (< 4557.63 band ceiling)
    assert contrib["PB000"]["er"] == Decimal("210.00")
    assert r.fr_employer_total == Decimal("898.73")
    assert r.fr_employee_total == Decimal("871.89")  # employee side untouched


def test_fr_t2_cet_above_pss():
    """Gross above PSS → Agirc T2 + CEG T2 + CET all engage. 6000/month is
    above 3×SMIC, so RGDU is correctly NOT eligible (the old per-period
    annual-SMIC bug granted 2462.00 relief here)."""
    r = fr_result(6000, ytd=dict(rgdu_remuneration="30000", rgdu_smic_reference="9115.27",
                                 rgdu_relief="0", csg_gross="30000", periods=5))
    b = r.fr_bases
    assert b["agirc_t2"] == Decimal("1995.00")   # 6000 - 4005 PSS
    assert b["cet"] == Decimal("6000.00")        # T1 4005 + T2 1995
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["RE2B"]["ee"] > 0
    assert contrib["CET"]["ee"] == Decimal("8.40")   # 6000 x 0.14%
    assert r.fr_employee_total == Decimal("1729.97")
    assert r.fr_pas_withheld == Decimal("493.44")
    assert r.fr_calculation_snapshot["rgdu"]["eligible"] is False
    assert r.fr_employer_total == Decimal("2766.37")


def test_fr_csg_4x_pass_envelope_boundary():
    """CSG/CRDS: 98.25% factor within a CUMULATIVE 4×PSS ceiling (4 × 4005
    × periods elapsed, regularised against YTD gross), full base above."""
    # December (12th period): ceiling 4×4005×12 = 192240; 177240 already
    # consumed → 15000 still inside, 5000 above.
    r = fr_result(20000, ytd=dict(rgdu_remuneration="170000", rgdu_smic_reference="20053.59",
                                  rgdu_relief="0", csg_gross="177240", periods=11),
                  payroll_date=date(2026, 12, 31))
    assert r.fr_calculation_snapshot["csg_base"] == Decimal("19737.50")   # 15000×0.9825 + 5000
    assert r.fr_calculation_snapshot["csg_base_factor"] == Decimal("98.25")
    assert r.fr_bases["csg_crds"] == Decimal("19737.50")


def test_fr_neutral_short_contract_748_abatement():
    pas = {"rate_type": "NEUTRAL", "rate_pct": Decimal("7.5"), "grid_version": "GRID-2026-05",
           "short_contract": True}
    r = fr_result(2000, pas=pas)
    assert r.fr_pas_rate_type == "NEUTRAL"
    assert r.fr_net_imposable == Decimal("1639.70")
    assert r.fr_bases["pas"] == Decimal("891.70")   # 1639.70 - 748 abatement
    assert r.fr_pas_withheld == Decimal("66.88")
    assert r.net_pay == Decimal("1515.83")


def test_fr_apprentice_exemption():
    pas = {"rate_type": "NEUTRAL", "rate_pct": Decimal("7.5"), "grid_version": "GRID-2026-05",
           "apprentice": True}
    r = fr_result(2000, pas=pas)
    assert r.fr_pas_withheld == Decimal("0.00")
    assert r.net_pay == r.fr_net_social     # PAS fully exempt → net à payer = net social


def test_fr_apprentice_exemption_only_up_to_threshold():
    """Above the monthly threshold (21876 / 12 = 1823.00) only the EXCESS of
    net imposable is taxed — never all-or-nothing."""
    pas = {"rate_type": "NEUTRAL", "rate_pct": Decimal("7.5"), "grid_version": "GRID-2026-05",
           "apprentice": True}
    r = fr_result(2500, pas=pas)
    assert r.fr_net_imposable == Decimal("2049.62")
    assert r.fr_bases["pas"] == Decimal("226.62")
    assert r.fr_pas_withheld == Decimal("17.00")


# ── A2. Spec §19 fixtures + phase-4 regressions ─────────────────────────

def test_fr_csg_january_high_earner_capped_at_4_pss():
    """A January high earner gets the abatement on at most 4×PSS (16020),
    not on the whole remaining annual 4×PASS envelope."""
    r = fr_result(50000, ytd={}, payroll_date=date(2026, 1, 31))
    assert r.fr_bases["csg_crds"] == Decimal("49719.65")   # 16020×0.9825 + 33980


def test_fr_f1_pass_boundary():
    """F1: capped old-age and Agirc T1/T2 split exactly at the PMSS 4005."""
    at = fr_result(4005).fr_bases
    assert (at["vieillesse_capped"], at["agirc_t1"], at["agirc_t2"], at["cet"]) == (
        Decimal("4005.00"), Decimal("4005.00"), Decimal("0.00"), Decimal("0.00"))
    above = fr_result(4006).fr_bases
    assert (above["vieillesse_capped"], above["vieillesse_uncapped"], above["agirc_t2"], above["cet"]) == (
        Decimal("4005.00"), Decimal("4006.00"), Decimal("1.00"), Decimal("4006.00"))


def test_fr_f2_smic_transition_may_vs_june():
    """F2: May uses 12.02/1823.03, June 12.31/1867.02 — from dated pack rows."""
    may = fr_result(1850, payroll_date=date(2026, 5, 31))
    assert may.fr_calculation_snapshot["smic_monthly"] == Decimal("1823.03")
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(1850, payroll_date=date(2026, 6, 30))
    assert exc.value.code == "SMIC_MINIMUM_BREACH"


def test_fr_f5_high_salary_t2_cet_capped_at_8_pss():
    """F5-style: above 8 PSS the CET base stops at T1+T2 = 32040, Apec at 4 PSS."""
    b = fr_result(50000, ytd={}, payroll_date=date(2026, 1, 31)).fr_bases
    assert b["agirc_t2"] == Decimal("28035.00")
    assert b["cet"] == Decimal("32040.00")
    assert b["apec"] == Decimal("16020.00")


def test_fr_f6_fnal_50_plus_uses_total_pay_and_tdelta_0_3821():
    r = fr_result(3000, establishment={**FR_ESTABLISHMENT, "fnal_class": "OVER_50"})
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["FNAL"]["er"] == Decimal("15.00")         # 0.50% × 3000 total pay
    assert r.fr_calculation_snapshot["rgdu"]["tdelta"] == Decimal("0.3821")


def test_fr_admin_class_vocabulary_accepted():
    """The Super Admin form stores UNDER_50/OVER_50 and UNDER_11/OVER_11 —
    the engine must accept them (previously ESTABLISHMENT_INCOMPLETE)."""
    r = fr_result(3000, establishment={**FR_ESTABLISHMENT, "fnal_class": "UNDER_50", "cfp_class": "OVER_11"})
    assert r.fr_calculation_snapshot["fnal_class"] == "0p10"
    assert r.fr_calculation_snapshot["cfp_class"] == "1p00"
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["CFP"]["er"] == Decimal("30.00")          # 1.00% × 3000 total pay


def test_fr_cfp_on_total_pay_not_capped():
    r = fr_result(6000, ytd={})
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["CFP"]["base"] == Decimal("6000")
    assert contrib["CFP"]["er"] == Decimal("33.00")          # 0.55% × 6000


def test_fr_part_time_ceilings_prorated_consistently():
    b = fr_result(6000, france_working_hours=Decimal("75.835")).fr_bases
    assert b["vieillesse_capped"] == Decimal("2002.50")      # PSS × 0.5
    assert b["agirc_t2"] == Decimal("3997.50")               # within 8 × prorated PSS
    assert b["chomage_ags_4x_pass"] == Decimal("6000.00")


def test_fr_versement_mobilite_missing_rate_blocks_unless_not_due():
    est = {k: v for k, v in FR_ESTABLISHMENT.items() if k != "vm_rate_pct"}
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, establishment=est)
    assert exc.value.code == "MANDATORY_RATE_NOT_CONFIGURED"
    r = fr_result(3000, establishment={**est, "vm_threshold_applies": False})
    contrib = {c["code"]: c for c in r.fr_contributions}
    assert contrib["VMRR"]["er"] == Decimal("0")


def test_fr_ytd_after_rolls_forward():
    r = fr_result(3000)
    assert r.fr_ytd_after == {
        "rgdu_remuneration": Decimal("18000.00"),
        "rgdu_smic_reference": Decimal("10938.32"),
        "rgdu_relief": Decimal("1799.05"),
        "csg_gross": Decimal("18000.00"),
        "periods": 6,
    }


def test_fr_missing_parameter_row_blocks():
    """FR-003/FR-027: a statutory PARAMETER (not only a rate) missing from
    the pack blocks — the hardcoded constant never silently applies."""
    rates = dict(FR_RATES)
    del rates["fr_pmss"]
    with pytest.raises(FranceCalculationBlockedError) as exc:
        fr_result(3000, rate_map=rates)
    assert "fr_pmss" in exc.value.message


def test_fr_simple_mode_blocked():
    ctx = PayrollContext(
        country="FR", gross=Decimal("3000"), basic=Decimal("3000"), rate_map=FR_RATES,
        pay_date=date(2026, 6, 30), france_payroll_date=date(2026, 6, 30),
        france_establishment=FR_ESTABLISHMENT, france_pas=dict(FR_PAS), france_ytd=dict(FR_YTD),
    )
    with pytest.raises(FranceCalculationBlockedError) as exc:
        calculate_payroll(ctx, "simple")
    assert exc.value.code == "FRANCE_SIMPLE_MODE_UNSUPPORTED"


def test_fr_content_catalog_covers_every_engine_parameter():
    from app.modules.payroll.engine.countries.france import FR_PARAMETER_KEYS
    keys = {row[0] for row in FR_2026_CONTENT}
    assert set(FR_PARAMETER_KEYS) <= keys


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
    assert result.net_pay == Decimal("2128.11")


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


def _activate_france_packs(db):
    """Seed the FR-2026-H1/H2 canonical packs from the content catalog and
    activate them (gate G1 is a readiness check)."""
    from scripts.seed_france_canonical_packs import _ensure_pack, _seed_pack_rows
    from app.modules.payroll.engine.countries.france_content import FR_2026_H1, FR_2026_H2
    for code, start, end in (FR_2026_H1, FR_2026_H2):
        pack = _ensure_pack(db, code, start, end)
        _seed_pack_rows(db, pack, start, end)
        pack.status = "Active"
    db.commit()


def _configure_france(db, org_id, emp, siren="552100554", *,
                      due_class="M15", effectif_year=2025, effectif_value=36,
                      at_mp="2.09", pas_effective=date(2026, 1, 1), pas_pct=Decimal("10")):
    """A fully launch-ready France org: §11 panels A–E + PAS + active pack."""
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import (
        EmployerFranceProfileUpsert, FranceEffectifRecord, FranceEstablishmentUpsert,
        FranceEstablishmentRatePackUpsert, FrancePASRateUpsert,
    )
    s.upsert_employer_france_profile(
        db, org_id, EmployerFranceProfileUpsert(
            siren=siren, legalName="ACME SAS", legalForm="SAS", idcc="1596", idccStatus="APPLICABLE",
            urssafAccount="7500000000001", dsnDeclarant="ACME", paymentMandateRef="SEPA-FR-001",
            pasCollectorIdentity="DGFIP-COLLECTOR-001", filingDueDateClass=due_class), actor_id=1)
    s.record_france_effectif(db, org_id, FranceEffectifRecord(
        year=effectif_year, value=effectif_value, source="DSN"), actor_id=1)
    est = s.upsert_france_establishment(db, org_id, FranceEstablishmentUpsert(
        siret=siren + "00021", name="Paris HQ", communeInsee="75056"), actor_id=1)
    s.upsert_france_establishment_rate_pack(
        db, org_id, FranceEstablishmentRatePackUpsert(
            establishmentId=est.id, atMpRatePct=Decimal(at_mp), atMpSource="Urssaf decision",
            vmRatePct=Decimal("2.80"), vmSource="Urssaf VM table",
            fnalClass="UNDER_50", cfpClass="OVER_11", effectif=36,
            effectiveFrom=date(2026, 1, 1)), actor_id=1)
    s.ingest_france_pas_rate(
        db, org_id, FrancePASRateUpsert(
            employeeId=emp.id, rateType="PERSONALIZED", ratePct=pas_pct,
            dgfipRateId="DGFIP-2026-0001", crmReference="CRM-PAS-202512",
            receivedDate=pas_effective - timedelta(days=10), effectiveFrom=pas_effective), actor_id=1)
    _activate_france_packs(db)


def test_fr_service_profile_upsert_and_validation(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import EmployerFranceProfileUpsert
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
            siren="55210055400021", filingDueDateClass="M15"), actor_id=1)   # SIREN is 9 digits
    p = s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert.model_validate({
        "siren": "552100554", "legalName": "ACME", "filingDueDateClass": "M15",
        "readinessStatus": "LIVE", "effectifState": {"2026": {"value": 999}}}), actor_id=1)
    assert p.siren == "552100554"
    assert p.filing_due_date_class == "M15"
    # readiness and effectif can no longer be written through a profile save
    assert p.readiness_status == "NOT_READY"
    assert p.effectif_state is None
    with pytest.raises(BadRequestException):
        s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
            siren="552100554", idccStatus="APPLICABLE", filingDueDateClass="M15"), actor_id=1)  # needs the code
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


def test_fr_service_effectif_correction_keeps_history(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import (
        EmployerFranceProfileUpsert, FranceEffectifRecord, FranceEffectifCorrection,
    )
    from app.core.exceptions import BadRequestException

    s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
        siren="552100554", filingDueDateClass="M15"), actor_id=1)
    s.record_france_effectif(db, 1, FranceEffectifRecord(year=2025, value=36, source="DSN"), actor_id=1)
    with pytest.raises(BadRequestException):   # an existing year is corrected, never re-recorded
        s.record_france_effectif(db, 1, FranceEffectifRecord(year=2025, value=40, source="DSN"), actor_id=1)
    with pytest.raises(BadRequestException):   # a correction needs a reason
        s.correct_france_effectif(db, 1, FranceEffectifCorrection(
            year=2025, value=40, source="Urssaf", reason=" "), actor_id=1)
    p = s.correct_france_effectif(db, 1, FranceEffectifCorrection(
        year=2025, value=40, source="Urssaf notice", reason="Urssaf recount"), actor_id=7)
    year = p.effectif_state["2025"]
    assert year["value"] == 40 and year["source"] == "Urssaf notice"
    assert year["history"][0]["value"] == 36
    assert year["history"][0]["reason"] == "Urssaf recount"
    assert year["history"][0]["replacedBy"] == 7


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


def test_fr_service_rate_pack_future_edit_close_and_backdate(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import (
        FranceEstablishmentRatePackUpsert, FranceEstablishmentRatePackUpdate, FranceRatePackClose,
    )
    from app.core.exceptions import BadRequestException

    today = date.today()
    past = s.upsert_france_establishment_rate_pack(db, 1, FranceEstablishmentRatePackUpsert(
        siret="55210055400021", atMpRatePct=Decimal("2.09"), atMpSource="S1",
        effectiveFrom=today.replace(day=1) - timedelta(days=400)), actor_id=1)   # backdated: allowed
    future = s.upsert_france_establishment_rate_pack(db, 1, FranceEstablishmentRatePackUpsert(
        siret="55210055400021", atMpRatePct=Decimal("2.20"), atMpSource="S2",
        effectiveFrom=today + timedelta(days=30)), actor_id=1)
    edited = s.update_france_establishment_rate_pack(db, 1, future.id, FranceEstablishmentRatePackUpdate(
        atMpRatePct=Decimal("2.30"), fnalClass="OVER_50"), actor_id=1)
    assert edited.at_mp_rate_pct == Decimal("2.30") and edited.fnal_class == "OVER_50"
    with pytest.raises(BadRequestException):   # an in-force period is append-only
        s.update_france_establishment_rate_pack(db, 1, past.id, FranceEstablishmentRatePackUpdate(
            atMpRatePct=Decimal("9")), actor_id=1)
    with pytest.raises(BadRequestException):   # VM is authority data too
        s.update_france_establishment_rate_pack(db, 1, future.id, FranceEstablishmentRatePackUpdate(
            vmRatePct=Decimal("2.8")), actor_id=1)
    closed = s.close_france_establishment_rate_pack(db, 1, future.id, FranceRatePackClose(
        effectiveTo=today + timedelta(days=90)), actor_id=1)
    assert closed.effective_to == today + timedelta(days=90)
    with pytest.raises(BadRequestException):
        s.close_france_establishment_rate_pack(db, 1, future.id, FranceRatePackClose(
            effectiveTo=today + timedelta(days=95)), actor_id=1)


def test_fr_service_establishments_registry(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import EmployerFranceProfileUpsert, FranceEstablishmentUpsert
    from app.core.exceptions import BadRequestException

    s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
        siren="552100554", filingDueDateClass="M15"), actor_id=1)
    est = s.upsert_france_establishment(db, 1, FranceEstablishmentUpsert(
        siret="55210055400021", name="Paris", communeInsee="75056"), actor_id=1)
    corsica = s.upsert_france_establishment(db, 1, FranceEstablishmentUpsert(
        siret="55210055400039", name="Ajaccio", communeInsee="2a004"), actor_id=1)
    assert corsica.commune_insee == "2A004"
    with pytest.raises(BadRequestException):   # SIRET must extend the org's SIREN
        s.upsert_france_establishment(db, 1, FranceEstablishmentUpsert(siret="99999999900011"), actor_id=1)
    with pytest.raises(BadRequestException):   # duplicate SIRET
        s.upsert_france_establishment(db, 1, FranceEstablishmentUpsert(siret="55210055400021"), actor_id=1)
    with pytest.raises(BadRequestException):   # SIRET is immutable on update
        s.upsert_france_establishment(db, 1, FranceEstablishmentUpsert(siret="55210055400047"),
                                      establishment_id=est.id, actor_id=1)
    s.upsert_france_establishment(db, 1, FranceEstablishmentUpsert(
        siret="55210055400021", name="Paris", isActive=False), establishment_id=est.id, actor_id=1)
    assert [e.siret for e in s.list_france_establishments(db, 1, include_inactive=False)] == ["55210055400039"]


def test_fr_service_pas_intake_guards_and_supersede(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FrancePASRateUpsert
    from app.core.exceptions import BadRequestException

    emp = _mk_employee(db, 1)

    def personalized(pct, eff, received, **kw):
        return FrancePASRateUpsert(employeeId=emp.id, rateType="PERSONALIZED", ratePct=Decimal(pct),
                                   dgfipRateId=kw.pop("rate_id", "R1"), crmReference=kw.pop("crm", "CRM-1"),
                                   receivedDate=received, effectiveFrom=eff, **kw)

    # PERSONALIZED requires a percentage AND its DGFiP provenance (FR-008)
    with pytest.raises(BadRequestException):
        s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
            employeeId=emp.id, rateType="PERSONALIZED", effectiveFrom=date(2026, 1, 1)), actor_id=1)
    with pytest.raises(BadRequestException):
        s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
            employeeId=emp.id, rateType="PERSONALIZED", ratePct=Decimal("10"), dgfipRateId="R1",
            effectiveFrom=date(2026, 1, 1)), actor_id=1)                      # no CRM ref / receipt date
    with pytest.raises(BadRequestException):                                  # out of 0–100
        s.ingest_france_pas_rate(db, 1, personalized("120", date(2026, 1, 1), date(2025, 12, 20)), actor_id=1)
    with pytest.raises(BadRequestException):                                  # applied before receipt
        s.ingest_france_pas_rate(db, 1, personalized("10", date(2026, 1, 1), date(2026, 1, 10)), actor_id=1)
    with pytest.raises(BadRequestException):                                  # beyond the 60-day window
        s.ingest_france_pas_rate(db, 1, personalized("10", date(2026, 3, 1), date(2025, 12, 20)), actor_id=1)
    # NEUTRAL forbids a percentage (engine resolves the statutory grid)
    with pytest.raises(BadRequestException):
        s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
            employeeId=emp.id, rateType="NEUTRAL", ratePct=Decimal("7.5"),
            effectiveFrom=date(2026, 1, 1)), actor_id=1)

    r1 = s.ingest_france_pas_rate(db, 1, personalized("10", date(2026, 1, 1), date(2025, 12, 20)), actor_id=1)
    assert r1.source == "CRM" and r1.crm_reference == "CRM-1"
    r2 = s.ingest_france_pas_rate(db, 1, personalized("12", date(2026, 6, 1), date(2026, 5, 20),
                                                      rate_id="R2", crm="CRM-2"), actor_id=1)
    assert r1.status == "STALE"                          # superseded, never deleted
    assert r1.effective_to == date(2026, 5, 31)
    assert s.get_active_france_pas_rate(db, 1, emp.id, as_of=date(2026, 6, 30)).rate_pct == Decimal("12")
    # FR §4 correction rule: an old period re-run uses the rate that governed
    # it, never the newer personalized rate.
    assert s.get_active_france_pas_rate(db, 1, emp.id, as_of=date(2026, 3, 1)).id == r1.id

    # A correction replaces a wrong row; the corrected row never resolves again.
    r2b = s.ingest_france_pas_rate(db, 1, personalized("11.5", date(2026, 6, 1), date(2026, 5, 20),
                                                       rate_id="R2b", crm="CRM-2b", correctionOfId=r2.id), actor_id=1)
    assert r2.status == "CORRECTED"
    assert s.get_active_france_pas_rate(db, 1, emp.id, as_of=date(2026, 6, 30)).id == r2b.id
    assert {r.status for r in s.list_france_pas_rates(db, 1, emp.id)} == {"ACTIVE", "STALE", "CORRECTED"} or \
        {r.status for r in s.list_france_pas_rates(db, 1, emp.id)} == {"PENDING", "STALE", "CORRECTED"}


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


def test_fr_service_dsn_unknown_is_reconciled_never_replayed(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceDsnSubmissionCreate, FranceDsnStatusUpdate
    from app.core.exceptions import BadRequestException

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp)
    dsn = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606"), actor_id=1)
    s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="QUEUED"), actor_id=1)
    s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="UNKNOWN"), actor_id=1)
    for blind in ("QUEUED", "TRANSMITTED"):
        with pytest.raises(BadRequestException):
            s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status=blind), actor_id=1)
    with pytest.raises(BadRequestException):   # an authority state needs its evidence
        s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="ACKNOWLEDGED"), actor_id=1)
    dsn = s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(
        status="ACKNOWLEDGED", technicalAck="OK-RECONCILED"), actor_id=1)
    assert dsn.status == "ACKNOWLEDGED"


def test_fr_service_dsn_draft_revalidation_and_correction(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceDsnSubmissionCreate, FranceDsnStatusUpdate
    from app.core.exceptions import BadRequestException

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp)
    stray = _mk_employee(db, 1, "E002")                   # no PAS → DRAFT
    dsn = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606"), actor_id=1)
    assert dsn.status == "DRAFT"
    with pytest.raises(BadRequestException):   # DRAFT → VALIDATED re-runs FR-031, never a bypass
        s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="VALIDATED"), actor_id=1)
    from app.modules.payroll.schemas import FrancePASRateUpsert
    s.ingest_france_pas_rate(db, 1, FrancePASRateUpsert(
        employeeId=stray.id, rateType="NEUTRAL", effectiveFrom=date(2026, 1, 1)), actor_id=1)
    dsn = s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status="VALIDATED"), actor_id=1)
    assert dsn.status == "VALIDATED" and dsn.validation_errors == []

    with pytest.raises(BadRequestException):   # an unfiled submission is not "corrected"
        s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
            periodStart=date(2026, 6, 1), releaseRef="FR-202606", correctionOfId=dsn.id), actor_id=1)
    for status, kw in (("QUEUED", {}), ("TRANSMITTED", {"technicalAck": "OK"}),
                       ("BUSINESS_REJECTED", {"businessCrm": {"anomalies": ["S21.G00.40"]}})):
        s.transition_france_dsn_submission(db, 1, dsn.id, FranceDsnStatusUpdate(status=status, **kw), actor_id=1)
    fix = s.create_france_dsn_submission(db, 1, FranceDsnSubmissionCreate(
        periodStart=date(2026, 6, 1), releaseRef="FR-202606-C1", correctionOfId=dsn.id), actor_id=1)
    assert fix.correction_of_id == dsn.id
    db.refresh(dsn)
    assert dsn.status == "BUSINESS_REJECTED"          # the original stays immutable


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
    # A changed payload for the same action is still the SAME outbox row.
    i4 = s.create_france_dsn_outbox_item(db, 1, FranceDsnOutboxCreate(
        submissionId=dsn.id, action="TRANSMIT", payload={"dsn": "different"}), actor_id=1)
    assert i4.id == i1.id
    s.transition_france_dsn_outbox_item(db, 1, i1.id, "UNKNOWN", actor_id=1)
    with pytest.raises(BadRequestException):   # UNKNOWN is never re-sent blind
        s.transition_france_dsn_outbox_item(db, 1, i1.id, "SENT", actor_id=1)
    with pytest.raises(BadRequestException):   # FAILED needs the reconciliation result
        s.transition_france_dsn_outbox_item(db, 1, i1.id, "FAILED", actor_id=1)
    s.transition_france_dsn_outbox_item(db, 1, i1.id, "FAILED", last_error="Not received per net-entreprises", actor_id=1)
    assert s.transition_france_dsn_outbox_item(db, 1, i1.id, "SENT", actor_id=1).attempts == 2

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
    assert {c["section"] for c in rd_after["checks"]} >= {"A", "B", "C", "D", "E", "H"}
    assert all(c["ok"] for c in rd_after["checks"])


def test_fr_service_go_live_only_when_ready(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import EmployerFranceProfileUpsert, FranceGoLiveRequest
    from app.core.exceptions import BadRequestException

    s.upsert_employer_france_profile(db, 1, EmployerFranceProfileUpsert(
        siren="552100554", legalName="ACME", filingDueDateClass="M15"), actor_id=1)
    with pytest.raises(BadRequestException):
        s.set_france_live(db, 1, FranceGoLiveRequest(), actor_id=1)

    emp = _mk_employee(db, 2)
    _configure_france(db, 2, emp)
    rd = s.set_france_live(db, 2, FranceGoLiveRequest(evidence={"parallelRun": "G8-2026-05/06"}), actor_id=9)
    assert rd["readinessStatus"] == "LIVE"
    profile = s.get_employer_france_profile(db, 2)
    assert profile.readiness_evidence["parallelRun"] == "G8-2026-05/06"
    assert profile.readiness_evidence["wentLiveBy"] == 9


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
    assert "/super-admin/compliance/france/establishments" in admin_paths
    assert "/super-admin/compliance/france/establishments/{establishment_id}" in admin_paths
    assert "/super-admin/compliance/france/establishment-rate-packs/{pack_id}" in admin_paths
    assert "/super-admin/compliance/france/establishment-rate-packs/{pack_id}/close" in admin_paths
    assert "/super-admin/compliance/france/effectif/corrections" in admin_paths
    assert "/super-admin/compliance/france/go-live" in admin_paths

# ── E. Statutory content in the DB (Phase 1) + France-org guard (Phase 0) ─

def test_fr_seed_creates_draft_packs_insert_only(db):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack
    from scripts.seed_france_canonical_packs import _ensure_pack, _seed_pack_rows
    from app.modules.payroll.engine.countries.france_content import FR_2026_H1, FR_2026_H2

    for code, start, end in (FR_2026_H1, FR_2026_H2):
        pack = _ensure_pack(db, code, start, end)
        assert pack.status == "Draft" and pack.pack_type == "tax" and pack.currency == "EUR"
        assert _seed_pack_rows(db, pack, start, end) > 40
    db.commit()

    h1 = db.query(JurisdictionPack).filter_by(pack_id="FR-2026-H1").one()
    # H1 (Jan–Apr) never carries the from-June SMIC row; H2 carries both dated rows.
    h1_smic = {r.flat_amount for r in db.query(ContributionRate).filter_by(
        jurisdiction_pack_id=h1.id, component_key="fr_smic_hourly")}
    assert h1_smic == {Decimal("12.02")}

    # Super Admin edits a Draft row; a re-run must not overwrite or duplicate it.
    row = db.query(ContributionRate).filter_by(jurisdiction_pack_id=h1.id, component_key="fr_csa_er").one()
    row.employer_rate_pct = Decimal("0.3000")
    db.commit()
    assert _seed_pack_rows(db, h1, FR_2026_H1[1], FR_2026_H1[2]) == 0
    db.commit()
    rows = db.query(ContributionRate).filter_by(jurisdiction_pack_id=h1.id, component_key="fr_csa_er").all()
    assert len(rows) == 1 and rows[0].employer_rate_pct == Decimal("0.3000")


def test_fr_activated_pack_resolves_dated_smic_for_engine(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from scripts.seed_france_canonical_packs import _ensure_pack, _seed_pack_rows
    from app.modules.payroll.engine.countries.france_content import FR_2026_H2

    code, start, end = FR_2026_H2
    pack = _ensure_pack(db, code, start, end)
    _seed_pack_rows(db, pack, start, end)
    pack.status = "Active"
    db.commit()

    for as_of, expected in ((date(2026, 5, 31), Decimal("12.02")), (date(2026, 6, 30), Decimal("12.31"))):
        rates, _slabs, resolved = resolve_tax_configuration(db, "FR", payroll_date=as_of)
        assert resolved.id == pack.id
        rate_map = {r.component_key: r for r in rates}
        assert rate_map["fr_smic_hourly"].flat_amount == expected
        # the resolved rows run the engine end-to-end with no fallback
        r = fr_result(3000, rate_map=rate_map, payroll_date=as_of)
        assert r.fr_net_social == Decimal("2374.07")


def test_fr_require_france_organization(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service as s
    from app.core.exceptions import BadRequestException, NotFoundException

    fr = Organization(organization_name="ACME FR", organization_code="ACMEFR", country="France")
    us = Organization(organization_name="ACME US", organization_code="ACMEUS", country="United States")
    db.add_all([fr, us])
    db.commit()
    assert s.require_france_organization(db, fr.id).id == fr.id
    with pytest.raises(BadRequestException):
        s.require_france_organization(db, us.id)
    with pytest.raises(NotFoundException):
        s.require_france_organization(db, 999999)


def test_fr_rate_pack_rejects_unknown_class_vocabulary(db, organization):
    from app.modules.payroll import service as s
    from app.modules.payroll.schemas import FranceEstablishmentRatePackUpsert
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        s.upsert_france_establishment_rate_pack(db, organization.id, FranceEstablishmentRatePackUpsert(
            siret="55210055400021", atMpRatePct=Decimal("2.09"), atMpSource="Urssaf decision",
            fnalClass="0p10", cfpClass="UNDER_11", effectiveFrom=date(2026, 1, 1)))


# ── F. Engine wired to the France authority tables (Phase 5) ────────────

def test_fr_service_inputs_drive_a_real_calculation_and_ytd_rolls(db):
    """The engine runs from REAL records: SIRET pack + PAS rate + active
    pack rows → a France result; the next period reads YTD back from the
    frozen payslip snapshot."""
    from app.modules.payroll import service as s
    from app.modules.payroll.engine.resolver import build_context_from_employee
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll.models import PayrollRun, PayslipItem

    emp = _mk_employee(db, 1)
    emp.compliance_fields = {"siret": "55210055400021", "cadre": "true"}
    db.commit()
    _configure_france(db, 1, emp)

    def run_calc(pay_date, run_id=None):
        rates, slabs, _pack = resolve_tax_configuration(db, "FR", payroll_date=pay_date)
        inputs = s._resolve_france_calc_inputs(db, 1, emp, pay_date, exclude_run_id=run_id)
        ctx = build_context_from_employee(
            emp, gross=Decimal("3000"), basic=Decimal("3000"), country="FR",
            rate_map={r.component_key: r for r in rates}, slabs=slabs,
            pay_date=pay_date, france_inputs=inputs)
        return calculate_payroll(ctx), inputs

    jan, inputs = run_calc(date(2026, 1, 31))
    assert inputs["france_establishment"]["fnal_class"] == "UNDER_50"   # stored vocabulary, engine maps it
    assert inputs["france_pas"]["rate_id"] == "DGFIP-2026-0001"
    assert inputs["france_ytd"] == {}
    assert jan.fr_net_social == Decimal("2374.07")
    assert jan.fr_calculation_snapshot["cfp_class"] == "1p00"           # OVER_11 → 1.00%

    # Freeze January like a generated payslip does, then compute February.
    run = PayrollRun(organization_id=1, period_label="Jan 2026", period_start=date(2026, 1, 1),
                     period_end=date(2026, 1, 31), pay_date=date(2026, 1, 31))
    db.add(run)
    db.commit()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=1,
                       employee_name=emp.name, country_code="FR",
                       fr_calculation_snapshot=s._fr_payslip_snapshot(jan)))
    db.commit()
    feb, inputs = run_calc(date(2026, 2, 28))
    assert inputs["france_ytd"]["periods"] == 1
    assert inputs["france_ytd"]["rgdu_relief"] == str(jan.fr_ytd_after["rgdu_relief"])
    assert feb.fr_ytd_after["periods"] == 2
    assert feb.fr_ytd_after["rgdu_remuneration"] == Decimal("6000.00")


def test_fr_service_blocked_employee_becomes_france_blocked_exception(db):
    from app.modules.payroll import service as s
    from app.core.exceptions import GermanyCalculationBlockedException, FranceCalculationBlockedException

    emp = _mk_employee(db, 1)
    _configure_france(db, 1, emp)
    other = _mk_employee(db, 1, "E009")                          # no PAS rate
    inputs = s._resolve_france_calc_inputs(db, 1, other, date(2026, 6, 30))
    assert inputs["france_pas"] == {}
    ctx = PayrollContext(country="FR", gross=Decimal("3000"), basic=Decimal("3000"), rate_map=FR_RATES,
                         pay_date=date(2026, 6, 30), **inputs)
    with pytest.raises(FranceCalculationBlockedError) as exc:
        calculate_payroll(ctx)
    wrapped = s._france_blocked(exc.value)
    # the run loop's existing FAILED-payslip handler catches it unchanged
    assert isinstance(wrapped, GermanyCalculationBlockedException)
    assert isinstance(wrapped, FranceCalculationBlockedException)
    assert wrapped.error_code == "PAS_NOT_RESOLVED"


# ── G. Super Admin "Load 2026 statutory defaults" (fills an empty pack) ─

def _mk_pack(db, pack_id="FR-PAYROLL-2026", status="Draft", country="FR", pack_type="tax"):
    from app.modules.payroll.models import JurisdictionPack
    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=country, pack_type=pack_type, version="1.0",
                            status=status, effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
                            tax_year="2026-27", currency="EUR")
    db.add(pack)
    db.commit()
    return pack


def test_fr_load_statutory_defaults_fills_empty_pack_insert_only(db):
    """The real-world case: a full-year Draft FR-PAYROLL-2026 pack with zero
    rows. One load adds every catalog row (both dated SMIC rows included),
    a second load adds nothing, and an edited value survives."""
    from app.modules.payroll import service as s
    from app.modules.payroll.models import ContributionRate

    pack = _mk_pack(db)
    result = s.load_france_statutory_defaults(db, pack.id, actor_id=1)
    assert result["added"] == len(FR_2026_CONTENT) == 52
    assert set(result["pendingG1Keys"]) == {"fr_sante_er", "fr_sante_er_reduced", "fr_famille_er", "fr_csa_er"}
    smic = sorted(r.flat_amount for r in db.query(ContributionRate).filter_by(
        jurisdiction_pack_id=pack.id, component_key="fr_smic_hourly"))
    assert smic == [Decimal("12.02"), Decimal("12.31")]

    row = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id, component_key="fr_csa_er").one()
    row.employer_rate_pct = Decimal("0.3000")
    db.commit()
    again = s.load_france_statutory_defaults(db, pack.id, actor_id=1)
    assert again["added"] == 0
    db.refresh(row)
    assert row.employer_rate_pct == Decimal("0.3000")


def test_fr_loaded_pack_runs_the_engine_with_no_missing_value(db):
    from app.modules.payroll import service as s
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    pack = _mk_pack(db)
    s.load_france_statutory_defaults(db, pack.id, actor_id=1)
    pack.status = "Active"
    db.commit()
    for as_of, smic in ((date(2026, 5, 31), Decimal("1823.03")), (date(2026, 6, 30), Decimal("1867.02"))):
        rates, _slabs, resolved = resolve_tax_configuration(db, "FR", payroll_date=as_of)
        r = fr_result(3000, rate_map={x.component_key: x for x in rates}, payroll_date=as_of)
        assert r.fr_net_social == Decimal("2374.07")
        assert r.fr_calculation_snapshot["smic_monthly"] == smic


def test_fr_load_statutory_defaults_refuses_active_and_non_france_packs(db):
    from app.modules.payroll import service as s
    from app.core.exceptions import BadRequestException, NotFoundException

    with pytest.raises(BadRequestException):
        s.load_france_statutory_defaults(db, _mk_pack(db, "FR-LIVE", status="Active").id, actor_id=1)
    with pytest.raises(BadRequestException):
        s.load_france_statutory_defaults(db, _mk_pack(db, "DE-X", country="DE").id, actor_id=1)
    with pytest.raises(NotFoundException):
        s.load_france_statutory_defaults(db, 999999, actor_id=1)
