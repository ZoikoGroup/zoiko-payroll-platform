"""Belgium (ZP-BE-ENG-001) Block I3: structured operational events (zoiko.belgium logger).

Every Belgian block / refusal / filing state / reveal step is logged with its code and internal ids only — never a
NISS, a name, an IBAN or an amount. The allow-list itself is enforced (unit), and real flows are captured and
checked (demo month, approval refused, engine block, filing refused, payslip PDF refused, NISS reveal)."""
import json
import logging
import re
from datetime import date

import pytest
from fastapi import HTTPException

NISS = "12312312312"  # privacy-scan: allow (synthetic TEST ONLY value)


def _obs():
    from app.modules.payroll import belgium_observability

    return belgium_observability


def test_the_allow_list_refuses_anything_but_codes_ids_and_counts():
    o = _obs()
    assert o.be_event_fields("be.filing.refused", code="BE_DEMO_FILING") == {"event": "be.filing.refused",
                                                                              "code": "BE_DEMO_FILING"}
    assert o.be_event_fields("be.calculation.blocked", code="BE_ROW_MISSING:be_rounding_onss", employee_id=7)
    for bad in ({"name": "Jan Peeters"}, {"niss": NISS}, {"amount": "3800.00"}, {"employee_id": "7"},
                {"code": "BE_X 3800.00"}, {"code": "Jan"}, {"state": "paid 12"}, {"form": "dmfa form"},
                {"organization_id": True}):
        with pytest.raises(ValueError):
            o.be_event_fields("be.filing.state", **bad)
    with pytest.raises(ValueError):
        o.be_event_fields("be.something.else")


def test_a_malformed_event_is_dropped_never_raised(caplog):
    with caplog.at_level(logging.INFO, logger="zoiko.belgium"):
        _obs().be_log_event("be.filing.refused", code="BE_DEMO_FILING", name="Jan Peeters")
    assert "Jan" not in caplog.text and "be.event dropped: field name" in caplog.text


@pytest.fixture
def demo(db, monkeypatch):
    from app.config import settings
    from app.core import code_generation
    from app.modules.payroll import belgium_demo
    from tests._mx_employer_helpers import make_org

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter) * 1000:05d}")  # room per run
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    t = make_org(db, name="DEMO Belgium BV", code="BEOBS", admins=2, country="BE")
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", str(t.org.id))
    belgium_demo.be_seed_demo_pack(db)
    db.commit()
    return t


def _records(caplog):
    return [r for r in caplog.records if r.name == "zoiko.belgium"]


def test_real_flows_log_codes_and_ids_only(db, demo, caplog):
    from app.modules.payroll import belgium_demo, belgium_filing as bf, belgium_service as be, service
    from app.modules.payroll.models import PayrollBeFiling, PayrollEmployee, PayrollRun, PayslipItem

    org, a, b = demo.org.id, demo.users[0].id, demo.users[1].id
    with caplog.at_level(logging.INFO, logger="zoiko.belgium"):
        out = belgium_demo.be_seed_demo_month(db, org, a, b)                       # filings DRAFT -> be.filing.state
        filing = db.get(PayrollBeFiling, out["dmfaFilingId"])
        with pytest.raises(HTTPException):
            bf.record_be_filing_submission(db, org, filing.id, {"submissionRef": "X"}, a)    # BE_DEMO_FILING
        # approval refused: a second run whose exceptions are not acknowledged
        employees = [e.id for e in db.query(PayrollEmployee).filter_by(organization_id=org)]
        run = PayrollRun(organization_id=org, period_label="Obs Oct 2026", period_start=date(2026, 10, 1),
                         period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31), created_by=a)
        db.add(run)
        db.commit()
        service.generate_payslips_for_run(db, run, org)
        db.commit()
        service.advance_payroll_run_status(db, run.id, a, org)
        db.commit()
        blocking = [p for p in be.be_run_preflight(db, run) if p["severity"] == "BLOCK"]
        if blocking:
            with pytest.raises(Exception):
                service.advance_payroll_run_status(db, run.id, b, org)
            db.rollback()
        # engine block: an employee with no Belgian records
        bare = PayrollEmployee(organization_id=org, employee_code="OBS-BARE", name="Bare Synthetic Worker",
                               country_code="BE", ctc=3000, basic=3000, hra=0)
        db.add(bare)
        db.commit()
        with pytest.raises(Exception):
            service.preview_payroll_run(db, org, [bare.id], "BE", period_start=date(2026, 9, 1),
                                        period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
        db.rollback()
        # payslip PDF refused (no snapshot)
        item = db.get(PayslipItem, out["payslips"][0])
        item.be_calculation_snapshot = None
        db.commit()
        with pytest.raises(HTTPException):
            service.generate_payslip_pdf_bytes(db, item.id, org)
        # NISS reveal: requested, approved by a second person, used once
        vault = be.create_be_identifier(db, org, "NISS", NISS, a, employee_id=employees[0])
        db.commit()
        be.request_be_identifier_reveal(db, org, vault.id, "Dimona check", a)
        be.approve_be_identifier_reveal(db, org, vault.id, b)
        assert be.reveal_be_identifier(db, org, vault.id, a)["value"] == NISS
        db.commit()

    records = _records(caplog)
    events = {r.be_event["event"] for r in records if hasattr(r, "be_event")}
    expected = {"be.filing.state", "be.filing.refused", "be.calculation.blocked", "be.payslip.pdf_refused",
                "be.identifier.reveal"} | ({"be.run.approval_refused"} if blocking else set())
    assert expected <= events, expected - events
    allowed = _obs().ALLOWED
    names = [n for (n,) in db.query(PayrollEmployee.name).filter_by(organization_id=org)]
    for r in records:
        text = r.getMessage()
        assert set(getattr(r, "be_event", {})) <= allowed, r.be_event
        assert NISS not in text and not re.search(r"BE\d{14}", text)
        assert not re.search(r"\d+\.\d{2}\b", text), text                         # no amount
        assert not any(name in text for name in names), text
    reveal = [r.be_event for r in records if getattr(r, "be_event", {}).get("event") == "be.identifier.reveal"]
    assert [e["state"] for e in reveal] == ["REVEAL_REQUESTED", "REVEAL_APPROVED", "REVEALED"]
    assert all(e["organization_id"] == org and e["vault_id"] == vault.id for e in reveal)
    blocked = [r.be_event for r in records if getattr(r, "be_event", {}).get("event") == "be.calculation.blocked"]
    assert any(e.get("employee_id") == bare.id and e["code"].startswith("BE_") for e in blocked)
    states = {(e.be_event.get("form"), e.be_event["state"]) for e in records
              if getattr(e, "be_event", {}).get("event") == "be.filing.state"}
    assert ("DMFA", "DRAFT") in states
