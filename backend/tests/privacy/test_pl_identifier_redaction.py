"""Poland privacy proof (ZP-PL-ENG-001 §13, PL-025, release gate G5).

A valid PESEL is GENERATED here (check digit computed at run time) — the file
holds no PESEL literal. It is stored in the vault and taken through every
path that handles it: the masked list, the employee summary, the run
preflight, the ZUS filing payloads, settlements, the journal, the vault
access log, the tax audit trail, the activity log and a parallel-run file.
Only the explicit, approved, single-use reveal may return the digits; nothing
else may carry them, in plain or grouped form.

Isolation: through the REAL app and auth chain (the privacy world: tenants A
and B, two legal entities each), tenant B's admin is refused every tenant-A
Poland record, and inside tenant A two legal employers' filings and
liabilities never mix.
"""
import json
import random
import re
from datetime import date
from decimal import Decimal

import pytest

from app.config import settings
from app.core.exceptions import BadRequestException
from app.modules.payroll import poland_filing as plf
from app.modules.payroll import poland_parallel as pp
from app.modules.payroll import poland_service as pls
from app.modules.payroll.employee_validation import pl_pesel_is_valid
from app.modules.payroll.models import (
    PayrollActivityLog, PayrollPlFiling, PayrollPlIdentifierAccessEvent, PayrollPlSettlement, PayrollRun,
    PayrollStatus, PayslipItem, TaxConfigurationAudit,
)

PAY_DATE = date(2026, 3, 31)


def _generated_pesel(seed: int) -> str:
    rng = random.Random(seed)
    while True:
        candidate = f"{rng.randint(50, 99):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}{rng.randint(0, 99999):05d}"
        if pl_pesel_is_valid(candidate):
            return candidate


def _absent(number: str, text: str, where: str):
    for form in (number, f"{number[:6]} {number[6:]}", f"{number[:6]}-{number[6:]}"):
        assert form not in text, f"PESEL found in {where}"


def _rows(db, model, **filters) -> str:
    rows = db.query(model).filter_by(**filters).all()
    return json.dumps([{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows], default=str)


@pytest.fixture()
def pl_world(world, monkeypatch):
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.models import CompanyComplianceDetails
    from tests._pl_engine_helpers import ctx

    monkeypatch.setattr(settings, "PL_TENANT_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "PL_IDENTIFIER_FINGERPRINT_KEY", "p" * 32)
    db = world.db
    for key in ("A", "B"):
        world.orgs[key].country = "Poland"
        db.add(CompanyComplianceDetails(organization_id=world.orgs[key].id, jurisdiction_country="PL"))
    for key in ("A1", "A2", "B1"):
        world.employees[key].country_code = "PL"
    db.commit()
    org_a, a1, a2 = world.orgs["A"].id, world.employees["A1"], world.employees["A2"]
    ta, pa = world.users["TA"].id, world.users["PA"].id
    number = _generated_pesel(424242)
    ids = {"vault": pls.create_pl_identifier(db, org_a, "PESEL", number, ta, employee_id=a1.id).id}
    for n, nip in ((1, "5261040828"), (2, "7680002466")):
        row = pls.record_pl_employer_registration(db, org_a, {
            "effective_from": "2026-01-01", "legal_entity_id": world.entities[f"A-E{n}"].id,
            "legal_name": f"Spółka {n} sp. z o.o.", "nip": nip, "zus_deadline_class": "DAY_15"}, ta, "setup")
        pls.approve_pl_employer_registration(db, org_a, row.id, pa)
        pls.verify_pl_employer_registration(db, org_a, row.id, pa, "verified", "checked against KRS")
    for employee in (a1, a2):
        row = pls.record_pl_worker_profile(db, org_a, employee.id, {
            "effective_from": "2026-01-01", "contract_type": "umowa_o_prace", "insurance_title_code": "011000",
            "pay_frequency": "monthly", "fte_numerator": 1, "fte_denominator": 1}, ta, "hire")
        pls.approve_pl_worker_profile(db, org_a, row.id, pa)
    run = PayrollRun(organization_id=org_a, period_label="Mar 2026", period_start=date(2026, 3, 1),
                     period_end=PAY_DATE, pay_date=PAY_DATE, status="Processed")
    db.add(run)
    db.flush()
    for employee in (a1, a2):
        context = ctx()
        result = calculate_payroll(context, "standard")
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=org_a,
                           employee_name=employee.name, country_code="PL", gross_pay=Decimal("8000"),
                           net_pay=result.net_pay,
                           pl_calculation_snapshot=pls.pl_payslip_snapshot(result, pls.pl_freeze_context(context))))
    db.commit()
    run.pl_approval_fingerprint = pls.pl_approval_fingerprint(db, run)
    pls.before_run_transition(db, run, PayrollStatus.PAID, ta)
    run.status = PayrollStatus.PAID
    db.commit()
    ids["run"] = run.id
    ids["filing"] = db.query(PayrollPlFiling).filter_by(organization_id=org_a, form_code="RCA").first().id
    summary = pp.import_parallel(db, org_a, {
        "runId": run.id, "sourceName": "Incumbent", "reason": "cycle",
        "csv": f"Employee,Gross\n{a1.employee_code},8000.00\n{a2.employee_code},8000.00\n",
        "columnMap": {"employeeCode": "Employee", "gross": "Gross"}}, ta)
    db.commit()
    ids["parallel"] = summary["id"]
    return world, ids, number


_QUERY = {"/annual-cap": "?year=2026", "/leave-entitlement": "?asOf=2026-03-31"}


def _a_record_paths(world, ids):
    """Every Poland GET route that takes a record id, filled with tenant A's
    ids — generated from the router, so a new route is swept automatically."""
    from app.modules.payroll.pl_org_router import router

    values = {"employee_id": world.employees["A1"].id, "run_id": ids["run"], "filing_id": ids["filing"],
              "import_id": ids["parallel"]}
    paths = []
    for route in router.routes:
        if "GET" in route.methods and "{" in route.path:
            names = re.findall(r"\{(\w+)\}", route.path)
            missing = [n for n in names if n not in values]
            assert not missing, f"{route.path}: the isolation world has no tenant-A id for {missing}"
            path = route.path.removeprefix("/poland").format(**{n: values[n] for n in names})
            paths.append(path + next((q for suffix, q in _QUERY.items() if path.endswith(suffix)), ""))
    return paths


def test_pesel_never_leaves_the_vault_except_through_an_approved_reveal(pl_world, client):
    world, ids, number = pl_world
    db, org_a = world.db, world.orgs["A"].id
    for path in _a_record_paths(world, ids):
        response = client.get(f"/api/payroll/poland{path}", headers=world.headers("TA"))
        expected = (200, 400) if path.endswith(_QUERY["/leave-entitlement"]) else (200,)  # no Active pack -> 400
        assert response.status_code in expected, (path, response.status_code, response.text[:200])
        _absent(number, response.text, f"tenant A's response for {path}")
        assert "GB00SYNTH12345678" not in response.text, path
    for path in ("/filings", "/settlements", "/variances", "/parallel-imports"):
        response = client.get(f"/api/payroll/poland{path}", headers=world.headers("TA"))
        assert response.status_code == 200 and (path == "/variances" or response.json()), path
        _absent(number, response.text, path)
    for model in (PayrollPlFiling, PayrollPlSettlement, TaxConfigurationAudit, PayrollActivityLog,
                  PayrollPlIdentifierAccessEvent):
        _absent(number, _rows(db, model), model.__tablename__)
    rca = db.get(PayrollPlFiling, ids["filing"]).payload
    assert rca["insured"][0]["peselMasked"] and rca["insured"][0]["peselVaultId"] == ids["vault"]
    # the reveal: requested with a reason, approved by ANOTHER person, used once by the requester
    pls.request_pl_identifier_reveal(db, org_a, ids["vault"], "ZUS correction needs the full number",
                                     world.users["TA"].id)
    pls.approve_pl_identifier_reveal(db, org_a, ids["vault"], world.users["PA"].id)
    db.commit()
    revealed = pls.reveal_pl_identifier(db, org_a, ids["vault"], world.users["TA"].id)
    assert number in json.dumps(revealed)
    db.commit()
    with pytest.raises(Exception):
        pls.reveal_pl_identifier(db, org_a, ids["vault"], world.users["TA"].id)          # single use
    db.rollback()
    _absent(number, _rows(db, PayrollPlIdentifierAccessEvent), "the access log after a reveal")


def test_a_parallel_file_holding_a_pesel_is_refused_without_echo(pl_world):
    world, ids, number = pl_world
    org_a, a1 = world.orgs["A"].id, world.employees["A1"]
    with pytest.raises(BadRequestException) as raised:
        pp.import_parallel(world.db, org_a, {
            "runId": ids["run"], "sourceName": "Incumbent", "reason": "cycle",
            "csv": f"Employee,Gross,Ref\n{a1.employee_code},8000.00,{number}\n",
            "columnMap": {"employeeCode": "Employee", "gross": "Gross"}}, world.users["TA"].id)
    assert "PESEL" in str(raised.value.detail)
    _absent(number, str(raised.value.detail), "the refusal message")


def test_tenant_b_is_refused_every_tenant_a_record(pl_world, client):
    world, ids, number = pl_world
    for path in _a_record_paths(world, ids):
        response = client.get(f"/api/payroll/poland{path}", headers=world.headers("TB"))
        assert response.status_code in (403, 404), (path, response.status_code)
        _absent(number, response.text, f"tenant B's response for {path}")
    for path in ("/filings", "/settlements", "/variances", "/parallel-imports"):
        response = client.get(f"/api/payroll/poland{path}", headers=world.headers("TB"))
        assert response.status_code == 200 and response.json() == [], path
    for path in (f"/identifiers/{ids['vault']}/reveal-request", f"/filings/{ids['filing']}/approve",
                 f"/parallel-imports/{ids['parallel']}/accept", f"/filings/rebuild/{ids['run']}"):
        response = client.post(f"/api/payroll/poland{path}", headers=world.headers("TB"), json={"reason": "probe"})
        assert response.status_code in (403, 404), (path, response.status_code)


def test_legal_employers_have_separate_filings_and_liabilities(pl_world):
    world, _ids, _number = pl_world
    db, org_a = world.db, world.orgs["A"].id
    e1, e2 = world.entities["A-E1"].id, world.entities["A-E2"].id
    rca = {f.legal_entity_id: f for f in db.query(PayrollPlFiling).filter_by(organization_id=org_a, form_code="RCA")}
    assert set(rca) == {e1, e2}
    assert [i["employeeId"] for i in rca[e1].payload["insured"]] == [world.employees["A1"].id]
    assert [i["employeeId"] for i in rca[e2].payload["insured"]] == [world.employees["A2"].id]
    assert rca[e1].payload["payer"]["nip"] != rca[e2].payload["payer"]["nip"]
    pit = {s.legal_entity_id: str(s.amount_due) for s in db.query(PayrollPlSettlement).filter_by(liability_type="PIT")}
    assert pit == {e1: "513.00", e2: "513.00"}


def test_a_mixed_employer_parallel_cycle_counts_for_no_single_employer(pl_world):
    world, ids, _number = pl_world
    summary = pp.parallel_summary(world.db, world.orgs["A"].id, ids["parallel"])
    assert summary["legalEntityId"] is None and summary["clean"]


def test_journal_refuses_employers_with_different_account_maps(pl_world):
    from app.modules.payroll import poland_journal as plj
    from app.modules.payroll.models import PayrollPlEmployerRegistration

    world, ids, _number = pl_world
    db, org_a = world.db, world.orgs["A"].id
    accounts = {k: f"6{n:03d}" for n, k in enumerate(plj.ACCOUNT_KEYS)}
    rows = db.query(PayrollPlEmployerRegistration).filter_by(organization_id=org_a).order_by("id").all()
    rows[0].pl_journal_accounts, rows[1].pl_journal_accounts = accounts, {**accounts, "salary_expense": "7000"}
    db.commit()
    journal = plj.build_pl_journal(db, org_a, ids["run"])
    assert journal["status"] == "BLOCKED" and "different account maps" in journal["reason"]
    rows[1].pl_journal_accounts = accounts
    db.commit()
    assert plj.build_pl_journal(db, org_a, ids["run"])["status"] == "READY"
