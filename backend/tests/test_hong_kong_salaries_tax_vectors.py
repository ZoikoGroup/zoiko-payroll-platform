"""
tests/test_hong_kong_salaries_tax_vectors.py
--------------------------------------------
Independent Hong Kong Salaries Tax golden vectors (release gate, ZP-HK-ENG-001
§16 / HK-012). The vectors in tests/fixtures/hk_salaries_tax_vectors/vectors.json
were written by hand from the IRD's published worked examples and the PAM 61(e)
parameters; nothing in this file computes an EXPECTED value with production code.

Three independent checks per vector, then the production comparison:
  1. the vector's own derivation is arithmetically consistent (re-added here
     from its written steps — this file never imports the production calculator
     for that);
  2. the statutory parameters the vector relies on are exactly the values in the
     seeded pack rows for that year of assessment, each traced to its IRD source
     (OFFICIAL SOURCE → PACK → EFFECTIVE DATE);
  3. the production estimate, fed only the pack's resolved rows, returns the
     expected figures (→ RESOLVER → CALCULATOR → RESULT).
"""

import json
import re
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "hk_salaries_tax_vectors" / "vectors.json")
                     .read_text(encoding="utf8"))
YA_START = {"2025/26": date(2025, 4, 1), "2026/27": date(2026, 4, 1)}


def _d(v):
    return D("0") if v in (None, "") else D(str(v))


@pytest.fixture()
def hk_packs(db):
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    packs = seed_hong_kong_all(db)
    for p in packs:
        p.status = "Active"     # test-only: resolution needs Active packs; production activation is gated
    db.commit()
    return packs


def _resolved(db, ya):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    rates, slabs, pack = resolve_tax_configuration(db, "HK", payroll_date=YA_START[ya])
    assert pack is not None and pack.tax_year == ya
    return {r.component_key: r for r in rates}, slabs, pack


# ── 1. derivations are internally consistent (independent arithmetic) ────

@pytest.mark.parametrize("v", VECTORS["vectors"], ids=lambda v: v["id"])
def test_vector_derivation_is_arithmetically_consistent(v):
    d = v["derivation"]
    income = _d(v["inputs"]["income"])
    allowed = sum((_d(x) for x in (d.get("deductionsAllowed") or {}).values()), D("0"))
    assert _d(d["netIncome"]) == max(income - _d(v["inputs"].get("deductions")) - allowed, D("0"))
    params = VECTORS["parameters"][v["ya"]]
    allowance_total = sum((_d(params[f"hk_allowance_{k}"]) * n for k, n in (v["inputs"].get("allowances") or {}).items()), D("0"))
    assert _d(d["totalAllowances"]) == allowance_total
    assert _d(d["nci"]) == max(_d(d["netIncome"]) - allowance_total, D("0"))
    assert sum((_d(p) for p, _r in d["progressive"]), D("0")) == _d(d["nci"])
    assert sum((_d(p) for p, _r in d["standard"]), D("0")) == _d(d["netIncome"])
    prog = sum((_d(p) * _d(r) / 100 for p, r in d["progressive"]), D("0"))
    std = sum((_d(p) * _d(r) / 100 for p, r in d["standard"]), D("0"))
    assert (prog, std) == (_d(d["progressiveTax"]), _d(d["standardTax"]))
    assert _d(d["taxBeforeReduction"]) == min(prog, std)
    # Each band portion respects the statutory band width of that year.
    widths = [None if hi is None else _d(hi) - _d(lo) for lo, hi, _r in params["progressive"]]
    for (portion, rate), width, (_lo, _hi, prate) in zip(d["progressive"], widths, params["progressive"]):
        assert rate == prate and (width is None or _d(portion) <= width)
    tax_expected = min(prog, std) - _d(d["reduction"])
    assert _d(v["expected"]["estimatedTax"]) == tax_expected


def test_every_vector_is_sourced_and_flagged():
    for v in VECTORS["vectors"]:
        assert v["verification"] in ("OFFICIAL_EXAMPLE", "DERIVED_FROM_STATUTORY_PARAMETERS"), v["id"]
        if v["verification"] == "OFFICIAL_EXAMPLE":
            assert v.get("source"), v["id"]
    ids = [v["id"] for v in VECTORS["vectors"]]
    assert len(ids) == len(set(ids))


# ── 2. OFFICIAL SOURCE → PACK → EFFECTIVE DATE ──────────────────────────

@pytest.mark.parametrize("ya", sorted(VECTORS["parameters"]))
def test_vector_parameters_are_the_seeded_pack_values_for_that_year(db, hk_packs, ya):
    from app.modules.payroll.models import SourceArtifact

    rate_map, slabs, pack = _resolved(db, ya)
    params = VECTORS["parameters"][ya]
    sources = {k: re.search(r"https://\S+?(?=,)", v).group(0) for k, v in VECTORS["sources"].items()}
    for key, value in params.items():
        if key in ("progressive", "standard", "absent"):
            continue
        row = rate_map.get(key)
        assert row is not None, f"{ya}: no pack row {key}"
        configured = row.flat_amount if row.flat_amount is not None else row.employee_rate_pct
        assert D(str(configured)) == D(value), f"{ya} {key}: pack {configured} != statutory {value}"
        art = db.get(SourceArtifact, row.source_document_id)
        assert art is not None and art.source_url in (sources["ird_pam61e"], sources["ird_adc"]), key
        assert pack.effective_from == YA_START[ya]
    for key in params.get("absent", []):
        assert key not in rate_map, f"{ya}: {key} must not exist (no reduction legislated for {ya})"
    for rule_type, name in (("HK_SALARIES_TAX_PROGRESSIVE", "progressive"), ("HK_SALARIES_TAX_STANDARD", "standard")):
        rows = sorted((s for s in slabs if s.rule_type == rule_type), key=lambda s: s.min_amount)
        got = [[str(r.min_amount.normalize()) if r.min_amount else "0",
                None if r.max_amount is None else str(r.max_amount.normalize()), str(r.rate_pct.normalize())]
               for r in rows]
        want = [[str(_d(lo).normalize()) if _d(lo) else "0", None if hi is None else str(_d(hi).normalize()),
                 str(_d(rt).normalize())] for lo, hi, rt in params[name]]
        assert got == want, f"{ya} {name}"


# ── 3. → RESOLVER → CALCULATOR → RESULT ─────────────────────────────────

@pytest.mark.parametrize("v", VECTORS["vectors"], ids=lambda v: v["id"])
def test_production_estimate_matches_the_independent_vector(db, hk_packs, v):
    from app.modules.payroll.engine.jurisdictions.hong_kong import salaries_tax

    rate_map, slabs, _pack = _resolved(db, v["ya"])
    inputs = v["inputs"]
    out = salaries_tax.estimate(
        year_of_assessment=v["ya"], rate_map=rate_map, slabs=slabs, income=_d(inputs["income"]),
        deductions=_d(inputs.get("deductions")), allowances=inputs.get("allowances") or {},
        deduction_claims=inputs.get("deductionClaims") or {}, elections=inputs.get("elections") or [])
    for field, expected in v["expected"].items():
        actual = out[field]
        if field == "basisApplied":
            assert actual == expected, f"{v['id']} {field}"
        else:
            assert D(actual) == D(expected), f"{v['id']} {field}: expected {expected}, got {actual}"
    allowed = {l["deduction"]: D(l["allowed"]) for l in out["deductionClaims"]}
    assert allowed == {k: D(x) for k, x in (v["derivation"].get("deductionsAllowed") or {}).items()}, v["id"]
    assert out["label"] == "INFORMATIONAL_NOT_WITHHELD"


@pytest.mark.parametrize("a", VECTORS["attribution"], ids=lambda a: a["id"])
def test_year_of_assessment_attribution(a):
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment

    assert year_of_assessment(date.fromisoformat(a["date"])) == a["expected"]


def test_salaries_tax_is_never_payroll_withholding(db, hk_packs):
    """The estimate exists for information; the payroll calculator never calls
    it and never sets tds (architecture lock)."""
    src = (Path(__file__).parents[1] / "app/modules/payroll/engine/countries/hong_kong.py").read_text(encoding="utf8")
    assert "salaries_tax" not in src
