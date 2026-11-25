"""Germany Super Admin page, read-only views (payroll/germany_overview.py).

Every value these views return is read from data rows or from the engine's
own constants; the tests compare against those sources, never against typed
figures. Nothing is written. SYNTHETIC data only."""
from datetime import date
from decimal import Decimal

from app.modules.payroll import germany_overview as g
from app.modules.payroll import hardcoded_defaults
from app.modules.payroll.engine.jurisdictions.germany import tax
from app.modules.payroll.models import ContributionRate, GermanyHealthFund, JurisdictionPack


def _pack(db, pack_id="DE-PAYROLL-SYNTH", start=date(2026, 1, 1), end=date(2026, 12, 31)):
    pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country="DE", pack_type="tax",
                            status="Draft", effective_from=start, effective_to=end, tax_year=str(start.year))
    db.add(pack)
    db.commit()
    return pack


def _fund(db, code, *, pack=None, start=date(2026, 1, 1), end=None, status="DRAFT"):
    fund = GermanyHealthFund(health_fund_id=code, fund_name=f"SYNTHETIC {code}", supplementary_rate_pct=Decimal("1.1"),
                             effective_from=start, effective_to=end, status=status,
                             jurisdiction_pack_id=pack.id if pack else None)
    db.add(fund)
    db.commit()
    return fund


def _rows(view):
    return [r for s in view["sections"] for r in s["rows"]]


def test_engine_rows_read_the_constants_themselves(db):
    view = g.germany_contribution_rows(db, _pack(db))
    engine = {r["componentKey"]: r for r in _rows(view) if r["origin"] == "engine"}
    assert engine["rv_pension"]["employeeRatePct"] == str(hardcoded_defaults._DE_RV_EMPLOYEE_RATE)
    assert engine["rv_pension"]["employerRatePct"] == str(hardcoded_defaults._DE_RV_EMPLOYER_RATE)
    assert engine["gkv_general"]["employeeRatePct"] == str(hardcoded_defaults._DE_GKV_GENERAL_EMPLOYEE_RATE)
    assert engine["minijob_upper_threshold"]["flatAmount"] == str(hardcoded_defaults._DE_MINIJOB_UPPER_THRESHOLD)
    assert engine["midijob_total_base_multiplier"]["factor"] == str(hardcoded_defaults._DE_MIDIJOB_TOTAL_BASE_MULTIPLIER)
    for row in engine.values():
        assert row["status"] == g.ENGINE_STATUS and row["sourceFile"] == g.ENGINE_DEFAULTS_FILE
    # every constant listed exists in hardcoded_defaults (no typed value anywhere)
    for _sec, _key, _label, *names, _override, _note in g._ENGINE_CONSTANTS:
        for name in names:
            assert name is None or hasattr(hardcoded_defaults, name), name


def test_registry_rows_linked_or_overlapping_unlinked_only(db):
    pack = _pack(db)
    other = _pack(db, "DE-PAYROLL-OTHER", date(2027, 1, 1), date(2027, 12, 31))
    _fund(db, "LINKED", pack=pack)
    _fund(db, "UNLINKED_IN_WINDOW")
    _fund(db, "UNLINKED_OUTSIDE", start=date(2024, 1, 1), end=date(2024, 12, 31))
    _fund(db, "OTHER_PACK", pack=other)
    _fund(db, "SUPERSEDED", pack=pack, status="SUPERSEDED")
    health = {r["componentKey"]: r for r in _rows(g.germany_contribution_rows(db, pack)) if r["origin"] == "data"}
    assert set(health) == {"LINKED", "UNLINKED_IN_WINDOW"}
    assert health["LINKED"]["linkedToPack"] is True and health["UNLINKED_IN_WINDOW"]["linkedToPack"] is False
    assert Decimal(health["LINKED"]["totalRatePct"]) == Decimal("1.1")


def test_a_pack_rate_row_marks_the_engine_fallback_overridden(db):
    pack = _pack(db)
    db.add(ContributionRate(jurisdiction_pack_id=pack.id, component_key="rv_pension", label="SYNTHETIC RV", employee_share=0.0, employer_share=0.0, total=0.0,
                            jurisdiction_country="DE", effective_from=date(2026, 1, 1)))
    db.commit()
    engine = {r["componentKey"]: r for r in _rows(g.germany_contribution_rows(db, pack)) if r["origin"] == "engine"}
    assert engine["rv_pension"]["overriddenBy"] == "pack row rv_pension"
    assert engine["alv_unemployment"]["overriddenBy"] is None


def test_views_write_nothing(db):
    pack = _pack(db)
    _fund(db, "LINKED", pack=pack)
    g.germany_contribution_rows(db, pack)
    g.germany_wage_tax_tariff()
    assert not (db.new or db.dirty or db.deleted)


def test_tariff_zones_are_read_from_tax_py():
    view = g.germany_wage_tax_tariff(today=date(2026, 6, 1))
    assert view["certified"] is False and view["warning"] == g.UNCERTIFIED_TARIFF_WARNING
    assert len(view["versions"]) == len(tax._TARIFF_VERSIONS)
    for shown, source in zip(view["versions"], tax._TARIFF_VERSIONS):
        zones = shown["zones"]
        assert zones[0]["maxAmount"] == str(source["grundfreibetrag"])
        assert (zones[1]["minAmount"], zones[1]["maxAmount"]) == (str(source["grundfreibetrag"]), str(source["zone2_upper"]))
        assert (zones[2]["maxAmount"], zones[3]["maxAmount"]) == (str(source["zone3_upper"]), str(source["zone4_upper"]))
        assert zones[3]["ratePct"] == str(source["zone4_rate"] * 100)
        assert zones[4]["ratePct"] == str(source["zone5_rate"] * 100) and zones[4]["maxAmount"] is None
        assert str(source["zone2_a"]) in zones[1]["formula"] and str(source["zone5_sub"]) in zones[4]["formula"]
        assert shown["source"] == source["source"]
    assert [v["inForceToday"] for v in view["versions"]].count(True) == 1


def test_soli_engine_parameters_are_the_constants():
    params = {p["key"]: p for p in g.germany_wage_tax_tariff()["engineParameters"]}
    assert params["_DE_SOLI_RATE"]["value"] == str(hardcoded_defaults._DE_SOLI_RATE)
    assert params["SOLI_MILDERUNGSZONE_RATE"]["value"] == str(tax.SOLI_MILDERUNGSZONE_RATE)


def _applies(view):
    return [v["taxYear"] for v in view["versions"] if v["appliesToPack"]]


def test_the_tariff_marked_for_a_pack_is_the_one_the_engine_resolves(db):
    from decimal import Decimal as D

    for year in (2026, 2025, 2024):
        pack = _pack(db, f"DE-PAYROLL-T{year}", date(year, 1, 1), date(year, 12, 31))
        view = g.germany_wage_tax_tariff(pack=pack)
        engine = tax.InternalGermanyWageTaxCalculator(soli_threshold_single=D(0), soli_rate_pct=D(0),
                                                      payroll_date=date(year, 6, 30))
        assert _applies(view) == [engine._tariff["tax_year"]], year
        assert view["pack"]["appliesTaxYear"] == engine._tariff["tax_year"]


def test_other_tariffs_are_marked_not_used_and_earlier_ones_historical(db):
    view = g.germany_wage_tax_tariff(pack=_pack(db, "DE-PAYROLL-T2026", date(2026, 1, 1), date(2026, 12, 31)))
    by_year = {v["taxYear"]: v for v in view["versions"]}
    current = next(v for v in view["versions"] if v["appliesToPack"])
    for v in view["versions"]:
        if v is not current:
            assert v["appliesToPack"] is False
            assert v["endsBeforePack"] is (v["effectiveToExclusive"] is not None
                                           and v["effectiveToExclusive"] <= current["effectiveFrom"])
    assert len(by_year) == len(tax._TARIFF_VERSIONS)


def test_a_pack_before_every_tariff_has_none_and_says_why(db):
    first = tax._TARIFF_VERSIONS[0]["effective_from"]
    pack = _pack(db, "DE-PAYROLL-EARLY", date(first.year - 1, 1, 1), date(first.year - 1, 12, 31))
    view = g.germany_wage_tax_tariff(pack=pack)
    assert _applies(view) == [] and view["pack"]["appliesTaxYear"] is None
    assert view["pack"]["note"]


def test_without_a_pack_nothing_is_marked_and_the_stale_constant_is_named_as_such():
    view = g.germany_wage_tax_tariff()
    assert all(v["appliesToPack"] is None for v in view["versions"]) and view["pack"] is None
    assert view["provenanceConstant"] == tax.PROVENANCE_VERSION
