"""Belgium (ZP-BE-ENG-001) Block J2: be_calculation_snapshot version 2 (pack by reference, used rows once).

* Version 1 — a CAPTURED snapshot from before the change (tests/fixtures/belgium_snapshot_v1.json, synthetic
  DEMO data) — still replays exactly and is read correctly by every reader: replay / correction context, payslip
  view, payslip PDF, filings (employer totals, demo flag), parallel run amounts, used rows.
* Version 2 — new snapshots reference the pack (packRef) and keep the used rows once; replay resolves the
  reference and reproduces the calculation exactly; a changed pack row or a missing database refuses the replay
  (fail closed); a correction of a version-2 payslip works and is itself version 2; no auditable fact is lost.
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.exceptions import BadRequestException

FIXTURE = Path(__file__).parent / "fixtures" / "belgium_snapshot_v1.json"


def _v1():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot"]


def _be():
    from app.modules.payroll import belgium_service

    return belgium_service


def _same_calculation(result, snapshot):
    r = result["be_result"] if isinstance(result, dict) else result.be_result
    for key in ("be_net", "be_withholding", "be_employee_total", "be_employer_total", "accumulatorDeltas",
                "bases", "hashes"):
        assert r[key] == snapshot[key], key
    assert r["usedRows"] == _be().be_snapshot_used_rows(snapshot)                       # full form, both versions


def _engine_sha(value):
    from app.modules.payroll.engine.countries import belgium as engine

    return engine._sha(value)


# ── version 1 (captured) ───────────────────────────────────────────────────
def test_the_captured_version_1_snapshot_replays_exactly_without_the_database():
    snap = _v1()
    assert "snapshot_version" not in snap and snap["frozenContext"]["version"] == 1
    assert "rateMap" in snap["frozenContext"] and snap["trace"]["contentUsed"] == snap["usedRows"]
    _same_calculation(_be().be_replay(snap["frozenContext"]), snap)


def test_every_reader_handles_version_1(db, monkeypatch):
    from app.config import settings
    from app.modules.payroll import belgium_filing as bf, belgium_parallel as bp, service
    from app.modules.payroll.models import PayrollRun, PayslipItem
    from tests._mx_employer_helpers import make_org

    be, snap = _be(), _v1()
    assert be.be_snapshot_used_rows(snap) == snap["usedRows"]
    assert "frozenContext" not in be.be_payslip_view(snap)
    t = make_org(db, name="V1 BV", code="BEV1", country="BE")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", str(t.org.id))
    run = PayrollRun(organization_id=t.org.id, period_label="v1", period_start=date(2026, 9, 1),
                     period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, organization_id=t.org.id, employee_id=1, employee_name="Synthetic",
                       country_code="BE", gross_pay=Decimal(snap["bases"]["ONSS_EMPLOYEE"]),
                       net_pay=Decimal(snap["be_net"]), be_calculation_snapshot=snap)
    db.add(item)
    db.commit()
    pdf = service.generate_payslip_pdf_bytes(db, item.id, t.org.id)                      # payslip PDF
    assert pdf.startswith(b"%PDF")
    demo = []
    totals = bf._employer_contributions(db, {item.id}, demo)                             # filings
    assert totals[item.id][0] == Decimal(snap["be_employer_total"]) and demo == [item.id]
    amounts = bp.be_parallel_amounts(item)                                               # parallel run
    assert amounts["net"] == Decimal(snap["be_net"])


# ── version 2 (new) ────────────────────────────────────────────────────────
@pytest.fixture
def demo_month(db, monkeypatch):
    from app.config import settings
    from app.core import code_generation
    from app.modules.payroll import belgium_demo
    from tests._mx_employer_helpers import make_org

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter) * 1000:05d}")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    t = make_org(db, name="DEMO V2 BV", code="BEV2", admins=2, country="BE")
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", str(t.org.id))
    belgium_demo.be_seed_demo_pack(db)
    db.commit()
    return t, belgium_demo.be_seed_demo_month(db, t.org.id, t.users[0].id, t.users[1].id)


def test_new_snapshots_are_version_2_and_replay_exactly_from_the_reference(db, demo_month):
    from app.modules.payroll.models import PayslipItem

    be = _be()
    _t, out = demo_month
    for item in db.query(PayslipItem).filter(PayslipItem.id.in_(out["payslips"])):
        snap = item.be_calculation_snapshot
        frozen = snap["frozenContext"]
        assert snap["snapshot_version"] == 2 and frozen["version"] == 2
        assert "rateMap" not in frozen and "slabs" not in frozen and frozen["packRef"]["rowsHash"]
        assert "contentUsed" not in snap["trace"] and snap["trace"]["contentUsedRef"] == "usedRows"
        assert snap["usedRowsFormat"] == "compact" and snap["usedRows"]
        full = be.be_snapshot_used_rows(snap)                                       # lossless expansion:
        assert _engine_sha(full) == snap["hashes"]["content"]                       # == the engine's content hash
        assert be.be_payslip_view(snap)["usedRows"] == full and "usedRowsFormat" not in be.be_payslip_view(snap)
        _same_calculation(be.be_replay(frozen, db), snap)
        with pytest.raises(BadRequestException, match="needs the database"):
            be.be_replay(frozen)


def test_version_2_keeps_every_fact_of_version_1(db, demo_month):
    """The reference resolves to exactly the rows a version-1 copy would have held (same hash), and the snapshot
    keeps every top-level fact; only the pack copy and the duplicate used-rows list are gone."""
    from app.modules.payroll.models import PayslipItem

    be = _be()
    _t, out = demo_month
    snap = db.get(PayslipItem, out["payslips"][0]).be_calculation_snapshot
    ref = snap["frozenContext"]["packRef"]
    rate_map, slabs = be._be_resolve_pack_ref(db, ref)
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("id", "jurisdiction_pack_id")} for r in rows]
    assert be._be_rows_hash({k: strip(v) for k, v in rate_map.items()},
                            [{k: v for k, v in s.items() if k != "jurisdiction_pack_id"} for s in slabs]) \
        == ref["rowsHash"]
    assert ref["packVersion"] and set(_v1()) - set(snap) == set()                     # no top-level fact lost
    assert len(json.dumps(snap)) < len(FIXTURE.read_text(encoding="utf-8")) / 2


def test_a_changed_pack_row_refuses_the_version_2_replay(db, demo_month):
    from app.modules.payroll.models import ContributionRate, PayslipItem

    be = _be()
    _t, out = demo_month
    frozen = db.get(PayslipItem, out["payslips"][0]).be_calculation_snapshot["frozenContext"]
    rate_id = next(i for ids in frozen["packRef"]["rateIds"].values() for i in ids)
    row = db.get(ContributionRate, rate_id)
    row.label = (row.label or "") + " (changed)"
    db.commit()
    with pytest.raises(BadRequestException, match="changed since"):
        be.be_replay(frozen, db)


def test_a_correction_of_a_version_2_payslip_works_and_is_version_2(db, demo_month):
    from app.modules.payroll.models import PayslipItem

    be = _be()
    t, out = demo_month
    original = db.get(PayslipItem, out["payslips"][0])
    fix = be.create_be_correction(db, t.org.id, original.id, {
        "reason": "late raise", "evidenceRef": "TEST ONLY letter", "payDate": "2026-10-31",
        "inputDelta": {"gross": "4000", "basic": "4000"}}, t.users[0].id)
    db.commit()
    snap = db.get(PayslipItem, fix["payslipItemId"]).be_calculation_snapshot
    assert snap["snapshot_version"] == 2 and snap["frozenContext"]["version"] == 2
    assert snap["correctionOf"] == original.id and Decimal(snap["grossDelta"]) != 0
