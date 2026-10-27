"""Mexico dedicated report generators (completion W4-2 = Phase 12b):
mexico_report_service. Every report is built from Mexico's own service views
(never recomputed), persisted immutable with supersession, labelled "not an
official file" where the official layout's source is not saved, and carries
no full RFC / CURP / NSS (MX-061). SYNTHETIC worlds only."""

import json
from datetime import date

import pytest

DEDICATED = {"MX-CFDI-STATUS": "MX_CFDI_STATUS", "MX-ISR-MONTHLY": "MX_ISR_WITHHOLDING",
             "MX-IDSE-MOVEMENTS": "MX_IDSE", "MX-SUA-RECON": "MX_SUA", "MX-SIPARE": "MX_SIPARE",
             "MX-VACATION-ACCRUAL": "MX_VACATION", "MX-PTU-DISTRIBUTION": "MX_PTU",
             "MX-ISN-RETURN-CDMX": "MX_ISN_RETURN"}


def _seed(db):
    from scripts.seed_statutory_report_templates import seed_mexico

    seed_mexico(db, manifest={})
    from app.modules.payroll.models import ReportTemplate

    return {t.template_key: t for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "MX")}


def _active(db, template):
    """Mexico template activation is W4-3's gate; these tests set the state directly."""
    template.status = "Active"
    db.commit()
    return template


def _R():
    from app.modules.payroll import mexico_report_service

    return mexico_report_service


def _world(db, monkeypatch, code):
    from tests import _mx_authority_helpers as ah

    w = ah.committed_world(db, monkeypatch, code=code)
    s = ah.svc()
    s.F.accrue(db, w.org.id, w.users[0].id)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    s.F.open_sua_period(db, w.org.id, w.registration.id, "2026-06", w.users[0].id)
    s.F.draft_isn_return(db, w.org.id, "CDMX", "2026-06", w.users[0].id)
    return w


def _params(key, w):
    return {"MX-ISR-MONTHLY": {"period_key": "2026-06"}, "MX-SUA-RECON": {"period_key": "2026-06"},
            "MX-SIPARE": {"period_key": "2026-06"}, "MX-ISN-RETURN-CDMX": {"period_key": "2026-06"}}.get(key, {})


def test_the_generic_generator_refuses_every_dedicated_type(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from tests import _mx_authority_helpers as ah

    w = ah.committed_world(db, monkeypatch, code="MXGEN0")
    templates = _seed(db)
    assert set(service.MX_DEDICATED_GENERATOR_REPORT_TYPES) >= set(DEDICATED.values())
    for key in DEDICATED:
        t = _active(db, templates[key])
        with pytest.raises(BadRequestException, match="dedicated Mexico generator"):
            service.generate_report_from_template(db, w.org.id, t.id, w.run.id, reporting_period="x", actor_id=None)


def test_each_dedicated_report_is_built_from_the_service_views(db, monkeypatch):
    w = _world(db, monkeypatch, "MXGEN1")
    templates = _seed(db)
    for key, rtype in DEDICATED.items():
        if key == "MX-PTU-DISTRIBUTION":
            continue                                             # needs a cycle: its own test below
        out = _R().mx_report_generate(db, w.org.id, _active(db, templates[key]).id, _params(key, w), w.users[0].id)
        assert out["reportType"] == rtype and out["status"] == "Generated", key
        data = out["renderedData"]["data"]
        assert data, key
    isr = _R().mx_report_generate(db, w.org.id, templates["MX-ISR-MONTHLY"].id, {"period_key": "2026-06"}, None)
    liabilities = isr["renderedData"]["data"]["liabilities"]
    assert liabilities and {l["authority"] for l in liabilities} == {"SAT_ISR"} and liabilities[0]["sources"]
    sipare = _R().mx_report_generate(db, w.org.id, templates["MX-SIPARE"].id, {"period_key": "2026-06"}, None)
    assert {l["authority"] for l in sipare["renderedData"]["data"]["liabilities"]} <= {"IMSS", "INFONAVIT"}
    idse = _R().mx_report_generate(db, w.org.id, templates["MX-IDSE-MOVEMENTS"].id, {}, None)
    assert idse["renderedData"]["data"]["movements"]


def test_official_layout_reports_say_they_are_not_official_files(db, monkeypatch):
    w = _world(db, monkeypatch, "MXGEN2")
    templates = _seed(db)
    for key in ("MX-ISR-MONTHLY", "MX-IDSE-MOVEMENTS", "MX-SUA-RECON", "MX-SIPARE", "MX-ISN-RETURN-CDMX"):
        out = _R().mx_report_generate(db, w.org.id, _active(db, templates[key]).id, _params(key, w), None)
        assert "NOT AN OFFICIAL FILE" in out["officialLayout"], key
        assert out["renderedData"]["officialLayout"] == out["officialLayout"]


def test_regenerating_supersedes_the_previous_report_never_edits_it(db, monkeypatch):
    from app.modules.payroll.models import GeneratedReport

    w = _world(db, monkeypatch, "MXGEN3")
    t = _active(db, _seed(db)["MX-ISR-MONTHLY"])
    first = _R().mx_report_generate(db, w.org.id, t.id, {"period_key": "2026-06"}, None)
    second = _R().mx_report_generate(db, w.org.id, t.id, {"period_key": "2026-06"}, None)
    old = db.get(GeneratedReport, first["reportId"])
    assert old.status == "Superseded" and second["renderedData"]["supersedesReportIds"] == [first["reportId"]]
    assert db.get(GeneratedReport, second["reportId"]).status == "Generated"


def test_no_report_carries_a_full_identifier(db, monkeypatch):
    """MX-061: a scan of every rendered report for the worker's full RFC / CURP / NSS."""
    w = _world(db, monkeypatch, "MXGEN4")
    templates = _seed(db)
    ids = [v for k, v in (w.employee.compliance_fields or {}).items() if k in ("rfc", "curp", "nss") and v]
    assert ids                                                    # the synthetic worker has them
    for key in DEDICATED:
        if key == "MX-PTU-DISTRIBUTION":
            continue
        out = _R().mx_report_generate(db, w.org.id, _active(db, templates[key]).id, _params(key, w), None)
        blob = json.dumps(out["renderedData"], default=str)
        assert not any(i in blob for i in ids), key


def test_missing_parameters_and_wrong_templates_are_refused(db, monkeypatch):
    from app.core.exceptions import BadRequestException

    w = _world(db, monkeypatch, "MXGEN5")
    templates = _seed(db)
    with pytest.raises(BadRequestException, match="period_key"):
        _R().mx_report_generate(db, w.org.id, _active(db, templates["MX-SUA-RECON"]).id, {}, None)
    with pytest.raises(BadRequestException):
        _R().mx_report_generate(db, w.org.id, templates["MX-CFDI-STATUS"].id, {}, None)      # still Draft
    with pytest.raises(BadRequestException):                       # a template-engine type, not dedicated
        _R().mx_report_generate(db, w.org.id, _active(db, templates["MX-PAYROLL-REGISTER"]).id, {}, None)


def test_the_annual_adjustment_employer_year_view(db, monkeypatch):
    from tests import test_mexico_annual_adjustment as A

    A._rules(monkeypatch)
    wa = A._world(db, monkeypatch, "MXGEN6")
    A._approved(db, wa)
    t = _active(db, _seed(db)["MX-ANNUAL-ISR-ADJ"])
    out = _R().mx_report_generate(db, wa.org.id, t.id, A._key(wa), None)
    assert out["scopeKey"].startswith("EMPLOYER:") and out["reportingPeriod"] == "ANNUAL"
    assert out["renderedData"]["data"]["employerYear"]


def test_the_ptu_distribution_report(db, monkeypatch):
    from tests import test_mexico_ptu as P

    P._rules(monkeypatch)
    w, _emps = P._world(db, monkeypatch, "MXGEN7", second=False)
    cycle = P._approved_amount(db, w)
    t = _active(db, _seed(db)["MX-PTU-DISTRIBUTION"])
    out = _R().mx_report_generate(db, w.org.id, t.id, {"cycle_id": cycle["id"]}, None)
    assert out["scopeKey"] == f"CYCLE:{cycle['id']}" and out["renderedData"]["data"]["cycle"]["id"] == cycle["id"]
