"""Belgium (ZP-BE-ENG-001) Block C2: parallel cycles (G4), golden replay of
authority examples (G1) and the release gates G1-G7 computed from evidence.

SYNTHETIC TEST ONLY content and records; users a = maker, b = checker."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from tests.test_belgium_run_lifecycle import NISS, _approve, _run, world  # noqa: F401  (pytest fixture)


def _bp():
    from app.modules.payroll import belgium_parallel

    return belgium_parallel


def _csv(rows, header="code,gross,net,withholding"):
    return "\n".join([header] + rows) + "\n"


def _committed(w):
    from app.modules.payroll.models import PayslipItem

    run = _approve(w, _run(w))
    item = w.db.query(PayslipItem).filter_by(payroll_run_id=run.id).one()
    return run, item


MAP = {"employeeCode": "code", "gross": "gross", "net": "net", "withholding": "withholding"}


# ── parallel cycles (G4) ───────────────────────────────────────────────────
def test_a_matching_file_is_a_clean_cycle_accepted_four_eyes(world):
    bp = _bp()
    w = world
    run, item = _committed(w)
    snap = item.be_calculation_snapshot
    text = _csv([f"BE1,{item.gross_pay},{item.net_pay},{snap['be_withholding']}"])
    out = bp.import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "TEST ONLY payroll", "csv": text,
                                           "columnMap": MAP, "reason": "cycle 1"}, w.a)
    w.db.commit()
    assert out["clean"] and out["matchedCount"] == 1 and out["differences"] == []
    with pytest.raises(BadRequestException):
        bp.accept_be_parallel_import(w.db, w.org, out["id"], w.a)                         # the importer cannot accept
    w.db.rollback()
    assert bp.accept_be_parallel_import(w.db, w.org, out["id"], w.b)["status"] == "ACCEPTED"
    with pytest.raises(BadRequestException, match="already imported"):
        bp.import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "x", "csv": text, "columnMap": MAP,
                                         "reason": "again"}, w.a)


def test_differences_are_explained_then_accepted_by_another_person(world):
    bp = _bp()
    w = world
    run, item = _committed(w)
    text = _csv([f"BE1,{item.gross_pay},{item.net_pay + Decimal('0.01')},0"])
    out = bp.import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "TEST ONLY", "csv": text, "columnMap": MAP,
                                           "reason": "cycle"}, w.a)
    w.db.commit()
    concepts = {d["concept"]: d for d in out["differences"]}
    assert set(concepts) == {"net", "withholding"} and concepts["net"]["difference"] == "-0.01"
    with pytest.raises(BadRequestException, match="EXPLAINED"):
        bp.accept_be_parallel_difference(w.db, w.org, concepts["net"]["id"], w.b)
    for d in concepts.values():
        bp.explain_be_parallel_difference(w.db, w.org, d["id"], "TEST ONLY rounding of the incumbent", w.a)
    w.db.commit()
    with pytest.raises(BadRequestException):
        bp.accept_be_parallel_difference(w.db, w.org, concepts["net"]["id"], w.a)       # four-eyes
    w.db.rollback()
    with pytest.raises(BadRequestException, match="difference be accepted"):
        bp.accept_be_parallel_import(w.db, w.org, out["id"], w.b)
    for d in concepts.values():
        bp.accept_be_parallel_difference(w.db, w.org, d["id"], w.b)
    w.db.commit()
    assert bp.accept_be_parallel_import(w.db, w.org, out["id"], w.b)["clean"]


def test_the_tolerance_comes_only_from_signed_content(world, monkeypatch):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack
    from tests._be_engine_helpers import build_pack, rate

    bp = _bp()
    w = world
    run, item = _committed(w)
    assert set(bp.be_parallel_tolerances(w.db, w.org, run.pay_date).values()) == {Decimal("0")}         # unsigned: exact
    rates = {k: dict(rate(k), flat_amount="0.05") for k in bp.TOLERANCE_KEYS.values()}
    rate_map, slabs = build_pack(rates_over=rates)
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: BePack(rate_map, slabs, org, on))
    assert bp.be_parallel_tolerances(w.db, w.org, run.pay_date)["net"] == Decimal("0.05")
    text = _csv([f"BE1,{item.gross_pay},{item.net_pay + Decimal('0.04')},"
                 f"{item.be_calculation_snapshot['be_withholding']}"])
    out = bp.import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "TEST ONLY", "csv": text, "columnMap": MAP,
                                           "reason": "cycle"}, w.a)
    assert out["differences"] == [] and out["clean"]


@pytest.mark.parametrize("cell, kind", [(NISS, "NISS / BIS"), ("0999.999.999", "enterprise number"),
                                        ("BE71 0961 2345 6769", "IBAN")])  # privacy-scan: allow (synthetic TEST ONLY)
def test_a_file_carrying_an_identifier_is_refused(world, cell, kind):
    w = world
    run, _item = _committed(w)
    text = _csv([f"BE1,100,90,10,{cell}"], header="code,gross,net,withholding,ref")
    with pytest.raises(BadRequestException, match=kind):
        _bp().import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "x", "csv": text, "columnMap": MAP,
                                            "reason": "r"}, w.a)
    with pytest.raises(BadRequestException, match="identifier column"):
        _bp().import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "x", "csv": _csv(
            ["BE1,100,90,10,1"], header="code,gross,net,withholding,NISS"), "columnMap": MAP, "reason": "r"}, w.a)


def test_only_a_committed_run_is_compared(world):
    w = world
    run = _run(w)
    with pytest.raises(BadRequestException, match="committed"):
        _bp().import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "x", "csv": _csv(["BE1,1,1,1"]),
                                            "columnMap": MAP, "reason": "r"}, w.a)


def test_g4_needs_two_accepted_months_for_every_launch_employer(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll.models import PayrollBeParallelImport

    bp = _bp()
    w = world
    assert bp.be_g4_state(w.db, frozenset())[0] is False
    for month, digest in ((date(2026, 1, 1), "a"), (date(2026, 2, 1), "b")):
        w.db.add(PayrollBeParallelImport(organization_id=w.org, pay_date=month, cycle_month=month,
                                         source_name="TEST ONLY", file_hash=digest * 64, column_map={},
                                         status="ACCEPTED", created_by_id=w.a, approved_by_id=w.b))
        w.db.commit()
        ok, detail = bp.be_g4_state(w.db, frozenset({w.org}))
    assert ok and "1 of 1" in detail
    assert bp.be_g4_state(w.db, frozenset({w.org, 999}))[0] is False
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", str(w.org))
    from app.modules.payroll import belgium_readiness

    g4 = [c for c in belgium_readiness.be_code_checks(w.db)["G4"]]
    assert g4 and g4[0]["ok"]


# ── golden replay (G1) ─────────────────────────────────────────────────────
def test_examples_parse_or_say_what_is_wrong():
    from app.modules.payroll import belgium_golden as g

    spec = g.be_parse_example("G=3000;EC=X1;WC=W1;JC=200;CAT=manual;D=2026-03-31 => net=1;wht=2")
    assert spec["inputs"]["CAT"] == "MANUAL" and spec["expected"] == {"net": Decimal("1"), "wht": Decimal("2")}
    for bad, why in (("", "no replayable case"), ("G=1;EC=X1;WC=W1", "inputs => expected"),
                     ("G=1;WC=W1 => net=1", "EC is required"), ("G=1;EC=X1;WC=W1 => foo=1", "unknown expected"),
                     ("G=1;EC=X1;WC=W1;JC=200;CAT=CEO => net=1", "CAT must be"), ("G=x;EC=X1;WC=W1;JC=200 => net=1", "number"), ("G=1;EC=X1;WC=W1 => net=1", "JC is required")):
        with pytest.raises(ValueError, match=why):
            g.be_parse_example(bad)


def _ns(values):
    numbers = ("min_amount", "max_amount", "rate_pct", "flat_amount", "employee_rate_pct", "employer_rate_pct")
    out = {"tax_regime": None, "assessment_basis": None, "min_amount": "0", "max_amount": None, "rate_pct": "0",
           "flat_amount": None, "formula_expression": None, "filing_status": None, "id": 0, "sort_order": 0,
           **values}
    return SimpleNamespace(**{k: (Decimal(v) if k in numbers and v is not None else v) for k, v in out.items()})


def _golden_pack(monkeypatch, examples):
    from app.modules.payroll import belgium_golden as g
    from app.modules.payroll.engine.countries import belgium_content as c
    from tests._be_engine_helpers import build_pack

    rate_map, slabs = build_pack()
    rates = {k: _ns(v) for k, v in rate_map.items()}
    rows = [_ns(s) for s in slabs] + [_ns({"rule_type": c.AUTHORITY_EXAMPLE_RULE, "filing_status": name,
                                           "formula_expression": case, "rate_label": f"Authority example {name}",
                                           "id": 900 + i}) for i, (name, case) in enumerate(examples)]
    monkeypatch.setattr(g, "_be_golden_pack_rows", lambda db, pack: (rates, rows))
    return SimpleNamespace(id=1, pack_id="TEST-BE", version="1.0", effective_from=date(2026, 1, 1))


def _actual(monkeypatch):
    """The engine's figures for the synthetic case (to build a matching example)."""
    from app.modules.payroll import belgium_golden as g
    from app.modules.payroll.engine.countries import belgium as engine

    pack = _golden_pack(monkeypatch, [])
    rates, rows = g._be_golden_pack_rows(None, pack)
    spec = g.be_parse_example("G=3000;EC=X1;WC=W1;JC=200;D=2026-03-31;H=38 => net=0")
    return g._be_golden_figures(engine.calculate(g.be_example_context(spec, rates, rows, pack.effective_from))["be_result"])


def test_an_example_that_replays_exactly_passes_and_certifies(db, monkeypatch):
    from app.modules.payroll import belgium_golden as g

    fig = _actual(monkeypatch)
    case = (f"G=3000;EC=X1;WC=W1;JC=200;D=2026-03-31;H=38 => wht={fig['wht']};onssEe={fig['onssEe']};"
            f"employer={fig['employer']};net={fig['net']}")
    pack = _golden_pack(monkeypatch, [("TEST-1", case)])
    check = g.be_golden_check(db, pack)
    assert check["passed"] and check["examples"] == 1
    assert g.be_golden_refusal(db, pack) and "certification run is missing" in g.be_golden_refusal(db, pack)
    run, _check = g.record_be_golden_certification(db, pack, None)
    db.commit()
    assert run.status == "PASS" and run.jurisdiction_country == "BE" and g.be_golden_refusal(db, pack) is None


def test_a_mismatch_or_a_missing_case_fails_and_blocks_activation(db, monkeypatch):
    from app.modules.payroll import belgium_golden as g

    fig = _actual(monkeypatch)
    wrong = f"G=3000;EC=X1;WC=W1;JC=200;D=2026-03-31;H=38 => net={fig['net'] + Decimal('0.01')}"
    pack = _golden_pack(monkeypatch, [("WRONG", wrong), ("NOCASE", None)])
    check = g.be_golden_check(db, pack)
    assert not check["passed"]
    by_name = {r["example"]: r for r in check["results"]}
    assert by_name["WRONG"]["failures"][0]["field"] == "net"
    assert "no replayable case" in by_name["NOCASE"]["error"]
    run, _c = g.record_be_golden_certification(db, pack, None)
    assert run.status == "FAIL" and run.failed_cases == 2
    assert "do not replay exactly" in g.be_golden_refusal(db, pack)
    empty = _golden_pack(monkeypatch, [])
    assert g.record_be_golden_certification(db, empty, None)[0].status == "NO_REAL_CASES"


# ── readiness G1-G7 ────────────────────────────────────────────────────────
def test_every_gate_is_red_without_evidence_and_available_is_refused(db):
    from app.modules.payroll import belgium_readiness as r
    from app.modules.payroll import belgium_service as be

    state = r.be_readiness(db)
    assert [g["gate"] for g in state["gates"]] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert not any(g["passed"] for g in state["gates"]) and not state["allPassed"]
    checks = {g["gate"]: {c["key"]: c for c in g["checks"]} for g in state["gates"]}
    assert checks["G3"]["transmission_adapter"]["ok"] is False
    assert checks["G1"]["pack_seeded"]["ok"] is False
    assert {"be-owner-content", "be-owner-specialist"} <= set(checks["G7"])
    unmet = be.be_unmet_requirements(db)
    assert {u["key"] for u in unmet} >= {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}
    summary = be.be_statutory_summary(db)
    assert summary["status"] == "NOT_CERTIFIED" and set(summary["gates"].values()) == {"NOT MET"}
    assert len(summary["gateDetails"]) == 7
    be.ensure_be_service_registry_row(db)
    db.commit()
    with pytest.raises((BadRequestException, HTTPException)):
        be._be_service_registry_transition(db, "AVAILABLE", "TEST ONLY go live")


def test_g2_sector_coverage_names_each_uncovered_line(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll import belgium_readiness as r

    w = world
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", str(w.org))
    g2 = {c["key"]: c for c in r.be_code_checks(w.db)["G2"]}
    assert g2["launch_employers_named"]["ok"]
    detail = g2["sector_coverage"]["detail"]
    assert not g2["sector_coverage"]["ok"] and "1 without certified" in detail and f"[{w.org}]" in detail
    assert f"#{w.employee.id}" not in detail and w.employee.name not in detail          # counts only
    assert g2["no_special_regimes"]["ok"]


def test_g5_counts_accepted_filings_of_launch_employers(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll import belgium_readiness as r

    w = world
    monkeypatch.setattr(settings, "BE_CANARY_ORG_IDS", str(w.org))
    g5 = {c["key"]: c for c in r.be_code_checks(w.db)["G5"]}
    assert g5["accepted_dimona"]["ok"]                      # the fixture's accepted Dimona IN
    assert not g5["accepted_dmfa"]["ok"] and not g5["reconciled_obligation"]["ok"]
    assert not g5["be-filing-e2e"]["ok"]
