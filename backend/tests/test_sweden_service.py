"""Sweden (ZP-SE-ENG-001) service layer — seed, governance gates, readiness,
statutory-profile validation, canonical sync, the youth month accumulator,
sick-pay episodes, leave ledgers, the collective-agreement registry and the
migration's idempotency guards. SQLite `db` fixture only."""
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import (
    CollectiveAgreement, ContributionRate, JurisdictionPack, PayrollEmployee, PayrollRun, PayslipItem, TaxSlab,
)
from app.modules.payroll.schemas import (
    CollectiveAgreementUpsert, EmployeeStatutoryProfileCreate, SwedenCalculationPreviewRequest,
    SwedenLeaveLedgerUpsert, SwedenSickEpisodeUpsert,
)
from scripts import seed_sweden_canonical_packs as seed

MAKER, CHECKER, ACTIVATOR = 101, 202, 303


@pytest.fixture()
def seeded(db):
    out = seed.seed_sweden(db)
    db.commit()
    return out


def _pack(db, pack_id="SE-PAYROLL-2026"):
    return db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == pack_id).one()


def _se_employee(db, org, code="SE1", country="SE", **kw):
    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Employee {code}", country_code=country,
                          ctc=D("480000"), date_of_birth=date(1990, 3, 3),
                          compliance_fields={"swedish_id_number": "19900303-1234"}, **kw)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


# ── Seed ────────────────────────────────────────────────────────────────

def test_seed_creates_draft_packs_scaffolds_and_evidence(db, seeded):
    p26, p27 = _pack(db), _pack(db, "SE-PAYROLL-2027")
    assert (p26.status, p27.status) == ("Draft", "Draft")
    assert (p26.effective_from, p26.effective_to) == (date(2026, 1, 1), date(2026, 12, 31))
    assert p26.source_document_id == seeded["source_id"] and p26.currency == "SEK"
    rates = {r.component_key: r for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == p26.id)}
    assert rates["se_sink"].employee_rate_pct == D("22.5")
    assert (rates["se_youth_reduced"].effective_from, rates["se_youth_reduced"].effective_to) == (date(2026, 4, 1), date(2027, 9, 30))
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == p26.id).all()
    assert len([s for s in slabs if s.rule_type == "SE_TAX_TABLE"]) == 14 * 6
    assert all(s.assessment_basis is None and s.flat_amount is None for s in slabs)
    rates27 = {r.component_key: r for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == p27.id)}
    assert rates27["se_sink"].employee_rate_pct == D("20")
    assert "se_er_age_pension" not in rates27   # 2027 components not stated in the spec — blocked, never copied


def test_seed_is_idempotent(db, seeded):
    before = (db.query(ContributionRate).count(), db.query(TaxSlab).count())
    again = seed.seed_sweden(db)
    db.commit()
    assert all(c == {"inserted": 0, "deleted": 0} for ch in again["changes"] for c in ch.values())
    assert (db.query(ContributionRate).count(), db.query(TaxSlab).count()) == before


def test_seed_refuses_a_pack_that_left_draft(db, seeded):
    _pack(db).status = "In Review"
    db.commit()
    with pytest.raises(SystemExit):
        seed.seed_sweden(db)


def test_agi_calendar_rolls_weekends_and_holidays():
    dates = dict(seed.agi_due_dates(2026))
    assert dates[1] == date(2026, 2, 12)
    assert dates[3] == date(2026, 4, 13)    # 12 Apr 2026 is a Sunday
    assert dates[7] == date(2026, 8, 17)    # August declarations are due on the 17th
    assert dates[8] == date(2026, 9, 14)    # 12 Sep 2026 is a Saturday
    assert dates[12] == date(2027, 1, 18)   # January 17th (Sunday) → Monday


# ── Governance gates ────────────────────────────────────────────────────

def test_activation_requires_se_certification_pass(db, seeded):
    with pytest.raises(BadRequestException, match="golden-vector certification"):
        service.set_jurisdiction_pack_status(db, _pack(db).id, "Active", actor_id=ACTIVATOR)


def test_activation_refused_while_tax_table_scaffolds_remain(db, seeded):
    service.run_golden_test_certification(db, jurisdiction_country="SE", actor_id=CHECKER)
    with pytest.raises(BadRequestException, match="not complete enough"):
        service.set_jurisdiction_pack_status(db, _pack(db).id, "Active", actor_id=ACTIVATOR)
    assert _pack(db).status == "Draft"


def test_activation_blockers_list_2027_missing_components(db, seeded):
    blockers = service.se_activation_blockers(db, _pack(db, "SE-PAYROLL-2027"))
    assert any("se_er_age_pension" in b for b in blockers)
    assert any("se_older_cohort_max_birth_year" in b for b in blockers)
    assert any("unfilled Draft scaffolds" in b for b in blockers)


def test_filled_pack_has_no_content_blockers(db, seeded):
    pack = _pack(db)
    for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        s.assessment_basis, s.flat_amount = "AMOUNT", D("1000")
    db.commit()
    assert service.se_activation_blockers(db, pack) == []


def test_sweden_hotfix_activation_is_never_allowed(db, seeded):
    with pytest.raises(BadRequestException, match="hotfix activation is not permitted"):
        service.activate_jurisdiction_pack_hotfix(db, _pack(db).id, "INC-1", "urgent", actor_id=MAKER)


def test_sweden_is_opted_into_every_sg_level_gate():
    for name in ("_APPROVER_NOT_ACTIVATOR_COUNTRIES", "_SELF_APPROVAL_REFUSED_COUNTRIES", "_REFUSAL_AUDIT_COUNTRIES",
                 "_PACK_TRANSITION_GRAPH_COUNTRIES", "_HOTFIX_DISTINCT_REVIEWER_COUNTRIES"):
        assert "SE" in getattr(service, name), name


# ── Readiness + preview ─────────────────────────────────────────────────

def test_readiness_is_never_ready_on_seeded_content(db, seeded):
    r = service.get_se_readiness(db, _pack(db).id)
    items = {i["key"]: i for i in r["items"]}
    assert r["ready"] is False and r["packId"] is not None
    assert items["source_evidence"]["complete"] and items["parameters"]["complete"]
    assert items["agi_calendar"]["complete"] and items["agi_template"]["complete"]
    for key in ("tax_tables", "certification", "specialist_review", "agi_xml", "parallel_payroll"):
        assert not items[key]["complete"], key


def test_preview_blocks_on_scaffold_and_computes_youth_relief(db, seeded):
    pack = _pack(db)
    blocked = service.preview_sweden_calculation(db, SwedenCalculationPreviewRequest(
        jurisdictionPackId=pack.id, payDate=date(2026, 5, 25), gross=D("40000"), dateOfBirth=date(1990, 1, 1),
        taxTable="32", taxColumn="1"))
    assert blocked["blocked"] and blocked["blockedKey"] == "se_tax_table"
    ok = service.preview_sweden_calculation(db, SwedenCalculationPreviewRequest(
        jurisdictionPackId=pack.id, payDate=date(2026, 5, 25), gross=D("40000"), dateOfBirth=date(2005, 1, 1),
        incomeRole="SUPPLEMENTARY_INCOME"))
    assert not ok["blocked"]
    assert ok["sweden"]["employer"]["amount"] == "9915.50"   # 25,000 @ 20.81% + 15,000 @ 31.42%
    assert ok["sweden"]["withholding"]["amount"] == "12000.00"


def test_preview_before_youth_window_is_not_blocked(db, seeded):
    """The youth rows are absent before 1 Apr 2026; that must not block."""
    out = service.preview_sweden_calculation(db, SwedenCalculationPreviewRequest(
        jurisdictionPackId=_pack(db).id, payDate=date(2026, 2, 25), gross=D("40000"), dateOfBirth=date(2005, 1, 1),
        incomeRole="SUPPLEMENTARY_INCOME"))
    assert not out["blocked"] and out["sweden"]["employer"]["cohort"] == "STANDARD"


# ── Canonical → org sync keeps Sweden's discriminators ──────────────────

def test_sync_propagates_table_column_basis_and_youth_window(db, seeded, organization):
    pack = _pack(db)
    for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        s.assessment_basis, s.flat_amount = "AMOUNT", D("1000")
    pack.status = "Active"
    db.commit()
    out = service.sync_org_rates_from_canonical(db, organization.id, "SE", payroll_date=date(2026, 5, 1))
    assert out["synced"]
    org_slab = db.query(TaxSlab).filter(TaxSlab.organization_id == organization.id,
                                        TaxSlab.tax_table_number == "32", TaxSlab.tax_column == "1").one()
    assert org_slab.assessment_basis == "AMOUNT"
    youth = db.query(ContributionRate).filter(ContributionRate.organization_id == organization.id,
                                              ContributionRate.component_key == "se_youth_reduced").one()
    assert (youth.effective_from, youth.effective_to) == (date(2026, 4, 1), date(2027, 9, 30))


# ── Statutory profile validation ────────────────────────────────────────

def _profile(**kw):
    return EmployeeStatutoryProfileCreate(effectiveFrom=date(2026, 1, 1), **kw)


@pytest.mark.parametrize("kwargs,fragment", [
    (dict(seTaxStatus="A-TAX"), "se_tax_status must be one of"),
    (dict(seTaxStatus="A_TAX", seIncomeRole="MAIN_INCOME"), "needs se_tax_table and se_tax_column"),
    (dict(seTaxStatus="SINK"), "se_sink_status is required"),
    (dict(seTaxTable="12"), "29–42"),
    (dict(seDecisionOverride=True), "se_skatteverket_decision_id is required"),
    (dict(seDecisionOverride=True, seSkatteverketDecisionId="D1", seDecisionEffectiveFrom=date(2026, 1, 1),
          reason="r"), "needs se_decision_monthly_withholding or se_decision_rate_pct"),
    (dict(seCbaStatus="SECTOR"), "se_cba_id is required"),
    (dict(seCbaStatus="NONE", seCbaId=4), "must be empty"),
])
def test_profile_validation_refuses_uncalculable_states(kwargs, fragment):
    errors = service._se_profile_field_errors(_profile(**kwargs))
    assert any(fragment in e for e in errors), errors


def test_profile_validation_accepts_a_complete_a_tax_profile():
    assert service._se_profile_field_errors(_profile(
        seTaxStatus="A_TAX", seIncomeRole="MAIN_INCOME", seTaxTable="32", seTaxColumn="1", seCbaStatus="NONE")) == []


# ── Youth month accumulator ─────────────────────────────────────────────

def test_month_to_date_counts_only_committed_runs_in_the_payment_month(db, organization):
    emp = _se_employee(db, organization)

    def run(pay_date, status, gross):
        r = PayrollRun(organization_id=organization.id, period_label=str(pay_date), period_start=pay_date.replace(day=1),
                       period_end=pay_date, pay_date=pay_date, status=status)
        db.add(r)
        db.flush()
        db.add(PayslipItem(payroll_run_id=r.id, employee_id=emp.id, organization_id=organization.id,
                           employee_name=emp.name, gross_pay=gross))
        db.commit()
        return r

    run(date(2026, 5, 10), "Approved", D("15000"))
    run(date(2026, 5, 15), "Draft", D("9000"))       # not yet payroll
    run(date(2026, 4, 25), "Paid", D("7000"))        # a different payment month
    current = run(date(2026, 5, 25), "Approved", D("5000"))
    prior = service._se_month_to_date_prior(db, organization.id, emp.id, date(2026, 5, 25), exclude_run_id=current.id)
    assert prior == D("15000")


# ── Sick-pay episodes ───────────────────────────────────────────────────

def _sick(db, org, emp, start, end, **kw):
    data = SwedenSickEpisodeUpsert(employeeId=emp.id, episodeStart=start, episodeEnd=end,
                                   expectedWeeklySickPay=kw.pop("weekly", D("5000")), qualifyingDeductionPct=D("20"), **kw)
    return service.upsert_se_sick_episode(db, org.id, data, actor_id=MAKER)


def test_recurrence_within_five_days_shares_one_period_and_one_deduction(db, organization):
    emp = _se_employee(db, organization)
    first = _sick(db, organization, emp, date(2026, 3, 2), date(2026, 3, 6))
    assert first.qualifying_deduction_amount == D("1000.00")   # 20% × 5,000
    assert (first.employer_period_day_from, first.employer_period_day_to) == (1, 5)
    again = _sick(db, organization, emp, date(2026, 3, 10), date(2026, 3, 13))
    assert again.recurrence_group_id == first.id
    assert again.qualifying_deduction_amount == D("0") and again.employer_period_day_from == 6
    later = _sick(db, organization, emp, date(2026, 4, 20), date(2026, 4, 21))
    assert later.recurrence_group_id is None and later.qualifying_deduction_amount == D("1000.00")


def test_deduction_never_exceeds_payable_sick_pay_and_day_15_transfers(db, organization):
    emp = _se_employee(db, organization)
    ep = _sick(db, organization, emp, date(2026, 5, 4), date(2026, 5, 22), employerSickPayAmount=D("600"))
    assert ep.qualifying_deduction_amount == D("600")
    assert ep.employer_period_day_to == 14 and ep.transfer_to_forsakringskassan


def test_sick_episode_needs_a_deduction_percentage_source(db, organization):
    emp = _se_employee(db, organization)
    with pytest.raises(BadRequestException, match="qualifying-deduction percentage"):
        service.upsert_se_sick_episode(db, organization.id, SwedenSickEpisodeUpsert(
            employeeId=emp.id, episodeStart=date(2026, 6, 1), episodeEnd=date(2026, 6, 2),
            expectedWeeklySickPay=D("5000")))


def test_sick_episodes_are_sweden_only(db, organization):
    emp = _se_employee(db, organization, code="UK1", country="UK")
    with pytest.raises(BadRequestException, match="Sweden employee"):
        _sick(db, organization, emp, date(2026, 3, 2), date(2026, 3, 3))


# ── Leave ledgers ───────────────────────────────────────────────────────

def _ledger(**kw):
    base = dict(employeeId=0, entitlementYear="2026", paidDays=D("25"), unpaidDays=D("0"), savedDays=D("0"))
    base.update(kw)
    return SwedenLeaveLedgerUpsert(**base)


def test_leave_ledger_statutory_bounds(db, organization):
    emp = _se_employee(db, organization)
    row = service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, savedDays=D("5")), MAKER)
    assert (row.paid_days, row.saved_days) == (D("25"), D("5"))
    with pytest.raises(BadRequestException, match="25-day statutory entitlement"):
        service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, paidDays=D("26")), MAKER)
    with pytest.raises(BadRequestException, match="exceeding 20"):
        service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, paidDays=D("22"), savedDays=D("3")), MAKER)
    with pytest.raises(BadRequestException, match="cbaAgreementId"):
        service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, vacationPayMethod="CBA_OVERRIDE"), MAKER)
    with pytest.raises(BadRequestException, match="five years"):
        service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, carryoverExpiry=date(2032, 3, 31)), MAKER)


def test_leave_ledger_upserts_one_row_per_entitlement_year(db, organization):
    emp = _se_employee(db, organization)
    service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, paidDays=D("10")), MAKER)
    service.upsert_se_leave_ledger(db, organization.id, _ledger(employeeId=emp.id, paidDays=D("12")), MAKER)
    rows = service.list_se_leave_ledgers(db, organization.id, emp.id)
    assert len(rows) == 1 and rows[0].paid_days == D("12")


# ── Collective-agreement registry ───────────────────────────────────────

def _cba(**kw):
    base = dict(jurisdictionCountry="SE", agreementCode="SE-SECTOR-TEST", name="Test agreement",
                agreementType="SECTOR", modules=["overtime"], effectiveFrom=date(2026, 1, 1))
    base.update(kw)
    return CollectiveAgreementUpsert(**base)


def test_no_national_default_agreement(db):
    with pytest.raises(BadRequestException, match="no national"):
        service.upsert_collective_agreement(db, _cba(agreementType="NATIONAL"), actor_id=MAKER)
    with pytest.raises(BadRequestException, match="Unknown agreement module"):
        service.upsert_collective_agreement(db, _cba(modules=["everything"]), actor_id=MAKER)


def test_agreement_lifecycle_is_four_eyes(db, seeded):
    row = service.upsert_collective_agreement(db, _cba(), actor_id=MAKER)
    service.set_collective_agreement_status(db, row.id, "In Review", actor_id=MAKER)
    with pytest.raises(BadRequestException, match="different Super Admin"):
        service.set_collective_agreement_status(db, row.id, "Approved", actor_id=MAKER)
    service.set_collective_agreement_status(db, row.id, "Approved", actor_id=CHECKER)
    with pytest.raises(BadRequestException, match="source artifact"):
        service.set_collective_agreement_status(db, row.id, "Active", actor_id=ACTIVATOR)
    db.query(CollectiveAgreement).filter(CollectiveAgreement.id == row.id).update(
        {"source_document_id": seeded["source_id"]})
    db.commit()
    with pytest.raises(BadRequestException, match="cannot also activate"):
        service.set_collective_agreement_status(db, row.id, "Active", actor_id=CHECKER)
    active = service.set_collective_agreement_status(db, row.id, "Active", actor_id=ACTIVATOR)
    assert active.status == "Active"
    with pytest.raises(BadRequestException, match="create a new"):
        service.upsert_collective_agreement(db, _cba(id=row.id), actor_id=MAKER)


def test_activating_a_new_version_supersedes_the_old(db, seeded):
    def activate(version):
        row = service.upsert_collective_agreement(db, _cba(version=version, sourceDocumentId=seeded["source_id"]), actor_id=MAKER)
        for status, actor in (("In Review", MAKER), ("Approved", CHECKER), ("Active", ACTIVATOR)):
            service.set_collective_agreement_status(db, row.id, status, actor_id=actor)
        return row.id

    v1 = activate("1.0")
    activate("2.0")
    assert db.get(CollectiveAgreement, v1).status == "Superseded"


# ── Snapshot + migration ────────────────────────────────────────────────

def test_payslip_snapshot_is_none_for_other_countries():
    assert service._se_payslip_snapshot(SimpleNamespace(se_employee_total=None)) is None


def test_migration_is_idempotent_by_construction():
    text = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "e8f1a2b3c4d5_add_sweden_jurisdiction_support.py").read_text(encoding="utf-8")
    upgrade = text.split("def upgrade()")[1].split("def downgrade()")[0]
    for table in ("payroll_collective_agreements", "payroll_sweden_sick_episodes", "payroll_sweden_leave_ledgers"):
        assert f"if not _has_table('{table}')" in upgrade
    assert "op.add_column(" not in upgrade   # every column add goes through the _add_column guard
