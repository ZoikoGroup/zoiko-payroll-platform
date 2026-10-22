"""Mexico Phase 10b — the payroll journal (plan D6). SYNTHETIC world and account
codes. The journal is built from the committed snapshots only, balances, keeps
every authority liability on its own line (§20), is exported as a CSV that
names no worker, and is never posted anywhere."""

from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_authority_helpers as ah


def _J():
    from app.modules.payroll import mexico_journal_service as J

    return J


def _all_accounts():
    return {code: f"SYN-{n:03d}" for n, (code, _, _) in enumerate(_J().LINE_TYPES, start=100)}


def _mapped(db, w, accounts=None):
    J = _J()
    m = J.create_mapping(db, w.org.id, {"accounts": accounts or _all_accounts(), "note": "SYNTHETIC"}, w.users[0].id)
    return J.approve_mapping(db, w.org.id, m["id"], w.users[1].id)


def _by_type(lines):
    out = {}
    for l in lines:
        sign = 1 if l["side"] == ("DEBIT" if l["lineType"].endswith("EXPENSE") else "CREDIT") else -1
        out[l["lineType"]] = out.get(l["lineType"], D("0")) + sign * D(str(l["amount"]))
    return out


# ── the mapping ─────────────────────────────────────────────────────────────

def test_the_mapping_is_versioned_four_eyes_and_validated(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL1")
    with pytest.raises(Exception, match="unknown line type"):
        J.create_mapping(db, w.org.id, {"accounts": {"WAGES": "6000"}}, w.users[0].id)
    with pytest.raises(Exception, match="unknown line type"):
        J.create_mapping(db, w.org.id, {"accounts": {"ISR_PAYABLE:X": "2100"}}, w.users[0].id)
    with pytest.raises(Exception, match="account code"):
        J.create_mapping(db, w.org.id, {"accounts": {"ISR_PAYABLE": "21;00"}}, w.users[0].id)
    m1 = J.create_mapping(db, w.org.id, {"accounts": _all_accounts()}, w.users[0].id)
    with pytest.raises(Exception, match="draft mapping already exists"):
        J.create_mapping(db, w.org.id, {"accounts": _all_accounts()}, w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        J.approve_mapping(db, w.org.id, m1["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    assert J.approve_mapping(db, w.org.id, m1["id"], w.users[1].id)["status"] == "APPROVED"
    m2 = J.create_mapping(db, w.org.id, {"accounts": {**_all_accounts(), "ISR_PAYABLE": "2105"}}, w.users[1].id)
    assert m2["version"] == 2 and J.approved_mapping(db, w.org.id).id == m1["id"]   # a draft changes nothing
    J.approve_mapping(db, w.org.id, m2["id"], w.users[0].id)
    assert [(m["version"], m["status"]) for m in J.list_mappings(db, w.org.id)] == [(2, "APPROVED"),
                                                                                  (1, "SUPERSEDED")]
    m3 = J.create_mapping(db, w.org.id, {"accounts": {"ISR_PAYABLE": "1"}}, w.users[0].id)
    assert J.withdraw_mapping(db, w.org.id, m3["id"], w.users[0].id)["status"] == "WITHDRAWN"


# ── the journal of a committed run ──────────────────────────────────────────

def test_the_journal_balances_and_keeps_every_liability_on_its_own_line(db, monkeypatch):
    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL2")
    (item,) = ah.rh.mx_items(db, w.run)
    res = item.mx_calculation_snapshot["result"]
    out = J.run_journal(db, w.org.id, w.run.id)
    assert out["balanced"] and out["debitTotal"] == out["creditTotal"]
    assert [p["code"] for p in out["problems"]] == ["MX_JOURNAL_MAPPING_MISSING"]
    t = _by_type(out["lines"])
    gross = D(str(res["gross"]))
    assert t["WAGES_EXPENSE"] == gross and t["NET_PAY_PAYABLE"] == D(str(item.net_pay))
    assert t["ISR_PAYABLE"] == D(str(res["isr_withheld"])) > 0
    assert t["IMSS_EMPLOYEE_PAYABLE"] == D(str(res["imss_employee"])) > 0
    assert t["IMSS_EMPLOYER_EXPENSE"] == t["IMSS_EMPLOYER_PAYABLE"] == D(str(res["imss_employer"])) > 0
    assert t["ISN_EXPENSE"] == t["ISN_PAYABLE"] == D(str(res["isn"]["amount"])).quantize(D("0.01")) > 0
    if D(str(res["infonavit_employer"])):
        assert t["INFONAVIT_EMPLOYER_EXPENSE"] == t["INFONAVIT_EMPLOYER_PAYABLE"]
    # never netted: each liability its own line, the employee and employer IMSS sides apart
    assert len({(l["lineType"], l["dimension"]) for l in out["lines"]}) == len(out["lines"])
    reg = [l["dimension"] for l in out["lines"] if l["lineType"] == "IMSS_EMPLOYER_PAYABLE"]
    assert reg == [w.registration.registro_patronal]
    assert [l["dimension"] for l in out["lines"] if l["lineType"] == "ISN_PAYABLE"] == [res["isn"]["state"]]
    assert "OTHER_DEDUCTIONS_PAYABLE" not in t                       # every deduction is a Mexican one


def test_export_needs_an_approved_complete_mapping_and_names_no_worker(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxJournalExport

    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL3")
    with pytest.raises(MXBlock) as exc:
        J.export_journal(db, w.org.id, w.run.id, w.users[0].id)
    assert exc.value.key == "MX_JOURNAL_MAPPING_MISSING"
    partial = {k: v for k, v in _all_accounts().items() if k != "ISR_PAYABLE"}
    _mapped(db, w, partial)
    with pytest.raises(MXBlock) as exc:
        J.export_journal(db, w.org.id, w.run.id, w.users[0].id)
    assert exc.value.key == "MX_JOURNAL_ACCOUNT_UNMAPPED" and "ISR_PAYABLE" in exc.value.reason
    assert db.query(PayrollMxJournalExport).count() == 0
    _mapped(db, w)
    out = J.export_journal(db, w.org.id, w.run.id, w.users[0].id)
    rows = out["content"].splitlines()
    assert rows[0].startswith("ZOIKO PAYROLL JOURNAL - NOT POSTED TO ANY LEDGER")
    assert rows[2] == "line_type,dimension,account,debit,credit" and rows[-1].startswith("TOTAL,")
    preview = J.run_journal(db, w.org.id, w.run.id)
    _, _, _, debit, credit = rows[-1].split(",")
    assert debit == credit == preview["debitTotal"] and preview["problems"] == []
    assert w.employee.name not in out["content"] and w.employee.employee_code not in out["content"]
    row = db.get(PayrollMxJournalExport, out["id"])
    assert row.file_sha256 == out["sha256"] and row.status == "CURRENT" and row.line_count == len(rows) - 4
    again = J.export_journal(db, w.org.id, w.run.id, w.users[0].id)
    assert again["sha256"] == out["sha256"]                          # deterministic


def test_wages_can_be_split_by_earning_kind(db, monkeypatch):
    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL4")
    (kind,) = {l["dimension"] for l in J.run_journal(db, w.org.id, w.run.id)["lines"]
               if l["lineType"] == "WAGES_EXPENSE"}
    _mapped(db, w, {**_all_accounts(), f"WAGES_EXPENSE:{kind}": "SYN-6010"})
    (wages,) = [l for l in J.run_journal(db, w.org.id, w.run.id)["lines"] if l["lineType"] == "WAGES_EXPENSE"]
    assert wages["account"] == "SYN-6010"


def test_other_deductions_and_an_unbalanceable_payslip(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL5")
    (item,) = ah.rh.mx_items(db, w.run)
    net = D(str(item.net_pay))
    item.net_pay = net - D("25.00")                                  # a deduction Zoiko did not compute
    db.commit()
    out = J.run_journal(db, w.org.id, w.run.id)
    assert _by_type(out["lines"])["OTHER_DEDUCTIONS_PAYABLE"] == D("25.00") and out["balanced"]
    item.net_pay = D(str(item.mx_calculation_snapshot["result"]["gross"])) + 1
    db.commit()
    with pytest.raises(MXBlock) as exc:
        J.run_journal(db, w.org.id, w.run.id)
    assert exc.value.key == "MX_JOURNAL_UNBALANCED"


def test_only_a_committed_run_has_a_journal(db, monkeypatch):
    from app.modules.payroll import service

    w = ah.committed_world(db, monkeypatch, code="MXJNL6")
    draft = ah.new_run(db, w)
    service.generate_payslips_for_run(db, draft, w.org.id, [w.employee.id])
    with pytest.raises(Exception, match="committed"):
        _J().run_journal(db, w.org.id, draft.id)


def test_a_correction_run_journals_its_deltas(db, monkeypatch):
    from app.modules.payroll import mexico_correction_service as S
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL7")
    (orig,) = ah.rh.mx_items(db, w.run)
    ah.raise_salary(db, w, "700", effective_from=date(2026, 6, 1))
    made = S.create_correction(db, w.org.id, w.run.id, [orig.id], "SYNTHETIC: daily salary 700", w.users[0].id)
    corr = db.get(PayrollRun, made["corrects"][0]["correctionRunId"])
    for _ in range(2):
        service.advance_payroll_run_status(db, corr.id, w.users[1].id, w.org.id)
    db.refresh(corr)
    (new,) = ah.rh.mx_items(db, corr)
    o, c = orig.mx_calculation_snapshot["result"], new.mx_calculation_snapshot["result"]
    out = J.run_journal(db, w.org.id, corr.id)
    t = _by_type(out["lines"])
    assert out["runType"] == "CORRECTION" and out["balanced"]
    assert t["WAGES_EXPENSE"] == D(str(c["gross"])) - D(str(o["gross"])) > 0
    assert t["NET_PAY_PAYABLE"] == D(str(new.net_pay)) - D(str(orig.net_pay))
    assert t["ISR_PAYABLE"] == D(str(c["isr_withheld"])) - D(str(o["isr_withheld"]))


def test_a_lower_correction_reverses_the_natural_side(db, monkeypatch):
    J = _J()
    lines = []
    acc = {}
    from collections import defaultdict

    acc = defaultdict(lambda: D("0"))
    amounts = {"gross": D("100"), "kinds": {"ORDINARY_SALARY": D("100")}, "net": D("90"), "isr": D("10"),
               "imss_ee": D("0"), "imss_er": D("0"), "housing": D("0"), "credit": D("0"), "isn": D("0"),
               "state": "CDMX"}
    lower = {**amounts, "gross": D("80"), "kinds": {"ORDINARY_SALARY": D("80")}, "net": D("72"), "isr": D("8")}
    J._post_payslip(acc, lower, "REG", 1, 2)
    J._post_payslip(acc, amounts, "REG", -1, 1)
    lines = {k: v for k, v in acc.items() if v}
    assert lines[("WAGES_EXPENSE", "ORDINARY_SALARY")] == D("-20") and lines[("NET_PAY_PAYABLE", "")] == D("-18")
    assert sum(v for (t, _), v in lines.items() if J._SIDE[t] == "DEBIT") == \
        sum(v for (t, _), v in lines.items() if J._SIDE[t] == "CREDIT")


# ── the run's reset (Phase 6 rule) ──────────────────────────────────────────

def test_a_current_export_refuses_the_reset_until_voided(db, monkeypatch):
    from fastapi import HTTPException

    from app.modules.payroll import mexico_run_service

    J = _J()
    w = ah.committed_world(db, monkeypatch, code="MXJNL8")
    _mapped(db, w)
    out = J.export_journal(db, w.org.id, w.run.id, w.users[0].id)
    with pytest.raises(HTTPException) as exc:
        mexico_run_service.reset_run(db, w.run, w.users[0].id, "SYNTHETIC")
    assert exc.value.status_code == 409 and f"journal export {out['id']} is CURRENT" in exc.value.detail
    with pytest.raises(Exception, match="reason"):
        J.void_export(db, w.org.id, out["id"], " ", w.users[0].id)
    assert J.void_export(db, w.org.id, out["id"], "SYNTHETIC: reversed", w.users[0].id)["status"] == "VOIDED"
    assert J.downstream_reasons(db, w.run) == []


def test_journal_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = ah.committed_world(db, monkeypatch, code="MXJNLAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        listed = c.get(f"{ORG_BASE}/journal/mappings")
        assert listed.status_code == 200, listed.text
        assert [t["code"] for t in listed.json()["lineTypes"]][0] == "WAGES_EXPENSE"
        made = c.post(f"{ORG_BASE}/journal/mappings", json={"accounts": _all_accounts()})
        assert made.status_code == 200, made.text
        own = c.post(f"{ORG_BASE}/journal/mappings/{made.json()['id']}/approve")
        assert own.status_code == 400 and "MX_FOUR_EYES_REQUIRED" in own.text
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        assert c.post(f"{ORG_BASE}/journal/mappings/{made.json()['id']}/approve").json()["status"] == "APPROVED"
        assert c.get(f"{ORG_BASE}/runs/{w.run.id}/journal").json()["problems"] == []
        f = c.post(f"{ORG_BASE}/runs/{w.run.id}/journal/export")
        assert f.status_code == 200 and f.headers["cache-control"].split(",")[0].strip() == "no-store"
        assert "attachment" in f.headers["content-disposition"] and f.text.startswith("ZOIKO PAYROLL JOURNAL")
        exp = c.get(f"{ORG_BASE}/runs/{w.run.id}/journal").json()["exports"][0]
        v = c.post(f"{ORG_BASE}/journal/exports/{exp['id']}/void", json={"reason": "SYNTHETIC"})
        assert v.status_code == 200 and v.json()["status"] == "VOIDED"
