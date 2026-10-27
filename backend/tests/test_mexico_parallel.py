"""Mexico final mile X4 — parallel payroll (spec §22 G8, MX-064): a legacy cycle
imported from CSV against a committed run, matched by employee code (never an
identifier), every difference explained and accepted four-eyes, and no cycle
declared clean while D-25 (materiality) is unset. SYNTHETIC worlds only."""

import json

import pytest

from tests import _mx_authority_helpers as ah

MAPPING = {"employee_code": "Code", "net": "Net", "isr_withheld": "ISR", "imss_employee": "IMSS EE"}


def _S():
    from app.modules.payroll import mexico_parallel_service

    return mexico_parallel_service


def _zoiko(db, w):
    from app.modules.payroll.models import PayslipItem

    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == w.run.id,
                                        PayslipItem.employee_id == w.employee.id).one()
    return _S().zoiko_amounts(item)


def _csv(db, w, net_delta="0.00", extra_rows=""):
    from decimal import Decimal

    z = _zoiko(db, w)
    net = z["net"] + Decimal(net_delta)
    return (f"Code,Net,ISR,IMSS EE\n{w.employee.employee_code},{net},{z['isr_withheld']},{z['imss_employee']}\n"
            + extra_rows)


def _import(db, w, csv_text, mapping=MAPPING, actor=0):
    return _S().import_parallel(db, w.org.id, {"run_id": w.run.id, "source_label": "SYNTHETIC legacy",
                                               "csv": csv_text, "column_mapping": mapping}, w.users[actor].id)


def _approve_d25(db, w, value):
    from app.modules.payroll import mexico_decision_service as D
    from app.modules.payroll.models import PayrollMxDecision as M

    D.seed_decisions(db)
    db.commit()
    did = db.query(M).filter(M.code == "D-25").one().id
    D.propose_mx_decision(db, did, {"chosen_option": value, "rationale": "SYNTHETIC", "cited_sources": ["spec §22"]},
                          w.users[0].id)
    D.approve_mx_decision(db, did, w.users[1].id)
    db.commit()


def test_d25_is_a_g8_amount_decision_in_the_register(db):
    from app.modules.payroll import mexico_decision_service as D
    from app.modules.payroll.models import PayrollMxDecision as M

    D.seed_decisions(db)
    db.commit()
    row = db.query(M).filter(M.code == "D-25").one()
    assert row.answer_kind == "AMOUNT" and row.gates == ["G8"] and row.status == "OPEN" and row.chosen_option is None


def test_an_identical_cycle_matches_but_is_never_clean_while_d25_is_unset(db, monkeypatch):
    w = ah.committed_world(db, monkeypatch, code="MXPARA")
    out = _import(db, w, _csv(db, w))
    assert out["status"] == "CURRENT" and out["rowCount"] == 1 and len(out["fileSha256"]) == 64
    assert {d["state"] for d in out["differences"]} == {"MATCH"} and len(out["differences"]) == 3
    assert out["differences"][0]["employee"] == w.employee.employee_code
    s = out["summary"]
    assert s["clean"] is None and s["materiality"]["threshold"] is None and "D-25" in s["note"]
    _approve_d25(db, w, "0")
    assert _S().parallel_import_view(db, w.org.id, out["id"])["summary"]["clean"] is True


def test_a_difference_needs_a_reason_then_a_second_reviewer(db, monkeypatch):
    from app.core.exceptions import BadRequestException, ForbiddenException

    w = ah.committed_world(db, monkeypatch, code="MXPARB")
    out = _import(db, w, _csv(db, w, net_delta="-12.50"))
    diff = next(d for d in out["differences"] if d["concept"] == "net")
    assert diff["state"] == "UNEXPLAINED" and diff["delta"] == "12.50"          # zoiko − legacy
    with pytest.raises(BadRequestException):
        _S().accept_parallel_difference(db, w.org.id, diff["id"], w.users[1].id)
    with pytest.raises(BadRequestException, match="reason"):
        _S().explain_parallel_difference(db, w.org.id, diff["id"], "  ", w.users[0].id)
    _S().explain_parallel_difference(db, w.org.id, diff["id"], "SYNTHETIC: legacy rounds per line", w.users[0].id)
    with pytest.raises(ForbiddenException, match="four-eyes"):
        _S().accept_parallel_difference(db, w.org.id, diff["id"], w.users[0].id)
    _approve_d25(db, w, "10")
    s = _S().parallel_import_view(db, w.org.id, out["id"])["summary"]
    assert s["clean"] is False and s["materiality"]["openMaterial"] == 1           # 12.50 > 10, not yet accepted
    assert _S().accept_parallel_difference(db, w.org.id, diff["id"], w.users[1].id)["state"] == "ACCEPTED"
    s = _S().parallel_import_view(db, w.org.id, out["id"])["summary"]
    assert s["clean"] is True and s["states"]["ACCEPTED"] == 1


def test_identifier_columns_and_values_are_refused_without_echoing_them(db, monkeypatch):
    from app.core.exceptions import BadRequestException

    w = ah.committed_world(db, monkeypatch, code="MXPARC")
    ids = [v for k, v in (w.employee.compliance_fields or {}).items() if k in ("rfc", "curp", "nss", "clabe") and v]
    assert ids
    with pytest.raises(BadRequestException, match="name an identifier") as e:
        _import(db, w, "Code,RFC,Net\nE1,X,1\n", {"employee_code": "Code", "net": "Net"})
    for value in ids:
        text = f"Code,Net,Note\n{w.employee.employee_code},1.00,{value}\n"
        with pytest.raises(BadRequestException, match="shaped like") as e:
            _import(db, w, text, {"employee_code": "Code", "net": "Net"})
        assert value not in str(e.value)
    with pytest.raises(BadRequestException, match="shaped like"):                  # an identifier as the match key
        _import(db, w, f"Code,Net\n{ids[0]},1.00\n", {"employee_code": "Code", "net": "Net"})
    from app.modules.payroll.models import PayrollMxParallelImport

    assert db.query(PayrollMxParallelImport).count() == 0                         # nothing recorded
    out = _import(db, w, _csv(db, w, net_delta="1.00"))
    diff = next(d for d in out["differences"] if d["state"] == "UNEXPLAINED")
    with pytest.raises(BadRequestException, match="shaped like") as e:              # nor in a reason
        _S().explain_parallel_difference(db, w.org.id, diff["id"], f"see {ids[0]}", w.users[0].id)
    assert ids[0] not in str(e.value)


def test_bad_files_are_refused_and_unmatched_employees_listed(db, monkeypatch):
    from app.core.exceptions import BadRequestException, NotFoundException

    w = ah.committed_world(db, monkeypatch, code="MXPARD")
    with pytest.raises(BadRequestException, match="Unknown mapping"):
        _import(db, w, _csv(db, w), {**MAPPING, "bonus": "Net"})
    with pytest.raises(BadRequestException, match="not in the file header"):
        _import(db, w, _csv(db, w), {**MAPPING, "isn": "ISN"})
    with pytest.raises(BadRequestException, match="not an amount"):
        _import(db, w, f"Code,Net\n{w.employee.employee_code},abc\n", {"employee_code": "Code", "net": "Net"})
    with pytest.raises(BadRequestException, match="repeats"):
        _import(db, w, "Code,Net\nA1,1\nA1,2\n", {"employee_code": "Code", "net": "Net"})
    out = _import(db, w, "Code,Net\nGHOST-1,100.00\n", {"employee_code": "Code", "net": "Net"})
    assert out["unmatched"] == {"legacyOnly": ["GHOST-1"], "zoikoOnly": [w.employee.employee_code]}
    assert out["differences"] == []
    _approve_d25(db, w, "0")
    assert _S().parallel_import_view(db, w.org.id, out["id"])["summary"]["clean"] is False
    other = ah.committed_world(db, monkeypatch, code="MXPARE")
    with pytest.raises(NotFoundException):                                         # another tenant's import
        _S().parallel_import_view(db, other.org.id, out["id"])
    with pytest.raises(NotFoundException):                                         # another tenant's run
        _S().import_parallel(db, other.org.id, {"run_id": w.run.id, "source_label": "x", "csv": "a\n",
                                                "column_mapping": MAPPING}, None)


def test_a_reimport_supersedes_and_freezes_the_old_cycle(db, monkeypatch):
    from app.core.exceptions import BadRequestException

    w = ah.committed_world(db, monkeypatch, code="MXPARF")
    first = _import(db, w, _csv(db, w, net_delta="1.00"))
    second = _import(db, w, _csv(db, w))
    assert _S().parallel_import_view(db, w.org.id, first["id"])["status"] == "SUPERSEDED"
    diff = next(d for d in first["differences"] if d["state"] == "UNEXPLAINED")
    with pytest.raises(BadRequestException, match="superseded"):
        _S().explain_parallel_difference(db, w.org.id, diff["id"], "late", w.users[0].id)
    assert [i["id"] for i in _S().list_parallel_imports(db, w.org.id, w.run.id)] == [second["id"], first["id"]]
    assert _S().withdraw_parallel_import(db, w.org.id, second["id"])["status"] == "WITHDRAWN"


def test_an_uncommitted_run_is_refused(db, monkeypatch):
    from app.core.exceptions import BadRequestException

    w = ah.committed_world(db, monkeypatch, code="MXPARG")
    draft = ah.new_run(db, w)
    with pytest.raises(BadRequestException, match="not committed"):
        _S().import_parallel(db, w.org.id, {"run_id": draft.id, "source_label": "x", "csv": "a\n",
                                            "column_mapping": MAPPING}, None)


def test_the_parallel_diff_report_is_built_from_the_import_without_identifiers(db, monkeypatch):
    from app.modules.payroll import service
    from tests.test_mexico_report_generators import _R, _active, _seed

    w = ah.committed_world(db, monkeypatch, code="MXPARH")
    out = _import(db, w, _csv(db, w, net_delta="3.00"))
    templates = _seed(db)
    assert templates["MX-PARALLEL-DIFF"].status == "Draft"
    assert "MX_PARALLEL_DIFF" in service.MX_DEDICATED_GENERATOR_REPORT_TYPES
    from app.modules.payroll.mexico_report_service import MX_REPORT_GATES

    assert MX_REPORT_GATES["MX_PARALLEL_DIFF"] == ("G8",)
    rep = _R().mx_report_generate(db, w.org.id, _active(db, templates["MX-PARALLEL-DIFF"]).id,
                                  {"import_id": out["id"]}, w.users[0].id)
    data = rep["renderedData"]["data"]
    assert rep["reportType"] == "MX_PARALLEL_DIFF" and data["id"] == out["id"]
    assert data["summary"]["clean"] is None and data["summary"]["states"]["UNEXPLAINED"] == 1
    ids = [v for k, v in (w.employee.compliance_fields or {}).items() if k in ("rfc", "curp", "nss", "clabe") and v]
    blob = json.dumps(rep, default=str)
    assert ids and not any(i in blob for i in ids)                                 # MX-061


def test_parallel_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = ah.committed_world(db, monkeypatch, code="MXPARAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    body = {"run_id": w.run.id, "source_label": "SYNTHETIC legacy", "csv": _csv(db, w, net_delta="-2.00"),
            "column_mapping": MAPPING}
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        made = c.post(f"{ORG_BASE}/parallel/imports", json=body)
        assert made.status_code == 200, made.text
        diff = next(d for d in made.json()["differences"] if d["state"] == "UNEXPLAINED")
        assert c.post(f"{ORG_BASE}/parallel/differences/{diff['id']}/explain",
                      json={"reason": "SYNTHETIC"}).json()["state"] == "EXPLAINED"
        own = c.post(f"{ORG_BASE}/parallel/differences/{diff['id']}/accept")
        assert own.status_code == 403
        assert c.get(f"{ORG_BASE}/parallel/imports?run_id={w.run.id}").json()[0]["id"] == made.json()["id"]
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        assert c.post(f"{ORG_BASE}/parallel/differences/{diff['id']}/accept").json()["state"] == "ACCEPTED"
        detail = c.get(f"{ORG_BASE}/parallel/imports/{made.json()['id']}").json()
        assert detail["summary"]["states"]["ACCEPTED"] == 1 and detail["summary"]["clean"] is None
        assert c.post(f"{ORG_BASE}/parallel/imports/{made.json()['id']}/withdraw").json()["status"] == "WITHDRAWN"
