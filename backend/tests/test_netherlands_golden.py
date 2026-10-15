"""
tests/test_netherlands_golden.py
--------------------------------
Golden-vector harness for the Netherlands engine (ZP-NL-ENG-001 §18, NL-054).

Every fixture in tests/fixtures/nl_golden/ records its inputs, the expected
outputs, unrounded intermediates (VCR cumulative state, minimum-wage hourly
rate, wage bases) and — for F1/F2 — the expected loonaangifte line and totals.
Expected figures come from the spec and the hand calculations written in each
fixture's `source.formulas`; they are never copied from the engine.

All current fixtures are PROVISIONAL: the wage-tax row is SYNTHETIC (the spec's
published F1 result) because the official 2026 tables are gate G1. An
OFFICIAL fixture must name the official table file and its sha256 and an
independent reviewer — enforced below so a provisional vector can never be
mistaken for a certified one.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.test_netherlands_engine import LOW_CONTRACT, _nl
from tests.test_netherlands_loonaangifte import _run_and_approve, nlx  # noqa: F401

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "nl_golden"
FIXTURES = sorted(GOLDEN_DIR.glob("*.json"))
CONTRACTS = {"LOW": LOW_CONTRACT, "FIXED": {**LOW_CONTRACT, "contract_term": "FIXED"}}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _expat(decision):
    if decision is None:
        return None
    out = dict(decision)
    for key in ("granted_from", "granted_to"):
        out[key] = date.fromisoformat(out[key]) if out.get(key) else None
    out["allowance_pct"] = Decimal(out["allowance_pct"])
    return out


def _calculate(inputs, vcr_before):
    gross = Decimal(inputs["gross"])
    return _nl(gross=gross, basic=gross, pay_date=date.fromisoformat(inputs["payDate"]),
               nl_contract=CONTRACTS[inputs["contract"]], nl_with_tax_credit=inputs["withTaxCredit"],
               nl_vcr_before=vcr_before, nl_expat_decision=_expat(inputs.get("expatDecision")))


def _view(out):
    nl = out["nl_result"]
    return {"tds": out["tds"], "nl": nl, "trace": {t.get("code"): t for t in nl["trace"]}}


def _get(view, dotted):
    node = view
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, f"{dotted}: no '{part}'"
        node = node[part]
    return node


def _same(actual, expected):
    if isinstance(expected, (bool, int)) and not isinstance(actual, str):
        return actual == expected
    if isinstance(expected, int):
        return str(actual) == str(expected)
    return str(actual) == str(expected)


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture_is_governed(path):
    fx = _load(path)
    assert fx["status"] in ("PROVISIONAL", "OFFICIAL"), path.name
    assert fx["source"]["spec"].startswith("ZP-NL-ENG-001")
    if fx["status"] == "PROVISIONAL":
        assert "G1" in fx["statusNote"] and "NOT an official" in fx["statusNote"]
    else:  # an official vector must be traceable and independently reviewed (NL-054)
        table = fx["source"]["tableRow"]
        assert table.get("kind") == "OFFICIAL" and len(table.get("fileSha256", "")) == 64
        assert fx["source"].get("reviewedBy") and fx["source"].get("reviewedOn")
    assert fx["source"].get("formulas"), "expected figures must show how they were derived"


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_engine_matches_golden_vector(path):
    fx = _load(path)
    vcr_before = {}
    for i, period in enumerate(fx["periods"]):
        inputs = period["inputs"]
        out = _calculate(inputs, vcr_before if inputs.get("chainVcr") else {})
        view = _view(out)
        for section in ("expected", "intermediates"):
            for key, want in (period.get(section) or {}).items():
                got = _get(view, key)
                assert _same(got, want), f"{fx['id']} period {i + 1} {section} {key}: got {got!r}, want {want!r}"
        for code in period.get("traceCodes", []):
            assert code in view["trace"], f"{fx['id']}: trace step {code} missing"
        codes = {e["code"] for e in out["nl_result"]["exceptions"]}
        for code in period.get("exceptionCodes", []):
            assert code in codes, f"{fx['id']}: exception {code} missing"
        assert out["nl_result"]["inputHash"], "every golden calculation must be replayable (input hash)"
        vcr_before = out["nl_result"]["vcr"]["after"]


def test_f1_f2_loonaangifte_fields_end_to_end(db, nlx):
    """F1/F2 through the real run -> approval (commit) -> return builder."""
    from app.modules.payroll import netherlands_filing_service as filings
    from app.modules.payroll.models import PayrollNlEmployerProfile, PayrollNlLoonaangifteLine

    fx = _load(GOLDEN_DIR / "F1_F2_white_monthly_and_premiums.json")["loonaangifte"]
    _run_and_approve(db, nlx, fx["month"])
    employer = db.query(PayrollNlEmployerProfile).filter_by(organization_id=nlx.org.id).one()
    ret = filings.build_loonaangifte_return(db, organization_id=nlx.org.id, employer_profile_id=employer.id,
                                            tax_year=2026, period_code=fx["periodCode"], return_type="REGULAR",
                                            actor_id=801)
    line = db.query(PayrollNlLoonaangifteLine).filter_by(return_id=ret.id).one()
    for key, want in fx["line"].items():
        assert _same(getattr(line, key), want), f"line {key}: got {getattr(line, key)!r}, want {want}"
    for key, want in fx["totals"].items():
        assert Decimal(str(getattr(ret, key))) == Decimal(want), f"return {key}: got {getattr(ret, key)}, want {want}"
