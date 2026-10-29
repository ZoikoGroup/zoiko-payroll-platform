"""Mexico final mile X2 — the calculation sandbox: SYNTHETIC inputs, the real
Draft packs seeded from mexico_content, the production engine, nothing written.
Without candidates every run stops at MX_ROUNDING_RULE_MISSING (linked to D-01);
with watermarked what-if candidates for D-01 and D-03 the spec §21 fixtures
F1–F4 are reproduced. The candidate values are SYNTHETIC test inputs, not
decisions."""

from decimal import Decimal as D

import pytest

from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, _http

CANDIDATES = [{"decision": "D-01", "value": "HALF_UP:0.01"}, {"decision": "D-03", "value": "GENERAL"}]


def _X():
    from app.modules.payroll import mexico_sandbox_service

    return mexico_sandbox_service


@pytest.fixture()
def world(db):
    from app.modules.payroll import mexico_decision_service
    from scripts.seed_mexico_canonical_packs import seed_mexico

    seed_mexico(db)
    mexico_decision_service.seed_decisions(db)
    db.commit()


def _run(db, **over):
    data = {"payDate": "2026-06-15", "periodStart": "2026-06-01", "periodEnd": "2026-06-15", "dailySalary": "600",
            "zone": "GENERAL", "workState": "CDMX", "payFrequencyCode": "04", "seniorityDate": "2026-01-01"}
    data.update(over)
    return _X().run_mx_sandbox(db, data)


def _counts(db):
    import sqlalchemy as sa

    from app.database import Base

    return {t: db.execute(sa.select(sa.func.count()).select_from(Base.metadata.tables[t])).scalar()
            for t in Base.metadata.tables if t in sa.inspect(db.bind).get_table_names()}


def test_without_a_pack_nothing_is_calculated(db):
    r = _run(db)
    assert r["outcome"] == "BLOCKED" and r["block"]["code"] == "MX_PACK_MISSING" and r["persisted"] is False


def test_today_every_run_stops_at_the_rounding_rule_linked_to_d01(db, world):
    r = _run(db)
    assert r["outcome"] == "BLOCKED" and r["block"]["code"] == "MX_ROUNDING_RULE_MISSING"
    assert [d["code"] for d in r["clearedBy"]] == ["D-01"]
    assert r["pack"]["draft"] is True and "NOT ACTIVE" in r["pack"]["label"]
    assert r["watermarks"] == [_X().SANDBOX_MARK] and r["candidates"] == []


def test_with_d01_alone_it_stops_at_d03_for_every_employee(db, world):
    """Finding (X2): D-03's row is read for every SBC, not only ZLFN band 1."""
    r = _run(db, candidates=CANDIDATES[:1])
    assert r["block"]["code"] == "MX_CONTENT_MISSING" and "mx_ceav_lowest_band_min_wage_ref" in r["block"]["message"]
    assert [d["code"] for d in r["clearedBy"]] == ["D-03"]
    assert _X().CANDIDATE_MARK in r["watermarks"]


def _segment(r):
    return r["result"]["mx_result"]["sbc"]["segments"][0]


def _branch(r, branch, side):
    (b,) = [b for b in r["result"]["mx_result"]["imss"] if (b["branch"], b["side"]) == (branch, side)]
    return b


def test_f1_uma_boundary_january_and_february(db, world):
    jan = _run(db, payDate="2026-01-15", periodStart="2026-01-01", periodEnd="2026-01-15", candidates=CANDIDATES)
    feb = _run(db, payDate="2026-02-15", periodStart="2026-02-01", periodEnd="2026-02-15", candidates=CANDIDATES)
    assert (D(_segment(jan)["uma_daily"]), D(_segment(feb)["uma_daily"])) == (D("113.14"), D("117.31"))
    assert D(_segment(jan)["cap"]) == D("113.14") * 25 and D(_segment(feb)["cap"]) == D("117.31") * 25


def test_f2_first_year_sbc_factor(db, world):
    r = _run(db, candidates=CANDIDATES)
    comps = r["result"]["mx_result"]["sbc"]["components"]
    assert r["outcome"] == "CALCULATED" and comps["service_year"] == 1
    assert D(comps["factor"]).quantize(D("0.000001")) == D("1.049315")                    # (365 + 15 + 12 × 25%) / 365


def test_f3_ceav_high_band(db, world):
    r = _run(db, dailySalary="1000", candidates=CANDIDATES)                              # SBC 1,049.32 > 4.01 UMA
    er = _branch(r, "CEAV", "employer")["lines"][0]
    assert (D(er["rate_pct"]), er["band"]) == (D("7.5130"), "4.01UMA")
    assert D(_branch(r, "CEAV", "employee")["lines"][0]["rate_pct"]) == D("1.125")
    assert D(_branch(r, "RETIRO", "employer")["lines"][0]["rate_pct"]) == D("2")


def test_f4_minimum_wage_geography(db, world):
    """The same 400 / day is lawful in the general zone and below the ZLFN floor
    (315.04 vs 440.87); above both, each zone carries its own floor."""
    general = _run(db, dailySalary="400", candidates=CANDIDATES)
    zlfn = _run(db, dailySalary="400", zone="ZLFN", candidates=CANDIDATES)
    assert general["outcome"] == "CALCULATED" and D(_segment(general)["floor"]) == D("315.04")
    assert zlfn["outcome"] == "BLOCKED" and zlfn["block"]["code"] == "MX_BELOW_MINIMUM_WAGE"
    high = _run(db, dailySalary="500", zone="ZLFN", candidates=CANDIDATES)
    assert high["outcome"] == "CALCULATED" and D(_segment(high)["floor"]) == D("440.87")


@pytest.mark.parametrize("candidate,message", [
    ({"decision": "D-07", "value": "UMA"}, "module switch"),                   # not a pack-row key
    ({"decision": "D-01", "value": "ROUND:1"}, "MODE:QUANTUM"),               # outside the grammar
    ({"decision": "D-99", "value": "x"}, "not yet approved"),                  # no such open decision
    ({"decision": "drop table", "value": "x"}, "decision code"),
])
def test_what_if_is_refused_outside_open_pack_row_decisions(db, world, candidate, message):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match=message):
        _run(db, candidates=[candidate])


def test_an_approved_decision_cannot_be_a_candidate(db, world):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_decision_service as S
    from app.modules.payroll.models import PayrollMxDecision as M

    did = db.query(M).filter(M.code == "D-01").one().id
    S.propose_mx_decision(db, did, {"chosen_option": "HALF_UP:0.01", "rationale": "SYNTHETIC",
                                    "cited_sources": ["S35"]}, SA_A.id)
    S.approve_mx_decision(db, did, SA_A.id + 1)
    with pytest.raises(BadRequestException, match="not yet approved"):
        _run(db, candidates=CANDIDATES[:1])


def test_the_sandbox_writes_nothing(db, world):
    before = _counts(db)
    for over in ({}, {"candidates": CANDIDATES}, {"candidates": CANDIDATES, "zone": "ZLFN"}):
        _run(db, **over)
    db.commit()                                                     # even a commit afterwards persists nothing
    assert _counts(db) == before


def test_the_route_is_super_admin_only_and_watermarks_candidates(db, world):
    body = {"payDate": "2026-06-15", "dailySalary": "600", "candidates": CANDIDATES}
    with _http(db, ORG_ADMIN) as c:
        assert c.post(f"{BASE}/sandbox/calculate", json=body).status_code == 403
    with _http(db, SA_A) as c:
        r = c.post(f"{BASE}/sandbox/calculate", json=body)
    assert r.status_code == 200 and r.json()["outcome"] == "CALCULATED"
    assert "CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR" in r.json()["watermarks"]
