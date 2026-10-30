"""
tests/test_multi_country_payroll_e2e.py
-----------------------------------------
End to end, through the real API: an organization on the Professional plan
(3 countries) adds two countries to its registration country under
Compliance > Countries, has one employee in each, and runs one month of
payroll. Everything that month produces must follow each employee's own
country — never the org's default:

  * each payslip is calculated by, and stamped with, the employee's country
    (India-only Professional Tax appears on the India payslip only);
  * each payslip PDF is in that country's currency;
  * the run's totals are reported per country, each in its own currency;
  * bank transfer files are one per country (a mixed file is refused);
  * the payroll register (PDF and CSV) has one section per country;
  * the dashboard breaks the month down per country;
  * every country's public holidays are seeded.

Hermetic like test_country_entitlement.py (own SQLite file, env set before
importing app.main) and run with BILLING_ENFORCEMENT_MODE=enforce.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="multi_country_e2e_")
os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.sqlite3')}"
os.environ["ENVIRONMENT"] = "development"
os.environ["ASSIST_MODEL_PROVIDER"] = ""
os.environ["ASSIST_MODEL_BASE_URL"] = ""
os.environ["ASSIST_MODEL_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_FROM_EMAIL"] = ""
os.environ["ASSIST_SUPPORT_EMAIL"] = ""
os.environ["ASSIST_SWEEP_ENABLED"] = "false"
os.environ["TRIAL_SWEEP_ENABLED"] = "false"
_ENV_MODE_BEFORE = os.environ.get("BILLING_ENFORCEMENT_MODE")
os.environ["BILLING_ENFORCEMENT_MODE"] = "enforce"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_app_modules = {
    _mod: _module
    for _mod, _module in sys.modules.items()
    if _mod == "app" or _mod.startswith("app.")
}
for _mod in list(_saved_app_modules):
    del sys.modules[_mod]

import csv  # noqa: E402
import io  # noqa: E402
from datetime import date, datetime, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app.main import app  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from app.modules.auth.models import User, UserRole  # noqa: E402
from app.modules.billing import plan_catalog  # noqa: E402
from app.modules.billing.feature_keys import (  # noqa: E402
    MAX_BWM, MAX_ENTITIES, MAX_JURISDICTIONS, MAX_SCHEDULES, PAYROLL_RUNS,
)
from app.modules.billing.models import BillingAuthority, BillingSubscription, SubscriptionStatus  # noqa: E402
from app.modules.organizations.models import Organization  # noqa: E402
from app.modules.payroll.models import (  # noqa: E402
    CompanyComplianceDetails, ContributionRate, PayrollHoliday, PayslipItem,
)

from sqlalchemy.engine import make_url as _make_url  # noqa: E402
from tests._mfa_login import mfa_login  # noqa: E402

assert _make_url(engine.url).get_backend_name() == "sqlite"


@sa.event.listens_for(engine, "connect")
def _register_pg_advisory_lock(dbapi_connection, connection_record):
    # code_generation.py takes a PostgreSQL-only advisory lock; a no-op on
    # SQLite (same stub as test_bulk_employees.py).
    dbapi_connection.create_function("pg_advisory_xact_lock", 1, lambda key: 1)


engine.dispose()
Base.metadata.create_all(bind=engine)
initialize_database()

_db = SessionLocal()

_super = User(email="mc-super@example.com", hashed_password=hash_password("strong-password"),
              role=UserRole.SUPER_ADMIN, first_name="Super", last_name="Admin", organization_id=None, is_active=True)
_db.add(_super)
_db.flush()

_PRO_FLAGS = {PAYROLL_RUNS: None, MAX_ENTITIES: 3, MAX_JURISDICTIONS: 3, MAX_SCHEDULES: 10, MAX_BWM: 1000}
_plan = plan_catalog.create_plan(_db, "PROFESSIONAL", "Professional", actor_user_id=_super.id)
_version = plan_catalog.create_plan_version(
    _db, plan_id=_plan.id, feature_set={"features": list(_PRO_FLAGS)},
    scale_limits={k: v for k, v in _PRO_FLAGS.items() if k != PAYROLL_RUNS}, actor_user_id=_super.id,
)
for _key, _limit in _PRO_FLAGS.items():
    plan_catalog.add_entitlement_flag(_db, _version.id, _key, _limit, actor_user_id=_super.id)
plan_catalog.approve_plan_version(_db, _version.id, actor_user_id=_super.id)
_version = plan_catalog.publish_plan_version(_db, _version.id, published_by_user_id=_super.id)

# A 30-day Professional evaluation registered in India (trials run on the
# Professional plan version: 3 countries).
_org = Organization(organization_name="Tri-Country Co", organization_code="TRICO",
                    workspace_type="EVALUATION", country="India")
_db.add(_org)
_db.flush()
_db.add(User(email="trico@example.com", hashed_password=hash_password("strong-password"), role=UserRole.ORG_ADMIN,
             first_name="Org", last_name="Admin", organization_id=_org.id, is_active=True))
_db.add(BillingSubscription(
    organization_id=_org.id, plan_version_id=_version.id, billing_authority=BillingAuthority.STANDALONE.value,
    status=SubscriptionStatus.TRIALING.value, current_period_start=datetime.utcnow() - timedelta(days=2),
    current_period_end=datetime.utcnow() + timedelta(days=28),
))
_db.add(CompanyComplianceDetails(organization_id=_org.id, name="Tri-Country Co",
                                 jurisdiction_country="IN", jurisdiction_state="Maharashtra"))
# Maharashtra Professional Tax: an India-only, state-scoped component.
_db.add(ContributionRate(
    organization_id=None, jurisdiction_country="IN", jurisdiction_state="Maharashtra", component_key="pt",
    label="pt", employee_share="—", employer_share="—", total="—", flat_amount=Decimal("200"),
))
_db.commit()
_ORG_ID = _org.id

for _mod in list(sys.modules):
    if _mod == "app" or _mod.startswith("app."):
        del sys.modules[_mod]
sys.modules.update(_saved_app_modules)
del _saved_app_modules
if _ENV_MODE_BEFORE is None:
    os.environ.pop("BILLING_ENFORCEMENT_MODE", None)
else:
    os.environ["BILLING_ENFORCEMENT_MODE"] = _ENV_MODE_BEFORE


@pytest.fixture(scope="module", autouse=True)
def _runtime_enforce():
    """Lazily-imported app modules may resolve another test file's settings
    object after the sys.modules swap — enforce there too, for this module
    only (same as test_country_entitlement.py)."""
    import app.config as runtime_config

    targets = {id(settings): settings, id(runtime_config.settings): runtime_config.settings}
    previous = {key: s.BILLING_ENFORCEMENT_MODE for key, s in targets.items()}
    for s in targets.values():
        s.BILLING_ENFORCEMENT_MODE = "enforce"
    yield
    for key, s in targets.items():
        s.BILLING_ENFORCEMENT_MODE = previous[key]


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def headers(client):
    login = mfa_login(client, json={"email": "trico@example.com", "password": "strong-password"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


_STATE: dict = {}

_EMPLOYEES = {
    "IN": {"employee_code": "TRI-IN", "name": "Asha India", "email": "asha@tri.example.com", "country_code": "IN",
           "work_state": "Maharashtra", "ctc": 1200000, "compliance_fields": {}},
    "US": {"employee_code": "TRI-US", "name": "Sam States", "email": "sam@tri.example.com", "country_code": "US",
           "ctc": 96000, "compliance_fields": {"ssn": "123-45-6789", "flsa_status": "Exempt",
                                               "state_tax_jurisdiction": "TX"}},
    "UK": {"employee_code": "TRI-UK", "name": "Jane Kingdom", "email": "jane@tri.example.com", "country_code": "UK",
           "ctc": 60000, "compliance_fields": {"nino": "TN123456C", "paye_tax_code": "1257L", "sort_code": "40-12-34"}},
}


def test_01_org_selects_three_countries_and_is_refused_a_fourth(client, headers):
    r = client.get("/api/payroll/jurisdictions/entitled", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["used"] == 1 and r.json()["limit"] == 3
    for code in ("US", "UK"):
        r = client.post("/api/payroll/jurisdictions/entitled", headers=headers, json={"countryCode": code})
        assert r.status_code == 200, r.text
    body = r.json()
    assert [c["code"] for c in body["countries"]] == ["IN", "US", "UK"]
    assert body["used"] == 3 and body["canAdd"] is False
    r = client.post("/api/payroll/jurisdictions/entitled", headers=headers, json={"countryCode": "AU"})
    assert r.status_code == 403, r.text


def test_02_every_country_gets_its_own_public_holidays(client, headers):
    r = client.get("/api/payroll/holidays", headers=headers, params={"year": 2026})
    assert r.status_code == 200, r.text
    seeded = {row[0] for row in _db.query(PayrollHoliday.country).filter(
        PayrollHoliday.organization_id == _ORG_ID).distinct()}
    assert {"IN", "US", "UK"} <= seeded, seeded


def test_03_one_employee_per_country(client, headers):
    ids = {}
    for code, payload in _EMPLOYEES.items():
        r = client.post("/api/payroll/employees", headers=headers, json={
            **payload, "department": "Engineering", "designation": "Engineer",
            "date_of_joining": "2025-01-01", "status": "Active",
        })
        assert r.status_code == 200, (code, r.text)
        assert r.json()["countryCode"] == code
        ids[code] = r.json()["id"]
    _STATE["employees"] = ids


def test_04_month_run_calculates_each_employee_by_their_own_country(client, headers):
    r = client.post("/api/payroll/runs", headers=headers, json={
        "periodStart": "2026-01-01", "periodEnd": "2026-01-31", "payDate": "2026-01-31",
        "attendanceOverrideReason": "E2E test: attendance is not tracked for this synthetic company.",
    })
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    _STATE["run_id"] = run_id

    _db.expire_all()
    items = {i.employee_id: i for i in _db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run_id)}
    ids = _STATE["employees"]
    assert set(items) == set(ids.values())
    for code, emp_id in ids.items():
        item = items[emp_id]
        assert item.country_code == code, (code, item.country_code, item.notes)
        assert item.status != "Failed", (code, item.notes)
        assert item.gross_pay and item.gross_pay > 0, code
    _STATE["items"] = {code: items[emp_id] for code, emp_id in ids.items()}
    # India's state Professional Tax lands on the India payslip only.
    assert items[ids["IN"]].professional_tax == Decimal("200")
    assert not items[ids["US"]].professional_tax
    assert not items[ids["UK"]].professional_tax
    # US / UK statutory lines come from their own engines.
    assert items[ids["US"]].social_security and items[ids["US"]].social_security > 0
    assert items[ids["UK"]].ni_employee is not None


def test_05_run_detail_and_payslip_list_are_per_country(client, headers):
    run_id = _STATE["run_id"]
    r = client.get(f"/api/payroll/runs/{run_id}", headers=headers)
    assert r.status_code == 200, r.text
    by_country = {row["country"]: row for row in r.json()["totalsByCountry"]}
    assert set(by_country) == {"IN", "US", "UK"}
    assert {c: row["currency"] for c, row in by_country.items()} == {"IN": "INR", "US": "USD", "UK": "GBP"}
    for code, item in _STATE["items"].items():
        assert Decimal(str(by_country[code]["totalNet"])) == item.net_pay
        assert by_country[code]["employeeCount"] == 1

    r = client.get(f"/api/payroll/runs/{run_id}/items", headers=headers)
    assert r.status_code == 200, r.text
    assert {row["employeeId"]: row["country"] for row in r.json()} == {
        _STATE["employees"][c]: c for c in ("IN", "US", "UK")}


def test_06_each_payslip_pdf_is_in_its_own_currency(client, headers):
    expected = {"IN": "INR", "US": "USD", "UK": "GBP"}
    symbols = {"IN": ("₹", "INR", "Rs"), "US": ("$", "USD"), "UK": ("£", "GBP")}
    for code, item in _STATE["items"].items():
        r = client.get(f"/api/payroll/payslips/{item.id}/download", headers=headers)
        assert r.status_code == 200, (code, r.text[:300])
        text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(r.content)).pages)
        assert any(sym in text for sym in symbols[code]), (code, expected[code], text[:400])
        others = [c for c in symbols if c != code]
        assert item.employee_name in text
        for other in others:
            assert _STATE["items"][other].employee_name not in text


def test_06b_uk_payslip_has_the_uk_layout(client, headers):
    """A UK payslip carries what UK employees and HMRC rely on — NI number
    and category, tax code and basis, tax period, employer references, year
    to date, employer NI/pension — and none of India's layout (HRA, NEFT,
    amount in words)."""
    item = _STATE["items"]["UK"]
    r = client.get(f"/api/payroll/payslips/{item.id}/download", headers=headers)
    assert r.status_code == 200, r.text[:300]
    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(r.content)).pages)
    for expected in ("NI number", "NI category", "Tax code", "Tax basis", "Tax period", "Pay date",
                     "Employer PAYE ref", "Accounts Office ref", "Year to date", "Employer National Insurance",
                     "Income tax (PAYE)", "National Insurance", "BACS", "NET PAY"):
        assert expected in text, (expected, text[:600])
    for india_only in ("House Rent Allowance", "NEFT", "in Words", "Salary Month"):
        assert india_only not in text, (india_only, text[:600])

    r = client.get(f"/api/payroll/payslips/{item.id}", headers=headers)
    assert r.status_code == 200, r.text
    uk = r.json()["ukPayslip"]
    assert uk["taxBasis"] in ("Cumulative", "Week 1/Month 1")
    assert 1 <= uk["taxMonth"] <= 12 and "/" in uk["taxYear"]
    assert Decimal(str(uk["ytd"]["net"])) >= item.net_pay
    # Other countries' payslips carry no UK block.
    r = client.get(f"/api/payroll/payslips/{_STATE['items']['IN'].id}", headers=headers)
    assert r.json().get("ukPayslip") is None


def test_07_bank_files_are_one_per_country_in_its_own_currency(client, headers):
    run_id = _STATE["run_id"]
    r = client.get(f"/api/payroll/runs/{run_id}/bank-transfer-summary", headers=headers)
    assert r.status_code == 200, r.text
    assert [c["country"] for c in r.json()["countries"]] == ["IN", "US", "UK"]

    r = client.get(f"/api/payroll/runs/{run_id}/bank-transfer-file", headers=headers, params={"format": "csv"})
    assert r.status_code == 400, r.text
    assert "3 countries" in r.text

    for code, currency in (("IN", "INR"), ("US", "USD"), ("UK", "GBP")):
        r = client.get(f"/api/payroll/runs/{run_id}/bank-transfer-file", headers=headers,
                       params={"format": "csv", "country": code})
        assert r.status_code == 200, (code, r.text)
        assert f"_{code}." in r.headers["content-disposition"]
        body = r.content.decode("utf-8")
        assert _STATE["items"][code].employee_name in body
        for other in {"IN", "US", "UK"} - {code}:
            assert _STATE["items"][other].employee_name not in body
        if currency != "INR":  # India's NACH-style CSV keeps its legacy byte-identical layout
            assert currency in body, (code, body[:300])


def test_08_payroll_register_has_one_section_per_country(client, headers):
    from app.modules.payroll import service

    run_id = _STATE["run_id"]
    pdf = service.generate_report_pdf_bytes(_db, run_id, _ORG_ID)
    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    for label in ("India — amounts in INR", "United States — amounts in USD", "United Kingdom — amounts in GBP"):
        assert label in text, (label, text[:500])

    rows = list(csv.reader(io.StringIO(service.generate_report_csv_bytes(_db, run_id, _ORG_ID).decode("utf-8"))))
    headers_rows = [r for r in rows if r and r[0].startswith("Country:")]
    assert [r[1] for r in headers_rows] == ["Currency: INR", "Currency: USD", "Currency: GBP"]


def test_09_dashboard_breaks_the_month_down_per_country(client, headers):
    r = client.get("/api/payroll/dashboard/summary", headers=headers, params={"year": 2026, "month": 1})
    assert r.status_code == 200, r.text
    by_country = {row["country"]: row for row in r.json()["byCountry"]}
    assert {c: row["currency"] for c, row in by_country.items()} == {"IN": "INR", "US": "USD", "UK": "GBP"}
    for code, item in _STATE["items"].items():
        assert Decimal(str(by_country[code]["totalNet"])) == item.net_pay


def test_10_statutory_reports_cover_every_country_and_only_that_countrys_employees(client, headers):
    """The report list offers each payroll country's reports; a country's
    report validates against, and is built from, that country's payslips."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, ReportTemplate

    for country, key, rtype, name in (("IN", "IN-TDS", "TDS", "Salary TDS"), ("UK", "UK-P32", "P32", "Employer P32"),
                                      ("AU", "AU-STP", "STP", "Single Touch")):
        _db.add(ReportTemplate(template_key=key, name=name, report_type=rtype, jurisdiction_country=country,
                               reporting_year="2026", version="1.0", status="Active"))
    _db.commit()

    r = client.get("/api/payroll/report-templates/available", headers=headers, params={"reportingYear": "2026"})
    assert r.status_code == 200, r.text
    offered = {(row["country"], row["reportType"]) for row in r.json()}
    assert offered == {("IN", "TDS"), ("UK", "P32")}  # not AU: not one of the org's countries

    run = _db.query(PayrollRun).filter(PayrollRun.id == _STATE["run_id"]).one()
    uk_template = _db.query(ReportTemplate).filter(ReportTemplate.template_key == "UK-P32").one()
    validation = service.validate_report_generation_context(_db, _ORG_ID, uk_template, run)
    assert validation["jurisdictionMatch"] is True, validation["reasons"]

    view = service._country_run_view(_db, run, "UK", _ORG_ID)
    assert [i.employee_name for i in view.payslip_items] == [_STATE["items"]["UK"].employee_name]
    assert view.total_net == _STATE["items"]["UK"].net_pay


def test_10b_reports_list_shows_every_country_of_the_run(client, headers):
    from app.modules.payroll.models import PayrollRun

    run = _db.get(PayrollRun, _STATE["run_id"])
    status = run.status
    run.status = "Review"  # the reports list skips Draft runs
    _db.commit()
    try:
        r = client.get("/api/payroll/reports", headers=headers)
    finally:
        run.status = status
        _db.commit()
    assert r.status_code == 200, r.text
    report = next(x for x in r.json() if x["id"] == _STATE["run_id"])
    by_country = {c["country"]: c for c in report["countries"]}
    assert {c: row["currency"] for c, row in by_country.items()} == {"IN": "INR", "US": "USD", "UK": "GBP"}
    for code, item in _STATE["items"].items():
        assert by_country[code]["employeeCount"] == 1
        assert Decimal(str(by_country[code]["totalNet"])) == item.net_pay


def test_11_runs_list_and_preview_report_each_country_in_its_own_currency(client, headers):
    r = client.get("/api/payroll/runs", headers=headers)
    assert r.status_code == 200, r.text
    run = next(row for row in r.json() if row["id"] == _STATE["run_id"])
    by_country = {row["country"]: row for row in run["totalsByCountry"]}
    assert {c: row["currency"] for c, row in by_country.items()} == {"IN": "INR", "US": "USD", "UK": "GBP"}
    for code, item in _STATE["items"].items():
        assert Decimal(str(by_country[code]["totalNet"])) == item.net_pay

    r = client.post("/api/payroll/runs/preview", headers=headers, json={
        "employeeIds": list(_STATE["employees"].values()), "country": "IN",
        "periodStart": "2026-01-01", "periodEnd": "2026-01-31", "payDate": "2026-01-31",
    })
    assert r.status_code == 200, r.text
    preview = {row["country"]: row for row in r.json()["totalsByCountry"]}
    assert {c: row["currency"] for c, row in preview.items()} == {"IN": "INR", "US": "USD", "UK": "GBP"}
    assert all(row["count"] == 1 for row in preview.values())


def test_12_subscription_shows_country_usage_and_downgrade_impact(client, headers):
    from app.modules.billing.jurisdiction_entitlement import plan_change_impact

    r = client.get("/api/billing/my-subscription", headers=headers)
    assert r.status_code == 200, r.text
    usage = r.json()["country_usage"]
    assert usage["used"] == 3 and usage["limit"] == 3
    assert [c["code"] for c in usage["countries"]] == ["IN", "US", "UK"]

    # A Core plan (1 country) would keep India and pause the US and UK.
    core = plan_catalog.create_plan(_db, "CORE", "Core", actor_user_id=_super.id)
    core_flags = {**_PRO_FLAGS, MAX_JURISDICTIONS: 1}
    cv = plan_catalog.create_plan_version(_db, plan_id=core.id, feature_set={"features": list(core_flags)},
                                          scale_limits={MAX_JURISDICTIONS: 1}, actor_user_id=_super.id)
    for key, limit in core_flags.items():
        plan_catalog.add_entitlement_flag(_db, cv.id, key, limit, actor_user_id=_super.id)
    plan_catalog.approve_plan_version(_db, cv.id, actor_user_id=_super.id)
    plan_catalog.publish_plan_version(_db, cv.id, published_by_user_id=_super.id)

    r = client.get("/api/billing/plan-change-impact", headers=headers, params={"plan_code": "CORE"})
    assert r.status_code == 200, r.text
    impact = r.json()
    assert impact["newLimit"] == 1 and impact["keep"] == ["IN"] and impact["pause"] == ["US", "UK"]
    assert plan_change_impact(_db, _ORG_ID, "PROFESSIONAL")["pause"] == []


def test_13_preview_rows_name_the_country_engine_used(client, headers):
    r = client.post("/api/payroll/runs/preview", headers=headers, json={
        "employeeIds": list(_STATE["employees"].values()), "country": "IN",
        "periodStart": "2026-01-01", "periodEnd": "2026-01-31", "payDate": "2026-01-31",
    })
    assert r.status_code == 200, r.text
    assert {row["employeeId"]: row["country"] for row in r.json()["employees"]} == {
        emp_id: code for code, emp_id in _STATE["employees"].items()}
