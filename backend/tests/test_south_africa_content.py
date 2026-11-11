"""Contract tests pinning south_africa_content.py to ZP-ZA-ENG-001.

These assert the values and rules the specification states (§2 bands,
rebates, credits, UIF/SDL/ETI, labour baselines, the evidence register and
fixtures F1–F4), so a content edit that contradicts the spec fails here
before it can reach a pack. The fixture cross-checks are hand arithmetic over
the CONTENT values — the certified engine arrives in Phase 3 and is pinned by
its own golden fixtures. "ZA" is South Africa ("SA" is Saudi Arabia).
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.modules.payroll.engine.countries import south_africa_content as content

TWO = Decimal("0.01")


def _scalar(key):
    return {row[0]: row for row in content.ZA_SCALAR_CONTENT}[key]


def _amount(key):
    return Decimal(_scalar(key)[4])


def _annual_tax(taxable: Decimal) -> Decimal:
    for lo, hi, rate, base, _label, _src in content.paye_bands():
        if hi is None or taxable <= hi:
            return base + (taxable - lo) * rate / 100
    raise AssertionError("no band")


# ── pack window and evidence register ───────────────────────────────────────
def test_pack_window_is_the_2027_tax_year():
    assert content.ZA_2027 == ("ZA-PAYROLL-2027", date(2026, 3, 1), date(2027, 2, 28))
    assert content.PACK_STATUS == "Draft"


def test_evidence_register_is_s1_to_s14_with_urls():
    assert content.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 15))
    assert set(content.SOURCE_URLS) == set(content.SOURCE_CODES)
    assert all(url.startswith("https://") for url in content.SOURCE_URLS.values())


def test_every_row_cites_a_real_evidence_code():
    codes = set(content.SOURCE_CODES)
    for row in content.ZA_SCALAR_CONTENT:
        assert row[6] in codes, row[0]
    for row in content.ZA_PAYE_BANDS:
        assert row[5] in codes, row[4]
    for row in content.ZA_ETI_BANDS:
        assert row[7] in codes, row[6]
    for row in content.ZA_EARNING_CLASSES:
        assert row[4] in codes, row[3]


# ── parameter catalog ───────────────────────────────────────────────────────
def test_every_parameter_is_seeded_exactly_once():
    keys = [row[0] for row in content.ZA_SCALAR_CONTENT]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(content.ZA_PARAMETER_KEYS)


def test_each_value_sits_in_the_slot_its_kind_names():
    slots = {"employee_pct": (2,), "employer_pct": (3,), "pct_pair": (2, 3), "amount": (4,), "text": (5,)}
    for row in content.ZA_SCALAR_CONTENT:
        filled = tuple(i for i in (2, 3, 4, 5) if row[i] is not None)
        if row[0] in content.ZA_EMPTY_BY_DESIGN:
            # Phase 9: the spec states no value — the row must stay EMPTY and pending.
            assert filled == () and row[7] is True, row[0]
            continue
        assert filled == slots[content.ZA_PARAMETER_KEYS[row[0]]], row[0]


def test_only_listed_rows_may_be_empty():
    empty = {row[0] for row in content.ZA_SCALAR_CONTENT if all(row[i] is None for i in (2, 3, 4, 5))}
    expected = set(content.ZA_EMPTY_BY_DESIGN)
    assert empty == expected


def test_values_fit_their_columns():
    for row in content.ZA_SCALAR_CONTENT:
        assert len(row[0]) <= 50, row[0]                      # component_key String(50)
        assert row[5] is None or len(row[5]) <= 50, row[0]    # text_value String(50)
    for rule in (content.ZA_PAYE_BAND_RULE, content.ZA_ETI_BAND_RULE, content.ZA_EARNING_CLASS_RULE):
        assert len(rule) <= 30
    for obligation, treatment, component, label, _src in content.ZA_EARNING_CLASSES:
        assert len(component) <= 30 and len(obligation) <= 20 and len(treatment) <= 20
        assert len(label) <= 150
    for row in content.ZA_PAYE_BANDS:
        assert len(row[4]) <= 150


def test_policy_choices_the_spec_leaves_open_are_pending_g1():
    for key in ("za_paye_tax_year_date_basis", "za_variable_remuneration_basis"):
        row = _scalar(key)
        assert row[5] == "PENDING_G1" and row[7] is True
        assert row[5] in content.DATE_BASES


def test_only_monthly_is_supported():
    assert _scalar("za_supported_pay_frequencies")[5] == "MONTHLY"
    assert content.PAY_FREQUENCIES_SUPPORTED == ("MONTHLY",)


# ── spec §2 values ──────────────────────────────────────────────────────────
def test_rebates_match_spec():
    assert _amount("za_rebate_primary") == 17820
    assert _amount("za_rebate_secondary") == 9765
    assert _amount("za_rebate_tertiary") == 3249
    assert _amount("za_rebate_secondary_age") == 65
    assert _amount("za_rebate_tertiary_age") == 75


def test_medical_tax_credits_match_spec():
    assert _amount("za_mtc_main_member") == 376
    assert _amount("za_mtc_first_dependant") == 376
    assert _amount("za_mtc_additional_dependant") == 254


def test_uif_sdl_retirement_match_spec():
    uif = _scalar("za_uif")
    assert (uif[2], uif[3]) == ("1.0000", "1.0000")
    assert _amount("za_uif_monthly_ceiling") == 17712
    assert _scalar("za_sdl")[3] == "1.0000" and _scalar("za_sdl")[2] is None   # employer only
    assert _amount("za_sdl_exemption_threshold") == 500000
    assert _scalar("za_retirement_deduction_pct")[2] == "27.5000"
    assert _amount("za_retirement_annual_cap") == 430000


def test_labour_baselines_are_dated():
    nmw = _scalar("za_nmw_hourly")
    assert Decimal(nmw[4]) == Decimal("30.23") and nmw[8] == date(2026, 3, 1)
    bcea = _scalar("za_bcea_earnings_threshold")
    assert Decimal(bcea[4]) == Decimal("269900.90") and bcea[8] == date(2026, 5, 1)
    # March–April 2026 has no BCEA row on purpose (prior value not in the spec).
    assert "za_bcea_earnings_threshold" not in content.content_rows_in_force(date(2026, 4, 30))
    assert "za_bcea_earnings_threshold" in content.content_rows_in_force(date(2026, 5, 1))


def test_brs_version_and_emp201_due_day():
    assert _scalar("za_brs_version")[5] == "25.3.0" and _scalar("za_brs_version")[7] is True
    assert _amount("za_emp201_due_day") == 7
    assert _scalar("za_emp201_non_business_day_rule")[5] == "PRECEDING_BUSINESS_DAY"


# ── PAYE bands (spec §2) ────────────────────────────────────────────────────
def test_paye_bands_match_the_2027_table():
    assert [(r[0], r[1], r[2], r[3]) for r in content.ZA_PAYE_BANDS] == [
        ("0", "245100", "18.0000", "0"),
        ("245100", "383100", "26.0000", "44118"),
        ("383100", "530200", "31.0000", "79998"),
        ("530200", "695800", "36.0000", "125599"),
        ("695800", "887000", "39.0000", "185215"),
        ("887000", "1878600", "41.0000", "259783"),
        ("1878600", None, "45.0000", "666339"),
    ]


def test_paye_bands_are_contiguous_and_bases_are_consistent():
    bands = content.paye_bands()
    for (lo, hi, rate, base, *_), (next_lo, _h, _r, next_base, *_n) in zip(bands, bands[1:]):
        assert hi == next_lo
        assert base + (hi - lo) * rate / 100 == next_base


@pytest.mark.parametrize("taxable, expected", [
    (Decimal("245100"), Decimal("44118")),
    (Decimal("600000"), Decimal("150727")),     # F1
    (Decimal("360000"), Decimal("73992")),      # F2
    (Decimal("1878600"), Decimal("666339")),
])
def test_annual_tax_cross_checks(taxable, expected):
    assert _annual_tax(taxable) == expected


# ── fixtures F1–F4 (spec §12), hand arithmetic over the content ─────────────
def test_f1_regular_monthly_salary_age_40():
    gross = Decimal("50000")
    paye = ((_annual_tax(gross * 12) - _amount("za_rebate_primary")) / 12).quantize(TWO, ROUND_HALF_UP)
    assert paye == Decimal("11075.58")
    uif = (min(gross, _amount("za_uif_monthly_ceiling")) * Decimal(_scalar("za_uif")[2]) / 100).quantize(TWO)
    assert uif == Decimal("177.12")
    assert (gross * Decimal(_scalar("za_sdl")[3]) / 100).quantize(TWO) == Decimal("500.00")
    assert gross - paye - uif == Decimal("38747.30")


def test_f2_age_68_with_one_medical_dependant():
    gross = Decimal("30000")
    rebates = _amount("za_rebate_primary") + _amount("za_rebate_secondary")
    assert rebates == Decimal("27585")
    before_mtc = ((_annual_tax(gross * 12) - rebates) / 12).quantize(TWO, ROUND_HALF_UP)
    assert before_mtc == Decimal("3867.25")
    mtc = _amount("za_mtc_main_member") + _amount("za_mtc_first_dependant")
    assert mtc == Decimal("752")
    paye = before_mtc - mtc
    assert paye == Decimal("3115.25")
    uif = Decimal("177.12")
    assert gross - paye - uif == Decimal("26707.63")


def _eti(period, remuneration):
    for formula, lo, hi, rate, flat, *_ in content.eti_bands(period):
        if lo <= remuneration < hi:
            if formula == "PCT":
                return remuneration * rate / 100
            if formula == "FLAT":
                return flat
            return flat - (remuneration - lo) * rate / 100
    return Decimal("0")


def test_f3_eti_first_twelve_months_r5000_is_r1500():
    assert _eti("FIRST_12", Decimal("5000")) == Decimal("1500")


@pytest.mark.parametrize("period, cap", [("FIRST_12", Decimal("1500")), ("SECOND_12", Decimal("750"))])
def test_eti_bands_are_contiguous_continuous_and_end_at_7500(period, cap):
    bands = content.eti_bands(period)
    assert [b[0] for b in bands] == ["PCT", "FLAT", "TAPER"]
    for (_f, _lo, hi, *_), (_f2, next_lo, *_n) in zip(bands, bands[1:]):
        assert hi == next_lo
    assert _eti(period, Decimal("2500")) == cap                      # PCT meets FLAT
    assert _eti(period, Decimal("2499.99")).quantize(TWO) <= cap
    assert _eti(period, Decimal("5500")) == cap                      # FLAT meets TAPER
    assert _eti(period, Decimal("7499.99")).quantize(TWO) >= 0
    assert _eti(period, Decimal("7500")) == 0                        # no band at R7,500


def test_second_twelve_months_is_half_the_first():
    for remuneration in ("1000", "2500", "5000", "6500"):
        r = Decimal(remuneration)
        assert _eti("SECOND_12", r) * 2 == _eti("FIRST_12", r)


def test_f4_fixed_travel_allowance_inclusion():
    allowance = Decimal("5000")
    assert allowance * Decimal(_scalar("za_travel_inclusion_default_pct")[2]) / 100 == Decimal("4000")
    assert allowance * Decimal(_scalar("za_travel_inclusion_business_pct")[2]) / 100 == Decimal("1000")
    paye = {c: t for (o, t, c, *_r) in content.ZA_EARNING_CLASSES if o == "PAYE"}
    assert paye["TRAVEL_FIXED"] == "TRAVEL_RULE"


# ── earning classification (spec §4) ───────────────────────────────────────
def test_every_obligation_classifies_every_component_exactly_once():
    pairs = [(o, c) for (o, _t, c, *_r) in content.ZA_EARNING_CLASSES]
    assert len(pairs) == len(set(pairs))
    assert set(pairs) == {(o, c) for o in content.OBLIGATIONS for c in content.ZA_COMPONENTS}


def test_treatments_are_known_and_salary_is_in_every_base():
    for obligation, treatment, component, *_ in content.ZA_EARNING_CLASSES:
        assert treatment in content.TREATMENTS
        if component == "SALARY":
            assert treatment == "INCLUDED", obligation


def test_unstated_treatments_block_rather_than_guess():
    stated = {("PAYE", c) for c in ("SALARY", "OVERTIME", "BONUS", "COMMISSION", "LEAVE_PAYOUT", "TRAVEL_FIXED")}
    for obligation, treatment, component, *_ in content.ZA_EARNING_CLASSES:
        if component != "SALARY" and (obligation, component) not in stated:
            assert treatment == "REVIEW", (obligation, component)


# ── seeding (in-memory SQLite via the `db` fixture) ─────────────────────────
def test_seed_writes_a_draft_pack_with_every_row(db):
    from app.modules.payroll import south_africa_service as svc
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab

    pack = svc.seed_south_africa_pack(db)
    assert (pack.pack_id, pack.version, pack.status) == ("ZA-PAYROLL-2027", "1.0", "Draft")
    assert (pack.jurisdiction_country, pack.pack_type, pack.currency) == ("ZA", "tax", "ZAR")
    assert (pack.effective_from, pack.effective_to) == (date(2026, 3, 1), date(2027, 2, 28))

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert {r.component_key for r in rates} == set(content.ZA_PARAMETER_KEYS)
    by_key = {r.component_key: r for r in rates}
    assert by_key["za_uif_monthly_ceiling"].flat_amount == Decimal("17712")
    assert by_key["za_uif"].employee_rate_pct == Decimal("1") and by_key["za_uif"].employer_rate_pct == Decimal("1")
    assert by_key["za_brs_version"].text_value == "25.3.0"
    assert by_key["za_brs_version"].label.endswith("[PENDING G1]")
    assert by_key["za_bcea_earnings_threshold"].effective_from == date(2026, 5, 1)

    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).all()
    by_rule = {}
    for s in slabs:
        by_rule.setdefault(s.rule_type, []).append(s)
    assert len(by_rule["ZA_PAYE_BAND"]) == 7
    assert len(by_rule["ZA_ETI_BAND"]) == 6
    assert len(by_rule["ZA_EARNING_CLASS"]) == len(content.ZA_EARNING_CLASSES)
    assert all(s.tax_table_number is None for s in by_rule["ZA_EARNING_CLASS"])   # no guessed IRP5 code
    top = max(by_rule["ZA_PAYE_BAND"], key=lambda s: s.min_amount)
    assert top.max_amount is None and top.flat_amount == Decimal("666339")

    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-ZA-ENG-001 S%")).count() == 14


def test_reseed_is_idempotent_and_refuses_a_pack_that_left_draft(db):
    from app.modules.payroll import south_africa_service as svc
    from app.modules.payroll.models import ContributionRate, SourceArtifact

    pack = svc.seed_south_africa_pack(db)
    first = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
    again = svc.seed_south_africa_pack(db)
    assert again.id == pack.id
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count() == first
    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-ZA-ENG-001 S%")).count() == 14

    pack.status = "Active"
    db.flush()
    with pytest.raises(ValueError, match="not Draft"):
        svc.seed_south_africa_pack(db)


def test_seed_only_writes_draft(db):
    from app.modules.payroll import south_africa_service as svc

    with pytest.raises(ValueError, match="only writes Draft"):
        svc.seed_south_africa_pack(db, status="Active")
