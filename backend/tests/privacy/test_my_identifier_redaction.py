"""Malaysia privacy proof (ZP-MY-ENG-001 §15, MY-029, release gate G4).

A valid NRIC is GENERATED here (a real birth date and place code at run time)
— the file holds no NRIC literal. It is stored in the vault and taken through
every path that handles it: the masked list, the employee summary, the run
preflight, the authority filing payloads, settlements, the journal, the vault
access log, the tax audit trail, the activity log and a parallel-run file.
Only the explicit, approved, single-use reveal may return the digits; nothing
else may carry them, plain or grouped.

Isolation: through the REAL app and auth chain (the privacy world: tenants A
and B, two legal entities each), tenant B's admin is refused every tenant-A
Malaysia record, and inside tenant A two legal employers' filings and
liabilities never mix. PCB is a stand-in (Phase 4); every amount is the TEST
pack's (tests/_my_engine_helpers.py).
"""
import json
import random
import re
from datetime import date
from decimal import Decimal

import pytest

from app.config import settings
from app.core.exceptions import BadRequestException
from app.modules.payroll import malaysia_parallel as mpp
from app.modules.payroll import malaysia_service as mys
from app.modules.payroll.employee_validation import my_nric_is_valid
from app.modules.payroll.models import (
    PayrollActivityLog, PayrollMyFiling, PayrollMyIdentifierAccessEvent, PayrollMySettlement, PayrollRun,
    PayrollStatus, PayslipItem, TaxConfigurationAudit,
)

PAY_DATE = date(2026, 3, 31)


def _generated_nric(seed: int) -> str:
    rng = random.Random(seed)
    while True:
        candidate = (f"{rng.randint(60, 99):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
                     f"{rng.randint(1, 16):02d}{rng.randint(0, 9999):04d}")
        if my_nric_is_valid(candidate):
            return candidate


def _absent(number: str, text: str, where: str):
    for form in (number, f"{number[:6]}-{number[6:8]}-{number[8:]}", f"{number[:6]} {number[6:8]} {number[8:]}"):
        assert form not in text, f"NRIC found in {where}"


def _rows(db, model, **filters) -> str:
    rows = db.query(model).filter_by(**filters).all()
    return json.dumps([{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows], default=str)


@pytest.fixture()
def my_world(world, monkeypatch):
    from app.modules.payroll.engine.jurisdictions.malaysia import pcb
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.models import CompanyComplianceDetails
    from tests._my_engine_helpers import ctx

    monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("100.00"), "trace": {"stub": True}})
    monkeypatch.setattr(settings, "MY_TENANT_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "MY_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "MY_IDENTIFIER_FINGERPRINT_KEY", "m" * 32)
    db = world.db
    for key in ("A", "B"):
        world.orgs[key].country = "Malaysia"
        db.add(CompanyComplianceDetails(organization_id=world.orgs[key].id, jurisdiction_country="MY"))
    for key in ("A1", "A2", "B1"):
        world.employees[key].country_code = "MY"
    db.commit()
    org_a, a1, a2 = world.orgs["A"].id, world.employees["A1"], world.employees["A2"]
    ta, pa = world.users["TA"].id, world.users["PA"].id
    number = _generated_nric(424242)
    ids = {"vault": mys.create_my_identifier(db, org_a, "NRIC", number, ta, employee_id=a1.id).id}
    for n in (1, 2):
        row = mys.record_my_employer_registration(db, org_a, {
            "effective_from": "2026-01-01", "legal_entity_id": world.entities[f"A-E{n}"].id,
            "legal_name": f"Syarikat {n} Sdn Bhd", "hasil_employer_no": f"E10000{n}",
            "hrd_category": "NOT_REGISTERED"}, ta, "setup")
        mys.approve_my_employer_registration(db, org_a, row.id, pa)
        mys.verify_my_employer_registration(db, org_a, row.id, pa, "verified", "checked against HASiL letter")
    for employee in (a1, a2):
        row = mys.record_my_worker_profile(db, org_a, employee.id, {
            "effective_from": "2026-01-01", "contract_type": "contract_of_service", "pay_frequency": "monthly",
            "citizenship": "CITIZEN"}, ta, "hire")
        mys.approve_my_worker_profile(db, org_a, row.id, pa)
    run = PayrollRun(organization_id=org_a, period_label="Mar 2026", period_start=date(2026, 3, 1),
                     period_end=PAY_DATE, pay_date=PAY_DATE, status="Processed")
    db.add(run)
    db.flush()
    for employee in (a1, a2):
        context = ctx()
        result = calculate_payroll(context, "standard")
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=org_a,
                           employee_name=employee.name, country_code="MY", gross_pay=Decimal("5000"),
                           net_pay=result.net_pay,
                           my_calculation_snapshot=mys.my_payslip_snapshot(result, mys.my_freeze_context(context))))
    db.commit()
    run.my_approval_fingerprint = mys.my_approval_fingerprint(db, run)
    mys.before_run_transition(db, run, PayrollStatus.PAID, ta)
    run.status = PayrollStatus.PAID
    db.commit()
    ids["run"] = run.id
    ids["filing"] = db.query(PayrollMyFiling).filter_by(organization_id=org_a, form_code="EPF_MONTHLY").first().id
    summary = mpp.import_parallel(db, org_a, {
        "runId": run.id, "sourceName": "Incumbent", "reason": "cycle",
        "csv": f"Employee,Gross\n{a1.employee_code},5000.00\n{a2.employee_code},5000.00\n",
        "columnMap": {"employeeCode": "Employee", "gross": "Gross"}}, ta)
    db.commit()
    ids["parallel"] = summary["id"]
    return world, ids, number


_QUERY = {"/leave-entitlement": "?asOf=2026-03-31", "/holidays": "?year=2026"}


def _a_record_paths(world, ids):
    """Every Malaysia GET route that takes a record id, filled with tenant A's
    ids — generated from the router, so a new route is swept automatically."""
    from app.modules.payroll.my_org_router import router

    values = {"employee_id": world.employees["A1"].id, "run_id": ids["run"], "filing_id": ids["filing"],
              "import_id": ids["parallel"]}
    paths = []
    for route in router.routes:
        if "GET" in route.methods and "{" in route.path:
            names = re.findall(r"\{(\w+)\}", route.path)
            missing = [n for n in names if n not in values]
            assert not missing, f"{route.path}: the isolation world has no tenant-A id for {missing}"
            path = route.path.removeprefix("/malaysia").format(**{n: values[n] for n in names})
            paths.append(path + next((q for suffix, q in _QUERY.items() if path.endswith(suffix)), ""))
    return paths


def test_nric_never_leaves_the_vault_except_through_an_approved_reveal(my_world, client):
    world, ids, number = my_world
    db, org_a = world.db, world.orgs["A"].id
    for path in _a_record_paths(world, ids):
        response = client.get(f"/api/payroll/malaysia{path}", headers=world.headers("TA"))
        no_pack = any(path.endswith(q) for q in _QUERY.values())                      # no Active pack -> 400
        assert response.status_code in ((200, 400) if no_pack else (200,)), (path, response.status_code,
                                                                              response.text[:200])
        _absent(number, response.text, f"tenant A's response for {path}")
    for path in ("/filings", "/settlements", "/variances", "/parallel-imports"):
        response = client.get(f"/api/payroll/malaysia{path}", headers=world.headers("TA"))
        assert response.status_code == 200 and (path == "/variances" or response.json()), path
        _absent(number, response.text, path)
    for model in (PayrollMyFiling, PayrollMySettlement, TaxConfigurationAudit, PayrollActivityLog,
                  PayrollMyIdentifierAccessEvent):
        _absent(number, _rows(db, model), model.__tablename__)
    epf = db.get(PayrollMyFiling, ids["filing"]).payload
    member = next(m for m in epf["members"] if m["employeeId"] == world.employees["A1"].id)
    assert member["nricMasked"] and member["nricVaultId"] == ids["vault"]
    # the reveal: requested with a reason, approved by ANOTHER person, used once by the requester
    mys.request_my_identifier_reveal(db, org_a, ids["vault"], "EPF correction needs the full number",
                                     world.users["TA"].id)
    mys.approve_my_identifier_reveal(db, org_a, ids["vault"], world.users["PA"].id)
    db.commit()
    revealed = mys.reveal_my_identifier(db, org_a, ids["vault"], world.users["TA"].id)
    assert number in json.dumps(revealed)
    db.commit()
    with pytest.raises(Exception):
        mys.reveal_my_identifier(db, org_a, ids["vault"], world.users["TA"].id)          # single use
    db.rollback()
    _absent(number, _rows(db, PayrollMyIdentifierAccessEvent), "the access log after a reveal")


def test_a_parallel_file_holding_an_nric_is_refused_without_echo(my_world):
    world, ids, number = my_world
    org_a, a1 = world.orgs["A"].id, world.employees["A1"]
    for header, cell in (("Ref", number), ("NRIC", "x"), ("IC No", "x")):
        with pytest.raises(BadRequestException) as raised:
            mpp.import_parallel(world.db, org_a, {
                "runId": ids["run"], "sourceName": "Incumbent", "reason": "cycle",
                "csv": f"Employee,Gross,{header}\n{a1.employee_code},5000.00,{cell}\n",
                "columnMap": {"employeeCode": "Employee", "gross": "Gross"}}, world.users["TA"].id)
        _absent(number, str(raised.value.detail), "the refusal message")


def test_tenant_b_is_refused_every_tenant_a_record(my_world, client):
    world, ids, number = my_world
    for path in _a_record_paths(world, ids):
        response = client.get(f"/api/payroll/malaysia{path}", headers=world.headers("TB"))
        assert response.status_code in (403, 404), (path, response.status_code)
        _absent(number, response.text, f"tenant B's response for {path}")
    for path in ("/filings", "/settlements", "/variances", "/parallel-imports"):
        response = client.get(f"/api/payroll/malaysia{path}", headers=world.headers("TB"))
        assert response.status_code == 200 and response.json() == [], path
    for path in (f"/identifiers/{ids['vault']}/reveal-request", f"/filings/{ids['filing']}/approve",
                 f"/parallel-imports/{ids['parallel']}/accept", f"/filings/rebuild/{ids['run']}"):
        response = client.post(f"/api/payroll/malaysia{path}", headers=world.headers("TB"), json={"reason": "probe"})
        assert response.status_code in (403, 404), (path, response.status_code)


def test_legal_employers_have_separate_filings_and_liabilities(my_world):
    world, _ids, _number = my_world
    db, org_a = world.db, world.orgs["A"].id
    e1, e2 = world.entities["A-E1"].id, world.entities["A-E2"].id
    epf = {f.legal_entity_id: f for f in db.query(PayrollMyFiling).filter_by(organization_id=org_a,
                                                                              form_code="EPF_MONTHLY")}
    assert set(epf) == {e1, e2}
    assert [m["employeeId"] for m in epf[e1].payload["members"]] == [world.employees["A1"].id]
    assert [m["employeeId"] for m in epf[e2].payload["members"]] == [world.employees["A2"].id]
    assert epf[e1].payload["payer"]["hasilEmployerNo"] != epf[e2].payload["payer"]["hasilEmployerNo"]
    pcb = {s.legal_entity_id: str(s.amount_due) for s in db.query(PayrollMySettlement).filter_by(liability_type="PCB")}
    assert pcb == {e1: "100.00", e2: "100.00"}


def test_journal_refuses_employers_with_different_account_maps(my_world):
    from app.modules.payroll import malaysia_journal as myj
    from app.modules.payroll.models import PayrollMyEmployerRegistration

    world, ids, _number = my_world
    db, org_a = world.db, world.orgs["A"].id
    accounts = {k: f"6{n:03d}" for n, k in enumerate(myj.ACCOUNT_KEYS)}
    rows = db.query(PayrollMyEmployerRegistration).filter_by(organization_id=org_a).order_by("id").all()
    rows[0].my_journal_accounts, rows[1].my_journal_accounts = accounts, {**accounts, "salary_expense": "7000"}
    db.commit()
    journal = myj.build_my_journal(db, org_a, ids["run"])
    assert journal["status"] == "BLOCKED" and "different account maps" in journal["reason"]
    rows[1].my_journal_accounts = accounts
    db.commit()
    assert myj.build_my_journal(db, org_a, ids["run"])["status"] == "READY"
