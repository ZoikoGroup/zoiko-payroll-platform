"""
tests/test_singapore_multi_pack_reports.py
------------------------------------------
Singapore final completion programme (2026-09-29): a report over payslips
calculated under MORE THAN ONE statutory pack version must record every
pack used (rendered_data["metadata"]["taxPacksUsed"], sorted) and pin no
single version — never silently the latest pack.

Phase 6.5 (test_singapore_phase65_hardening.py) proves this for SDL, IR8A
and EZPay. This file closes the remaining generators: the generic
template generator (SG payroll register / summary / CPF contribution / SHG /
FWL all render through it), PWM compliance, LQS compliance and the IR21
register. It also pins the generic generator's list order: it was
list(set), whose order follows insertion when ids collide in the hash table
(e.g. 1001 / 1009), so a regenerated report could differ; it is now sorted
like every dedicated Singapore generator.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date

import pytest

from tests.test_singapore_phase65_hardening import A, _ir21_case, _packs, _payslips, _template


def _two_pack_month(db, organization):
    """May 2026 payslips under two versions of the SG pack. Explicit ids 1001
    and 1009 share a slot in a small Python set's hash table, so a list built
    from a set follows insertion order; the v1.3 (id 1009) payslips are
    inserted FIRST, so only a sorted list comes out [1001, 1009]."""
    from app.modules.payroll.models import JurisdictionPack

    p12 = JurisdictionPack(id=1001, pack_id="SG-MP", jurisdiction_country="SG", pack_type="tax", version="1.2",
                           status="Superseded", effective_from=date(2026, 1, 1))
    p13 = JurisdictionPack(id=1009, pack_id="SG-MP", jurisdiction_country="SG", pack_type="tax", version="1.3",
                           status="Active", effective_from=date(2026, 5, 15))
    db.add_all([p12, p13])
    db.commit()
    assert list({p13.id, p12.id}) == [p13.id, p12.id]          # the precondition: a set does NOT sort these
    second = _payslips(db, organization, p13, codes=("M2",))
    first = _payslips(db, organization, p12, codes=("M1",))
    return p12, p13, first, second


def _assert_lists_both(rep, p12, p13):
    assert (rep.applicable_tax_pack_id, rep.applicable_tax_pack_version) == (None, None)   # no single version claimed
    assert rep.rendered_data["metadata"]["taxPacksUsed"] == sorted([p12.id, p13.id])     # every pack, deterministic


@pytest.mark.parametrize("report_type", ["SG_PAYROLL_REGISTER", "SG_PAYROLL_SUMMARY", "SG_CPF_CONTRIBUTION",
                                         "SG_SHG_MONTHLY", "SG_FWL_MONTHLY"])
def test_the_generic_generator_lists_every_pack_of_a_mixed_run(db, organization, report_type):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    p12, p13, first, second = _two_pack_month(db, organization)
    # One run holding payslips from both packs (a mid-run pack change).
    for item in first:
        item.payroll_run_id = second[0].payroll_run_id
    db.commit()
    run_id = second[0].payroll_run_id
    in_order = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run_id).order_by(PayslipItem.id).all()
    assert [i.tax_policy_pack_id for i in in_order] == [p13.id, p12.id]             # the later pack's rows come first
    rep = service.generate_report_from_template(db, organization.id, _template(db, f"SG-MP-{report_type}", report_type).id,
                                                run_id, actor_id=A)
    _assert_lists_both(rep, p12, p13)


def test_the_generic_generator_still_pins_a_single_pack_run(db, organization):
    from app.modules.payroll import service

    p12 = _packs(db)
    items = _payslips(db, organization, p12)
    rep = service.generate_report_from_template(db, organization.id, _template(db, "SG-MP-ONE", "SG_PAYROLL_REGISTER").id,
                                                items[0].payroll_run_id, actor_id=A)
    assert (rep.applicable_tax_pack_id, rep.applicable_tax_pack_version) == (p12.id, "1.2")
    assert "taxPacksUsed" not in (rep.rendered_data.get("metadata") or {})


@pytest.mark.parametrize("report_type, generate", [
    ("SG_PWM_COMPLIANCE", lambda service, db, org, t: service.generate_sg_pwm_compliance(db, org.id, t.id, 2026, 5, actor_id=A)),
    ("SG_LQS_COMPLIANCE", lambda service, db, org, t: service.generate_sg_lqs_compliance(db, org.id, t.id, 2026, 5, actor_id=A)),
])
def test_wage_month_workspaces_list_every_pack_of_the_month(db, organization, report_type, generate):
    from app.modules.payroll import service

    p12, p13, _first, _second = _two_pack_month(db, organization)
    rep = generate(service, db, organization, _template(db, f"SG-MP-{report_type}", report_type))
    _assert_lists_both(rep, p12, p13)


def test_the_ir21_register_lists_every_pack_its_held_payslips_used(db, organization):
    from app.modules.payroll import service

    p12, p13, first, second = _two_pack_month(db, organization)
    _ir21_case(db, organization, first[0])
    _ir21_case(db, organization, second[0])
    rep = service.generate_sg_ir21_register(db, organization.id, _template(db, "SG-MP-IR21", "SG_IR21_REGISTER").id,
                                            2026, actor_id=A, today=date(2026, 6, 1))
    _assert_lists_both(rep, p12, p13)
