"""
tests/test_singapore_phase68_ir8a_modifications.py
--------------------------------------------------
Phase 6.8 (G3) — IR8A Revision / Amendment of an IRAS-acknowledged extract
(docs/SINGAPORE_G3_IR8A_AMENDMENT_AND_AIS_DECISION.md §C). IRAS myTax Portal
"Modify previously submitted data" (Quick Guide, 15 Sep 2025): a REVISION
carries the full and correct values and overwrites the previous records; an
AMENDMENT carries only the differences. Positions are the myTaxPortalEntry
values per employee. app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal

import pytest

D = Decimal


# ── fixtures / helpers ─────────────────────────────────────────────────────

def _actors():
    from tests.test_singapore import CHECKER, MAKER

    return MAKER.id, CHECKER.id


def _template(db):
    from tests.test_singapore import _ir8a_template

    return _ir8a_template(db)


def _pack(db, version="1.2"):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="SG-P68", jurisdiction_country="SG", pack_type="tax", version=version, status="Active",
                            effective_from=date(2025, 1, 1))
    db.add(pack)
    db.commit()
    return pack


def _employee(db, org, code):
    from tests.test_singapore import _sg_employee

    return _sg_employee(db, org.id, code, compliance_fields={"nric_fin": "S1234567D"})


def _payslip(db, org, emp, pay_date, gross, cpf="0", pack=None):
    from app.modules.payroll.models import PayrollStatus, PayslipItem
    from tests.test_singapore import _run

    run = _run(db, org, pay_date, f"P68 {org.id} {emp.id} {pay_date} {gross}")
    run.status = PayrollStatus.APPROVED
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org.id, employee_name=emp.name,
                       country_code="SG", gross_pay=D(gross), employee_pension=D(cpf),
                       tax_policy_pack_id=pack.id if pack else None, tax_policy_version=pack.version if pack else None))
    db.commit()


def _original(db, org, template, year=2026, outcome="ACKNOWLEDGED"):
    from app.modules.payroll import service

    maker, checker = _actors()
    report = service.generate_sg_ir8a(db, org.id, template.id, year, actor_id=maker)
    service.transition_sg_ir8a(db, org.id, report.id, "SUBMITTED_MANUALLY", actor_id=checker, reference=f"MYTAX-{report.id}")
    if outcome:
        kw = {"note": "confirmed"} if outcome == "UNKNOWN" else {}
        service.transition_sg_ir8a(db, org.id, report.id, outcome, actor_id=checker, reference=f"IRAS-{report.id}", **kw)
    return report


def _modify(db, org, base, method, reason="correction"):
    from app.modules.payroll import service

    maker, _ = _actors()
    return service.create_sg_ir8a_modification(db, org.id, base.id, method, reason=reason, actor_id=maker)


def _file(db, org, mod, outcome="ACKNOWLEDGED"):
    from app.modules.payroll import service

    _, checker = _actors()
    service.transition_sg_ir8a(db, org.id, mod["reportId"], "SUBMITTED_MANUALLY", actor_id=checker,
                               reference=f"MYTAX-MOD-{mod['id']}")
    if outcome:
        service.transition_sg_ir8a(db, org.id, mod["reportId"], outcome, actor_id=checker, reference=f"IRAS-MOD-{mod['id']}",
                                   **({"note": "confirmed"} if outcome == "UNKNOWN" else {}))


def _position(db, base):
    from app.modules.payroll import service

    return service._sg_ir8a_cumulative_position(db, base)


def _refused(db, entity_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return [a for a in db.query(TaxConfigurationAudit).filter(
        TaxConfigurationAudit.entity_type == "sg_ir8a", TaxConfigurationAudit.entity_id == entity_id,
        TaxConfigurationAudit.action == "refused").order_by(TaxConfigurationAudit.id)]


@pytest.fixture()
def acknowledged(db, organization):
    """Two employees, a 2026 original acknowledged by IRAS."""
    template = _template(db)
    pack = _pack(db)
    a, b = _employee(db, organization, "P68A"), _employee(db, organization, "P68B")
    _payslip(db, organization, a, date(2026, 3, 31), "6000", "1200", pack)
    _payslip(db, organization, b, date(2026, 3, 31), "4000", "800", pack)
    base = _original(db, organization, template)
    return {"template": template, "pack": pack, "a": a, "b": b, "base": base}


# ── 1–3: original, acknowledgement, no second original ────────────────────

def test_original_is_acknowledged_and_a_second_original_is_blocked(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    base = acknowledged["base"]
    db.refresh(base)
    assert base.status == "ACKNOWLEDGED"
    assert service.list_sg_ir8a(db, organization.id)[0]["submissionKind"] == "ORIGINAL"
    again = service.generate_sg_ir8a(db, organization.id, acknowledged["template"].id, 2026, actor_id=_actors()[0])
    with pytest.raises(BadRequestException, match="Revision or Amendment"):
        service.transition_sg_ir8a(db, organization.id, again.id, "SUBMITTED_MANUALLY", actor_id=_actors()[1], reference="X")


# ── 4–6: revision ──────────────────────────────────────────────────────────

def test_revision_carries_full_values_preserves_the_original_and_replaces_the_position(db, organization, acknowledged):
    from app.modules.payroll.models import GeneratedReport

    base = acknowledged["base"]
    original_data = dict(db.query(GeneratedReport).get(base.id).rendered_data)
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "200", acknowledged["pack"])
    mod = _modify(db, organization, base, "REVISION")
    a = str(acknowledged["a"].id)
    assert (mod["method"], mod["sequence"], mod["delta"]) == ("REVISION", 1, None)
    assert mod["resultingPosition"][a]["grossSalary"] == 7000 and mod["previousPosition"][a]["grossSalary"] == 6000
    report = db.query(GeneratedReport).get(mod["reportId"])
    assert report.rendered_data["modification"]["method"] == "REVISION"
    assert {r["employeeId"] for r in report.rendered_data["employeeRows"]} == {acknowledged["a"].id, acknowledged["b"].id}
    _file(db, organization, mod)
    db.expire_all()
    assert _position(db, base) == mod["resultingPosition"]                              # overwrites
    stored = db.query(GeneratedReport).get(base.id)
    assert (stored.status, stored.rendered_data) == ("ACKNOWLEDGED", original_data)       # original untouched


# ── 7–9: amendment ─────────────────────────────────────────────────────────

def test_amendment_stores_only_the_differences(db, organization, acknowledged):
    from app.modules.payroll.models import GeneratedReport

    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "200", acknowledged["pack"])
    mod = _modify(db, organization, acknowledged["base"], "AMENDMENT")
    a = str(acknowledged["a"].id)
    assert mod["delta"] == {a: {"grossSalary": 1000, "employeeCpf": 200}}                # B unaffected -> absent
    entries = db.query(GeneratedReport).get(mod["reportId"]).rendered_data["amendmentEntries"]
    assert [(e["employeeId"], e["myTaxPortalAmendment"]) for e in entries] == [(acknowledged["a"].id, mod["delta"][a])]
    assert entries[0]["nricFinMasked"].startswith("*") and "S1234567D" not in str(entries)


def test_amendments_accumulate_against_the_acknowledged_position(db, organization, acknowledged):
    base, a = acknowledged["base"], str(acknowledged["a"].id)
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    first = _modify(db, organization, base, "AMENDMENT")
    _file(db, organization, first)
    _payslip(db, organization, acknowledged["a"], date(2026, 9, 30), "500", "0", acknowledged["pack"])
    second = _modify(db, organization, base, "AMENDMENT")
    assert second["previousPosition"][a]["grossSalary"] == 7000                         # after the first
    assert second["delta"] == {a: {"grossSalary": 500}}                                  # never re-applied
    _file(db, organization, second)
    assert _position(db, base)[a]["grossSalary"] == 7500 and second["sequence"] == 2


# ── 10–12: duplicates, rejection, UNKNOWN ──────────────────────────────────

def test_duplicate_or_empty_amendments_are_refused_and_audited(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException

    base = acknowledged["base"]
    with pytest.raises(BadRequestException, match="nothing to amend"):
        _modify(db, organization, base, "AMENDMENT")
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    first = _modify(db, organization, base, "AMENDMENT")
    _file(db, organization, first, outcome=None)                                         # SUBMITTED_MANUALLY: open
    with pytest.raises(BadRequestException, match="record IRAS's outcome"):
        _modify(db, organization, base, "AMENDMENT")
    assert [r.new_value["attempted"] for r in _refused(db, base.id)] == ["ir8a_amendment", "ir8a_amendment"]


def test_an_unfiled_modification_is_superseded_and_can_never_be_filed(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport

    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    first = _modify(db, organization, acknowledged["base"], "AMENDMENT")
    second = _modify(db, organization, acknowledged["base"], "AMENDMENT")                # regenerate
    assert db.query(GeneratedReport).get(first["reportId"]).status == "Superseded"
    assert (second["delta"], second["resultingPosition"]) == (first["delta"], first["resultingPosition"])   # deterministic
    with pytest.raises(BadRequestException):
        service.transition_sg_ir8a(db, organization.id, first["reportId"], "SUBMITTED_MANUALLY", actor_id=_actors()[1],
                                   reference="X")


def test_rejected_modification_keeps_the_position_and_a_new_one_may_follow(db, organization, acknowledged):
    base = acknowledged["base"]
    before = _position(db, base)
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    rejected = _modify(db, organization, base, "AMENDMENT")
    _file(db, organization, rejected, outcome="REJECTED")
    assert _position(db, base) == before
    retry = _modify(db, organization, base, "AMENDMENT")
    assert retry["sequence"] == 2 and retry["delta"] == rejected["delta"]


def test_unknown_outcome_is_never_success(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException

    base = acknowledged["base"]
    before = _position(db, base)
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    _file(db, organization, _modify(db, organization, base, "AMENDMENT"), outcome="UNKNOWN")
    assert _position(db, base) == before                                                # not applied
    with pytest.raises(BadRequestException, match="UNKNOWN"):
        _modify(db, organization, base, "AMENDMENT")                                     # still open


# ── 13–14: maker-checker, refusal audit ────────────────────────────────────

def test_the_preparer_cannot_record_the_modification_filing(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import SgpIr8aModification

    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    mod = _modify(db, organization, acknowledged["base"], "AMENDMENT")
    maker, checker = _actors()
    with pytest.raises(BadRequestException, match="distinct operator"):
        service.transition_sg_ir8a(db, organization.id, mod["reportId"], "SUBMITTED_MANUALLY", actor_id=maker, reference="X")
    assert len(_refused(db, mod["reportId"])) == 1
    service.transition_sg_ir8a(db, organization.id, mod["reportId"], "SUBMITTED_MANUALLY", actor_id=checker, reference="Y")
    row = db.query(SgpIr8aModification).get(mod["id"])
    assert (row.prepared_by_id, row.recorded_by_id) == (maker, checker)


def test_refused_modifications_are_audited(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    maker, _ = _actors()
    unacknowledged = _original(db, organization, acknowledged["template"], year=2025, outcome=None)
    for report, method, match in ((unacknowledged, "AMENDMENT", "Only an IRAS-acknowledged"),
                                  (acknowledged["base"], "OVERWRITE", "Unknown IR8A modification method")):
        with pytest.raises(BadRequestException, match=match):
            service.create_sg_ir8a_modification(db, organization.id, report.id, method, actor_id=maker)
    assert [r.new_value["attempted"] for r in _refused(db, unacknowledged.id)] == ["ir8a_amendment"]
    assert [r.new_value["attempted"] for r in _refused(db, acknowledged["base"].id)] == ["ir8a_overwrite"]


def test_a_modification_cannot_itself_be_modified(db, organization, acknowledged):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import GeneratedReport

    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    mod = _modify(db, organization, acknowledged["base"], "REVISION")
    _file(db, organization, mod)
    with pytest.raises(BadRequestException, match="itself a modification"):
        _modify(db, organization, db.query(GeneratedReport).get(mod["reportId"]), "AMENDMENT")


def test_a_stale_modification_cannot_be_filed(db, organization, acknowledged):
    """Defence in depth: filing re-checks the position the delta was computed from."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import SgpIr8aModification

    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    mod = _modify(db, organization, acknowledged["base"], "AMENDMENT")
    row = db.query(SgpIr8aModification).get(mod["id"])
    row.previous_position = {"0": {}}
    db.commit()
    with pytest.raises(BadRequestException, match="has since changed"):
        service.transition_sg_ir8a(db, organization.id, mod["reportId"], "SUBMITTED_MANUALLY", actor_id=_actors()[1],
                                   reference="X")


# ── 15: tenant isolation / Super Admin without an organization ─────────────

def test_modifications_are_tenant_isolated(db, organization, acknowledged):
    from fastapi import HTTPException

    from app.modules.payroll import service
    from tests.test_singapore import _other_org

    other = _other_org(db, "P68OTHER")
    maker, _ = _actors()
    for org_id in (other.id, None):                                                     # other tenant; Super Admin (no org)
        with pytest.raises(HTTPException) as exc:
            service.create_sg_ir8a_modification(db, org_id, acknowledged["base"].id, "AMENDMENT", actor_id=maker)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            service.list_sg_ir8a_modifications(db, org_id, acknowledged["base"].id)
        assert exc.value.status_code == 404


def test_modification_routes_use_payroll_operator_rbac_and_the_callers_organization():
    import inspect

    from app.core.dependencies import get_current_payroll_operator
    from app.main import app
    from app.modules.payroll import router

    for method in ("POST", "GET"):
        route = next(r for r in app.routes if getattr(r, "path", None) == "/api/payroll/singapore/reports/ir8a/{report_id}/modifications"
                     and method in r.methods)
        assert get_current_payroll_operator in {d.call for d in route.dependant.dependencies}
    for fn in (router.create_sg_ir8a_modification, router.list_sg_ir8a_modifications):
        assert "current_user.organization_id" in inspect.getsource(fn)


# ── 16–20: versions, regeneration, immutability, years ─────────────────────

def test_pack_and_template_versions_are_preserved(db, organization, acknowledged):
    from app.modules.payroll.models import GeneratedReport, TaxConfigurationAudit

    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    mod = _modify(db, organization, acknowledged["base"], "AMENDMENT")
    report = db.query(GeneratedReport).get(mod["reportId"])
    assert (report.applicable_tax_pack_version, report.template_version) == ("1.2", acknowledged["base"].template_version)
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "sg_ir8a_modification",
                                                   TaxConfigurationAudit.entity_id == mod["id"]).one()
    assert (audit.action, audit.new_value["applicableTaxPackVersion"], audit.new_value["templateVersion"]) == (
        "create", "1.2", "1.0")
    assert audit.old_value == {"position": mod["previousPosition"]} and audit.new_value["delta"] == mod["delta"]


def test_acknowledged_modifications_stay_immutable_after_later_ones(db, organization, acknowledged):
    from app.modules.payroll.models import GeneratedReport, SgpIr8aModification

    base = acknowledged["base"]
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    first = _modify(db, organization, base, "AMENDMENT")
    _file(db, organization, first)
    frozen = (db.query(GeneratedReport).get(first["reportId"]).rendered_data,
              db.query(SgpIr8aModification).get(first["id"]).resulting_position)
    _payslip(db, organization, acknowledged["b"], date(2026, 6, 30), "300", "0", acknowledged["pack"])
    _file(db, organization, _modify(db, organization, base, "REVISION"))
    db.expire_all()
    assert db.query(GeneratedReport).get(first["reportId"]).status == "ACKNOWLEDGED"
    assert (db.query(GeneratedReport).get(first["reportId"]).rendered_data,
            db.query(SgpIr8aModification).get(first["id"]).resulting_position) == frozen


def test_income_years_are_isolated(db, organization, acknowledged):
    from app.modules.payroll import service

    _payslip(db, organization, acknowledged["a"], date(2025, 3, 31), "2000", "0", acknowledged["pack"])
    base_2025 = _original(db, organization, acknowledged["template"], year=2025)
    _payslip(db, organization, acknowledged["a"], date(2026, 6, 30), "1000", "0", acknowledged["pack"])
    mod_2026 = _modify(db, organization, acknowledged["base"], "AMENDMENT")
    a = str(acknowledged["a"].id)
    assert _position(db, base_2025)[a]["grossSalary"] == 2000                           # untouched by 2026
    assert mod_2026["delta"] == {a: {"grossSalary": 1000}}
    assert service.list_sg_ir8a_modifications(db, organization.id, base_2025.id) == []
