"""Mexico Phase 9d — PTU (plan 9d D1–D10). Every rule is SYNTHETIC and
monkeypatched into the value-free content seams; with the seams empty no PTU is
allocated and no operator exclusion recorded. The distributable amount is the
employer's figure (MX-054); days and salary come only from committed runs."""

from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal as D

import pytest

from tests import _mx_authority_helpers as ah

FY = 2026
TODAY = date(2027, 3, 1)


class SynPtuRule:
    """Half by days, half by ordinary salary, pro rata; amounts floored to the
    cent; the residue is what flooring leaves. Operator-excluded workers get
    nothing. No cap (recorded as such)."""
    source, source_ref = "S26", "SYNTHETIC"

    def __init__(self, ignore_exclusions=False):
        self.ignore_exclusions = ignore_exclusions

    def allocate(self, pool, workers, fiscal_year):
        live = [w for w in workers if self.ignore_exclusions or not w.get("operator_exclusion")]
        days = sum((w["days"] for w in live), D("0"))
        salary = sum((w["salary_by_kind"].get("ORDINARY_SALARY", D("0")) for w in live), D("0"))
        out, total = [], D("0")
        for w in workers:
            if w in live:
                ds = (pool / 2 * w["days"] / days).quantize(D("0.01"), ROUND_DOWN) if days else D("0")
                ss = (pool / 2 * w["salary_by_kind"].get("ORDINARY_SALARY", D("0")) / salary).quantize(
                    D("0.01"), ROUND_DOWN) if salary else D("0")
                out.append({"employee_id": w["employee_id"], "eligible": True, "exclusion_reason": None,
                            "days_share": ds, "salary_share": ss, "cap_reference": {"cap": "none (SYNTHETIC)"},
                            "cap_applied": False, "final_amount": ds + ss})
                total += ds + ss
            else:
                out.append({"employee_id": w["employee_id"], "eligible": False,
                            "exclusion_reason": w["operator_exclusion"], "days_share": D("0"), "salary_share": D("0"),
                            "cap_reference": {}, "cap_applied": False, "final_amount": D("0")})
        return {"workers": out, "residue": pool - total, "residue_rule": "SYNTHETIC: flooring residue kept"}

    def payment_deadline(self, fiscal_year, employer):
        return date(fiscal_year + 1, 5, 30)


class SynExclusion:
    source, source_ref, label = "S26", "SYNTHETIC", "Synthetic director"


class SynSpecialPayRule:
    source, source_ref = "S24", "SYNTHETIC"
    combine_with_ordinary = False

    def exempt(self, concept, amount, facts):
        return min(amount, D("100"))

    def standalone_isr(self, taxable, facts):
        return (taxable * D("0.10")).quantize(D("0.01"), ROUND_HALF_UP)


def _rules(monkeypatch, *, ptu=True, exclusions=True, rule=None):
    from app.modules.payroll import mexico_ptu_service
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(mexico_ptu_service, "_today", lambda: TODAY)
    # W1-4 transcribed the real rule and catalog: "absent" is set explicitly
    monkeypatch.setattr(c, "MX_PTU_RULE", (rule or SynPtuRule()) if ptu else None)
    monkeypatch.setattr(c, "MX_PTU_EXCLUSION_REASONS", {"SYN_DIRECTOR": SynExclusion()} if exclusions else {})
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_RULES", {"PTU": SynSpecialPayRule()})
    monkeypatch.setattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", {("CDMX", "PTU"): (True, "S22", "SYNTHETIC")})


def _P():
    from app.modules.payroll import mexico_ptu_service as P

    return P


def _second_employee(db, w, salary="500"):
    from tests._mx_employer_helpers import new_mx_employee, save_mx_profile

    emp = new_mx_employee(db, w.org.id, code=f"{w.org.organization_code}-2",
                          email=f"emp2.{w.org.organization_code.lower()}@example.com",
                          rfc="WXYZ010101AB1", curp="WXYZ010101HDFXYZ01", nss="10987654321")
    save_mx_profile(db, emp, w.org.id, effective_from=date(2026, 1, 1), mx_daily_salary=D(salary),
                    mx_seniority_date=date(2024, 3, 1), mx_salary_type="FIXED", mx_pay_frequency_code="04",
                    mx_establishment_id=w.workplace.establishment["id"], mx_imss_registration_id=w.registration.id)
    return emp


def _commit(db, w, run, employees):
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, run, w.org.id, [e.id for e in employees])
    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    assert run.status == "Approved" and run.mx_approval_fingerprint["committedAt"]
    return run


def _world(db, monkeypatch, code, *, second=True):
    """Employee 1: Jun 1-15 (world run) + Jun 16-30 committed (30 days, 600/day).
    Employee 2: Jun 16-30 only (15 days, 500/day)."""
    w = ah.committed_world(db, monkeypatch, code=code)
    emps = [w.employee]
    if second:
        emps.append(_second_employee(db, w))
    _commit(db, w, ah.new_run(db, w), emps)
    return w, emps


def _employer(w):
    return w.registration.employer_profile_id


def _cycle(db, w, amount="10000", actor=0, year=FY):
    return _P().create_cycle(db, w.org.id, {"employer_profile_id": _employer(w), "fiscal_year": year,
                                            "distributable_amount": amount, "evidence_ref": "SYN-DECL-2026"},
                             w.users[actor].id)


def _approved_amount(db, w, **kw):
    c = _cycle(db, w, **kw)
    return _P().approve_amount(db, w.org.id, c["id"], w.users[1].id)


def _extend_content_to(db, year=2027):
    """The synthetic packs cover 2026; a PTU of 2026 is paid in 2027."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    for model in (JurisdictionPack, ContributionRate, TaxSlab):
        for row in db.query(model).filter(model.effective_to == date(2026, 12, 31)):
            row.effective_to = date(year, 12, 31)
    db.commit()


def _codes(db, run):
    from app.modules.payroll import mexico_run_service

    return {e["code"] for e in mexico_run_service.run_preflight(db, run)["exceptions"]}


# ── the cycle ───────────────────────────────────────────────────────────────

def test_the_cycle_needs_an_ended_year_evidence_and_a_second_person(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _rules(monkeypatch, ptu=False)
    w, _ = _world(db, monkeypatch, "MXPTU1", second=False)
    with pytest.raises(Exception, match="ended"):
        _cycle(db, w, year=2027)
    with pytest.raises(Exception, match="evidence"):
        _P().create_cycle(db, w.org.id, {"employer_profile_id": _employer(w), "fiscal_year": FY,
                                         "distributable_amount": "10", "evidence_ref": " "}, w.users[0].id)
    with pytest.raises(Exception, match="more than zero"):
        _cycle(db, w, amount="0")
    c = _cycle(db, w)
    assert c["status"] == "DRAFT" and c["distributableAmount"] == "10000.00"
    with pytest.raises(Exception, match="already exists"):
        _cycle(db, w)
    with pytest.raises(MXBlock) as exc:
        _P().approve_amount(db, w.org.id, c["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    out = _P().approve_amount(db, w.org.id, c["id"], w.users[1].id)
    assert out["status"] == "AMOUNT_APPROVED" and out["paymentDeadline"] is None
    assert out["deadlineRuleRef"].startswith("unsourced")


def test_without_the_rule_nothing_is_allocated(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxPtuAllocation

    _rules(monkeypatch, ptu=False)
    w, _ = _world(db, monkeypatch, "MXPTU2", second=False)
    c = _approved_amount(db, w)
    with pytest.raises(MXBlock) as exc:
        _P().allocate(db, w.org.id, c["id"], w.users[0].id)
    assert exc.value.key == "MX_PTU_RULE_MISSING"
    assert db.query(PayrollMxPtuAllocation).count() == 0


# ── the allocation ──────────────────────────────────────────────────────────

def test_allocation_comes_from_committed_runs_only_and_sums_to_the_pool(db, monkeypatch):
    """Directional: more days → a larger days share; a higher salary → a larger salary share."""
    from app.modules.payroll import service

    _rules(monkeypatch)
    w, (e1, e2) = _world(db, monkeypatch, "MXPTU3")
    draft = ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15))
    service.generate_payslips_for_run(db, draft, w.org.id, [e1.id, e2.id])   # calculated, NOT committed
    c = _approved_amount(db, w)
    out = _P().allocate(db, w.org.id, c["id"], w.users[0].id)
    a = {x["employeeId"]: x for x in out["allocations"]}
    assert out["status"] == "ALLOCATED" and D(a[e1.id]["qualifyingDays"]) == 30 and D(a[e2.id]["qualifyingDays"]) == 15
    assert D(a[e1.id]["daysShare"]) > D(a[e2.id]["daysShare"]) > 0
    assert D(a[e1.id]["salaryShare"]) > D(a[e2.id]["salaryShare"]) > 0
    assert D(out["allocatedTotal"]) + D(out["residue"]) == D("10000")
    assert a[e1.id]["capReference"] == {"cap": "none (SYNTHETIC)"} and out["ruleSource"] == "S26 SYNTHETIC"


def test_a_committed_change_after_allocation_makes_it_stale(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _rules(monkeypatch)
    w, (e1, e2) = _world(db, monkeypatch, "MXPTU4")
    c = _approved_amount(db, w)
    _P().allocate(db, w.org.id, c["id"], w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        _P().approve_allocation(db, w.org.id, c["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    _commit(db, w, ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15)), [e1])
    with pytest.raises(MXBlock) as exc:
        _P().approve_allocation(db, w.org.id, c["id"], w.users[1].id)
    assert exc.value.key == "MX_PTU_ALLOCATION_STALE"
    _P().allocate(db, w.org.id, c["id"], w.users[0].id)                     # re-allocate: now current
    assert _P().approve_allocation(db, w.org.id, c["id"], w.users[1].id)["status"] == "APPROVED"


def test_operator_exclusions_need_the_catalog_evidence_and_a_second_person(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    _rules(monkeypatch, exclusions=False)
    w, (e1, e2) = _world(db, monkeypatch, "MXPTU5")
    c = _approved_amount(db, w)
    with pytest.raises(MXBlock) as exc:
        _P().record_exclusion(db, w.org.id, c["id"], {"employee_id": e2.id, "reason_code": "SYN_DIRECTOR",
                                                      "evidence_ref": "SYN"}, w.users[0].id)
    assert exc.value.key == "MX_PTU_EXCLUSION_RULE_MISSING"
    _rules(monkeypatch)
    with pytest.raises(MXBlock) as exc:
        _P().record_exclusion(db, w.org.id, c["id"], {"employee_id": e2.id, "reason_code": "FREE_TEXT",
                                                      "evidence_ref": "SYN"}, w.users[0].id)
    assert exc.value.key == "MX_PTU_EXCLUSION_REASON_UNKNOWN"
    _P().record_exclusion(db, w.org.id, c["id"], {"employee_id": e2.id, "reason_code": "SYN_DIRECTOR",
                                                  "evidence_ref": "SYN-BOARD-MINUTES"}, w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        _P().allocate(db, w.org.id, c["id"], w.users[0].id)
    assert exc.value.key == "MX_PTU_EXCLUSION_PENDING"
    with pytest.raises(MXBlock) as exc:
        _P().approve_exclusion(db, w.org.id, c["id"], e2.id, w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    _P().approve_exclusion(db, w.org.id, c["id"], e2.id, w.users[1].id)
    out = _P().allocate(db, w.org.id, c["id"], w.users[0].id)
    a = {x["employeeId"]: x for x in out["allocations"]}
    assert (a[e2.id]["eligible"], a[e2.id]["exclusionReason"], D(a[e2.id]["finalAmount"])) == (False, "SYN_DIRECTOR", 0)
    assert a[e2.id]["exclusionEvidenceRef"] == "SYN-BOARD-MINUTES" and D(a[e1.id]["finalAmount"]) > 0


def test_a_rule_that_ignores_an_exclusion_or_loses_money_is_refused(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.engine.jurisdictions.mexico import ptu

    _rules(monkeypatch, rule=SynPtuRule(ignore_exclusions=True))
    workers = [{"employee_id": 1, "days": D("10"), "salary_by_kind": {"ORDINARY_SALARY": D("100")},
                "operator_exclusion": "SYN_DIRECTOR"},
               {"employee_id": 2, "days": D("10"), "salary_by_kind": {"ORDINARY_SALARY": D("100")},
                "operator_exclusion": None}]
    with pytest.raises(MXBlock) as exc:
        ptu.allocate(D("1000"), workers, FY)
    assert exc.value.key == "MX_PTU_RULE_INVALID"

    class Leaky(SynPtuRule):
        def allocate(self, pool, workers, fiscal_year):
            out = super().allocate(pool, workers, fiscal_year)
            out["residue"] = D("0") if out["residue"] else D("1")            # does not add up
            return out

    _rules(monkeypatch, rule=Leaky())
    with pytest.raises(MXBlock) as exc:
        ptu.allocate(D("1000.01"), workers[1:], FY)
    assert exc.value.key == "MX_PTU_RULE_INVALID"


# ── the PTU run ─────────────────────────────────────────────────────────────

def _approved_cycle(db, monkeypatch, code):
    _rules(monkeypatch)
    w, emps = _world(db, monkeypatch, code)
    c = _approved_amount(db, w)
    _P().allocate(db, w.org.id, c["id"], w.users[0].id)
    _P().approve_allocation(db, w.org.id, c["id"], w.users[1].id)
    _extend_content_to(db)
    return w, emps, c


def test_the_ptu_run_pays_each_worker_on_its_own_never_as_ordinary_pay(db, monkeypatch):
    from app.modules.payroll.models import EmployeeStatus, PayrollMxSbcHistory, PayrollRun

    w, (e1, e2), c = _approved_cycle(db, monkeypatch, "MXPTU6")
    e2.status, e2.date_of_leaving = EmployeeStatus.INACTIVE, date(2026, 9, 30)   # a leaver keeps the right
    db.commit()
    with pytest.raises(Exception, match="after that year ends"):
        _P().create_ptu_run(db, w.org.id, c["id"], date(2026, 12, 31), w.users[0].id)
    out = _P().create_ptu_run(db, w.org.id, c["id"], date(2027, 5, 15), w.users[0].id)
    run = db.get(PayrollRun, out["runId"])
    assert run.mx_run_type == "PTU" and out["employees"] == 2 and _codes(db, run) == set()
    items = {i.employee_id: i for i in ah.rh.mx_items(db, run)}
    cyc = _P().get_cycle(db, w.org.id, c["id"])
    finals = {a["employeeId"]: D(a["finalAmount"]) for a in cyc["allocations"]}
    for emp in (e1, e2):
        res = items[emp.id].mx_calculation_snapshot["result"]
        assert D(res["gross"]) == finals[emp.id] and res["special"]["concept"] == "PTU"
        assert res["imss"] == [] and D(res["isr_withheld"]) == ((finals[emp.id] - 100) * D("0.10")).quantize(D("0.01"))
    with pytest.raises(Exception, match="already has PTU run"):
        _P().create_ptu_run(db, w.org.id, c["id"], date(2027, 5, 15), w.users[0].id)
    with pytest.raises(Exception, match="delete it first"):
        _P().cancel_cycle(db, w.org.id, c["id"], "SYNTHETIC", w.users[0].id)
    _commit_run(db, w, run)
    assert db.query(PayrollMxSbcHistory).filter(PayrollMxSbcHistory.payroll_run_id == run.id).count() == 0  # MX-056


def _commit_run(db, w, run):
    from app.modules.payroll import service

    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    assert run.status == "Approved" and run.mx_approval_fingerprint["committedAt"]


def test_commit_distributes_the_cycle_and_reset_reverses_it(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import PayrollRun

    w, (e1, e2), c = _approved_cycle(db, monkeypatch, "MXPTU7")
    run = db.get(PayrollRun, _P().create_ptu_run(db, w.org.id, c["id"], date(2027, 5, 15), w.users[0].id)["runId"])
    _commit_run(db, w, run)
    cyc = _P().get_cycle(db, w.org.id, c["id"])
    assert cyc["status"] == "DISTRIBUTED" and all(a["payslipItemId"] for a in cyc["allocations"])
    assert cyc["ptuRun"]["committed"] is True
    with pytest.raises(Exception, match="DISTRIBUTED"):
        _P().cancel_cycle(db, w.org.id, c["id"], "SYNTHETIC", w.users[0].id)
    assert _P().employee_ptu(db, w.org.id, e2.id)[0]["cycleStatus"] == "DISTRIBUTED"
    out = mexico_run_service.reset_run(db, run, w.users[0].id, "SYNTHETIC")
    assert out["removed"]["ptuAllocationsReopened"] == 2
    cyc = _P().get_cycle(db, w.org.id, c["id"])
    assert cyc["status"] == "APPROVED" and not any(a["payslipItemId"] for a in cyc["allocations"])


def test_ptu_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    _rules(monkeypatch)
    w, (e1, e2) = _world(db, monkeypatch, "MXPTUAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        made = c.post(f"{ORG_BASE}/ptu/cycles", json={"employerId": _employer(w), "fiscalYear": FY,
                                                      "distributableAmount": "5000", "evidenceRef": "SYN-1"})
        assert made.status_code == 200, made.text
        own = c.post(f"{ORG_BASE}/ptu/cycles/{made.json()['id']}/approve-amount")
        assert own.status_code == 400 and "MX_FOUR_EYES_REQUIRED" in own.text
        assert [r["code"] for r in c.get(f"{ORG_BASE}/ptu/exclusion-reasons").json()["reasons"]] == ["SYN_DIRECTOR"]
    cid = made.json()["id"]
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        assert c.post(f"{ORG_BASE}/ptu/cycles/{cid}/approve-amount").json()["status"] == "AMOUNT_APPROVED"
        alloc = c.post(f"{ORG_BASE}/ptu/cycles/{cid}/allocate")
        assert alloc.status_code == 200 and len(alloc.json()["allocations"]) == 2, alloc.text
        assert c.get(f"{ORG_BASE}/ptu/cycles").json()[0]["id"] == cid
        assert c.get(f"{ORG_BASE}/employees/{e1.id}/ptu").json()[0]["cycleId"] == cid
