"""South Africa ETI (ZP-ZA-ENG-001) — the pure incentive arithmetic and the
per-employee-per-month ledger, "ZA" is South Africa.

The engine vectors (tests/fixtures/za_golden/eti_*) prove the wiring end to end;
these tests pin the checks the golden fields cannot express (status, reasons,
NMW, band edges, normalisation) and the ledger governance (one live row per
month, reversal plus replacement, a stable content hash).
"""
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.engine.countries import south_africa as za
from app.modules.payroll.engine.countries import south_africa_content as content
from app.modules.payroll.engine.countries import south_africa_eti as eti
from app.modules.payroll.models import PayrollEmployee, PayrollZaEtiLedgerEntry

TWO = Decimal("0.01")


def _rnd(value):
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def _pack(*, nmw=None):
    rows = {}
    for key, _label, ee, er, flat, text, _src, _pending, _from, _to in content.ZA_SCALAR_CONTENT:
        rows[key] = SimpleNamespace(
            flat_amount=None if flat is None else Decimal(str(flat)),
            text_value=text,
            employee_rate_pct=None if ee is None else Decimal(str(ee)),
            employer_rate_pct=None if er is None else Decimal(str(er)),
        )
    if nmw is not None:
        rows["za_nmw_hourly"] = SimpleNamespace(flat_amount=Decimal(str(nmw)), text_value=None,
                                               employee_rate_pct=None, employer_rate_pct=None)
    return za._Pack(rows, None)


def _slabs():
    return [SimpleNamespace(rule_type=content.ZA_ETI_BAND_RULE, filing_status=period,
                            tax_regime=formula, min_amount=Decimal(lo), max_amount=Decimal(hi),
                            rate_pct=None if rate is None else Decimal(rate),
                            flat_amount=None if flat is None else Decimal(flat))
            for period, formula, lo, hi, rate, flat, _l, _s in content.ZA_ETI_BANDS]


def _eti(**overrides):
    args = dict(claim_month_end=date(2026, 9, 30), date_of_birth=date(2000, 1, 1),
                hire_date=date(2026, 1, 15), eligible_flag=True, employer_registered=True,
                paid_hours=Decimal("160"), remuneration=Decimal("5000"), qualifying_month_no=1,
                pack=_pack(), slabs=_slabs(), rnd=_rnd)
    args.update(overrides)
    return eti.compute_eti(**args)


# ── bands and periods ───────────────────────────────────────────────────────
def test_f3_first_twelve_months_r5000_is_r1500():
    out = _eti()
    assert out["status"] == eti.ELIGIBLE
    assert out["period"] == "FIRST_12"
    assert out["band"]["formula"] == "FLAT"
    assert out["amount"] == Decimal("1500.00")


def test_second_twelve_months_r5000_is_r750():
    out = _eti(qualifying_month_no=13)
    assert out["period"] == "SECOND_12"
    assert out["amount"] == Decimal("750.00")


def test_pct_band_isolates_the_percentage_arithmetic():
    out = _eti(remuneration=Decimal("2000"), pack=_pack(nmw="12.50"))
    assert out["band"]["formula"] == "PCT"
    assert out["amount"] == Decimal("1200.00")


@pytest.mark.parametrize("remuneration, period, expected", [
    ("2499.99", 1, "1499.99"), ("2500", 1, "1500.00"),
    ("5499.99", 1, "1500.00"), ("5500", 1, "1500.00"),
    ("7499.99", 1, "0.01"), ("7500", 1, "0.00"),
    ("2499.99", 13, "750.00"), ("2500", 13, "750.00"),
    ("5499.99", 13, "750.00"), ("5500", 13, "750.00"),
    ("7499.99", 13, "0.00"), ("7500", 13, "0.00"),
])
def test_band_edges(remuneration, period, expected):
    # NMW 0 isolates the band arithmetic: at the real R30.23 most of these low
    # remunerations would be INELIGIBLE before reaching a band (see below).
    out = _eti(remuneration=Decimal(remuneration), qualifying_month_no=period, pack=_pack(nmw="0"))
    assert out["status"] == eti.ELIGIBLE
    assert out["amount"] == Decimal(expected)


def test_r7500_is_eligible_with_zero_and_no_band():
    out = _eti(remuneration=Decimal("7500"), pack=_pack(nmw="0"))
    assert out["status"] == eti.ELIGIBLE
    assert out["amount"] == Decimal("0.00")
    assert out["band"] is None


def test_hours_are_normalised_then_the_amount_is_un_normalised():
    out = _eti(remuneration=Decimal("4000"), paid_hours=Decimal("120"))
    assert out["normalisedRemuneration"] == str(Decimal("4000") * 160 / 120)
    assert out["amount"] == Decimal("1125.00")


# ── eligibility checks ──────────────────────────────────────────────────────
def test_below_the_national_minimum_wage_is_ineligible():
    out = _eti(remuneration=Decimal("2000"))
    assert out["status"] == eti.INELIGIBLE
    assert out["amount"] == Decimal("0.00")
    assert "minimum wage" in out["reasons"][0]


@pytest.mark.parametrize("born, expected_status", [
    ("2009-01-01", eti.INELIGIBLE),  # 17
    ("2008-01-01", eti.ELIGIBLE),    # 18
    ("1997-01-01", eti.ELIGIBLE),    # 29
    ("1996-01-01", eti.INELIGIBLE),  # 30
])
def test_age_window(born, expected_status):
    out = _eti(date_of_birth=date.fromisoformat(born))
    assert out["status"] == expected_status


def test_qualifying_month_beyond_the_maximum_is_ineligible():
    out = _eti(qualifying_month_no=25)
    assert out["status"] == eti.INELIGIBLE


def test_not_registered_employer_is_not_registered():
    out = _eti(employer_registered=False)
    assert out["status"] == eti.NOT_REGISTERED
    assert out["amount"] == Decimal("0.00")


def test_unknown_registration_status_blocks():
    out = _eti(employer_registered=None)
    assert out["status"] == eti.BLOCKED


def test_missing_eligibility_evidence_blocks():
    out = _eti(eligible_flag=None)
    assert out["status"] == eti.BLOCKED


def test_missing_fact_blocks():
    out = _eti(hire_date=None)
    assert out["status"] == eti.BLOCKED
    assert "hire date" in out["reasons"][0]


def test_zero_paid_hours_blocks_instead_of_dividing_by_zero():
    out = _eti(paid_hours=Decimal("0"))
    assert out["status"] == eti.BLOCKED
    assert "greater than zero" in out["reasons"][0]


def test_missing_band_configuration_blocks():
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        _eti(slabs=[])
    assert exc.value.key == "za_eti_band"


def test_ambiguous_band_configuration_blocks():
    slabs = _slabs() + [SimpleNamespace(rule_type=content.ZA_ETI_BAND_RULE, filing_status="FIRST_12",
                                       tax_regime="FLAT", min_amount=Decimal("0"),
                                       max_amount=Decimal("7500"), rate_pct=Decimal("0"),
                                       flat_amount=Decimal("1"))]
    with pytest.raises(za.ZACalculationBlockedError) as exc:
        _eti(slabs=slabs)
    assert exc.value.key == "za_eti_band"


def test_eti_result_is_json_safe_apart_from_the_decimal_amount():
    out = _eti()
    encoded = json.loads(json.dumps(out, default=str))
    assert encoded["status"] == "ELIGIBLE" and encoded["band"]["formula"] == "FLAT"
    assert encoded["reasons"] == []


# ── ledger (ZA-010) ─────────────────────────────────────────────────────────
def _employee(db, organization, *, code="ZA-ETI-1"):
    employee = PayrollEmployee(organization_id=organization.id, employee_code=code,
                               name=f"Employee {code}", date_of_joining=date(2026, 1, 15),
                               basic=Decimal("5000"), country_code="ZA")
    db.add(employee)
    db.flush()
    return employee


def _result(**overrides):
    result = {"status": "ELIGIBLE", "reasons": [], "qualifyingMonthNo": 1,
              "period": "FIRST_12", "paidHours": "160", "remuneration": "5000",
              "normalisedRemuneration": "5000", "band": {"period": "FIRST_12", "formula": "FLAT"},
              "amount": "1500.00"}
    result.update(overrides)
    return result


def test_next_month_starts_at_one(db, organization):
    employee = _employee(db, organization)
    assert svc.za_next_eti_month_no(db, employee.id, date(2026, 9, 30)) == 1


def test_record_then_the_same_month_is_refused(db, organization):
    employee = _employee(db, organization)
    row = svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                                  claim_month=date(2026, 9, 30), eti_result=_result(), actor_id=1)
    assert row.status == "CALCULATED" and row.claim_month == date(2026, 9, 1)
    assert len(row.content_hash) == 64

    with pytest.raises(Exception) as exc:
        svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                                claim_month=date(2026, 9, 15), eti_result=_result())
    assert "already recorded" in str(exc.value)


def test_next_month_counts_prior_live_rows(db, organization):
    employee = _employee(db, organization)
    svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                            claim_month=date(2026, 9, 30), eti_result=_result())
    assert svc.za_next_eti_month_no(db, employee.id, date(2026, 10, 31)) == 2


def test_reversal_keeps_the_row_and_frees_the_month(db, organization):
    employee = _employee(db, organization)
    original = svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                                       claim_month=date(2026, 9, 30), eti_result=_result(), actor_id=1)
    original_hash = original.content_hash
    svc.reverse_za_eti_entry(db, original.id, actor_id=2)
    assert original.status == "REVERSED" and original.content_hash == original_hash
    assert svc.za_next_eti_month_no(db, employee.id, date(2026, 9, 30)) == 1

    replacement = svc.record_za_eti_entry(
        db, organization_id=organization.id, employee_id=employee.id, claim_month=date(2026, 9, 30),
        eti_result=_result(), actor_id=1, reverses_id=original.id)
    assert replacement.reverses_id == original.id
    assert replacement.content_hash == original_hash


def test_content_hash_is_stable_for_the_same_result(db, organization):
    employee = _employee(db, organization)
    svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                            claim_month=date(2026, 9, 30), eti_result=_result())
    assert svc._content_hash(_result()) == svc._content_hash(dict(reversed(list(_result().items()))))


def test_non_eligible_results_are_never_recorded(db, organization):
    employee = _employee(db, organization)
    for status in ("INELIGIBLE", "NOT_REGISTERED", "BLOCKED"):
        with pytest.raises(Exception):
            svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                                    claim_month=date(2026, 9, 30), eti_result=_result(status=status))


def test_ledger_refuses_an_employee_outside_the_organisation(db, organization):
    employee = _employee(db, organization)
    with pytest.raises(Exception):
        svc.record_za_eti_entry(db, organization_id=999999, employee_id=employee.id,
                                claim_month=date(2026, 9, 30), eti_result=_result())


def test_ledger_refuses_a_result_missing_figures(db, organization):
    employee = _employee(db, organization)
    with pytest.raises(Exception):
        svc.record_za_eti_entry(db, organization_id=organization.id, employee_id=employee.id,
                                claim_month=date(2026, 9, 30),
                                eti_result=_result(paidHours=None))


def test_reversing_an_unknown_entry_raises(db):
    with pytest.raises(Exception):
        svc.reverse_za_eti_entry(db, 999999)
