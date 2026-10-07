"""Italy F24 payable liability objects (§16, IT-043/IT-046/IT-047).

A F24 is a payment instruction, and one code on it decides which authority gets
paid what. That makes this module's real subject REFUSAL rather than
calculation:

  * IT-043 forbids inventing a causale, so the catalog ships empty and a build
    with nothing governed in force must refuse - the single most important
    assertion here, because a fallback "default" causale would be the one change
    that turns a safe refusal into a silent wrong payment.
  * A component the engine actually withheld, but for which no causale is
    governed, must refuse the WHOLE build. Emitting the mapped components and
    quietly dropping the unmapped one produces a line that looks complete while
    understating the liability.
  * A regional or municipal causale whose employee has no tax-domicile codes
    cannot be attributed to an authority, so it refuses rather than defaulting to
    a national aggregate.
  * A draft run is refused: paying from a run that may still be recalculated is
    worse than not paying yet.

And on the positive side, the build must be IDEMPOTENT. Re-deriving the same
period from the same committed run has to converge on one set of lines, because a
retried build that appends a duplicate has turned a build step into a second
payment instruction (IT-044).

SQLite `db` fixture only - nothing here reaches a real database.
"""
from datetime import date
from decimal import Decimal as D

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import (
    EmployeeStatutoryProfile, ItalyF24Causale, ItalyF24Line, PayrollEmployee,
    PayrollRun, PayslipItem, StatutoryFiling,
)
from app.modules.payroll.schemas import ItalyF24BuildRequest, ItalyF24CausaleUpsert


def _employee(db, organization, code="IT1", region=None, comune=None):
    employee = PayrollEmployee(organization_id=organization.id, employee_code=code,
                               name=f"Worker {code}", country_code="IT")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    if region or comune:
        # IT-031: the tax domicile decides which regional/municipal authority
        # the withholding is owed to, so it is what the F24 lines read.
        db.add(EmployeeStatutoryProfile(
            employee_id=employee.id, organization_id=organization.id,
            country_code="IT", effective_from=date(2026, 1, 1),
            it_tax_domicile_region=region,
            it_tax_domicile_comune=comune,
        ))
        db.commit()
    return employee


def _run(db, organization, status="Approved", run_code="IT-2026-10"):
    run = PayrollRun(
        organization_id=organization.id, run_code=run_code,
        period_label="Oct 2026", period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31),
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


_MINIMAL_SNAPSHOT = {
    "inps": {"employee": "0.00", "employer": "0.00", "base": "10000.00",
             "additional1pct": "0.00", "minimumApplied": False},
    "irpef": {"withheld": "900.00", "refund": None, "annualNet": "42000.00",
              "detrazione": "1500.00", "additionalDeduction": "0.00"},
    "wedge": {"taxFreeSum": "0.00", "recoveredNow": "0.00"},
    "localTax": {"regionalSaldo": "0.00", "municipalSaldo": "0.00",
                 "municipalAcconto": "0.00", "terminationWithheld": None},
}

# A payslip that owes in every section, so the derivation has to split it across
# INPS / ERARIO / REGIONI / ENTI_LOCALI rather than collapse it into one line.
_FULL_SNAPSHOT = {
    "inps": {"employee": "1200.00", "employer": "3100.00", "base": "10000.00",
             "additional1pct": "100.00", "minimumApplied": False},
    "irpef": {"withheld": "900.00", "refund": None, "annualNet": "42000.00",
              "detrazione": "1500.00", "additionalDeduction": "0.00"},
    "wedge": {"taxFreeSum": "0.00", "recoveredNow": "50.00"},
    "localTax": {"regionalSaldo": "80.00", "municipalSaldo": "40.00",
                 "municipalAcconto": "30.00", "terminationWithheld": None},
}


def _payslip(db, organization, run, employee, snapshot=None, **sections):
    """One committed Italy payslip carrying an it_calculation_snapshot.

    Snapshot values are exact strings, mirroring it_payslip_snapshot's
    Decimal-as-string contract, so a float can never enter the liability.
    `sections` overrides one or more top-level snapshot sections by name, e.g.
    inps={"employee": "1200.00"} or withheld="0.10" for irpef.withheld.

    Defaults to a snapshot that owes IRPEF and nothing else. Because the builder
    refuses the WHOLE build when any owed component is ungoverned (IT-043), a
    minimal snapshot is what lets a test isolate one section without first
    having to govern the entire catalog. Tests that need a full obligation pass
    snapshot=_FULL_SNAPSHOT.
    """
    data = dict(snapshot or _MINIMAL_SNAPSHOT)
    for section_name, override in sections.items():
        key = "irpef" if section_name == "withheld" else section_name
        if key not in data or not isinstance(data[key], dict):
            continue
        # A bare string is shorthand for that section's headline amount.
        data[key] = ({**data[key], "withheld": override}
                     if isinstance(override, str) else {**data[key], **override})
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, basic_salary=10000, gross_pay=10000,
        total_deductions=2300, net_pay=7700,
        it_calculation_snapshot=data,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _causale(db, organization, component_key, section="ERARIO", tax_code="1001",
             direction="DEBIT", **kw):
    defaults = dict(section=section, componentKey=component_key, taxCode=tax_code,
                    direction=direction, effectiveFrom=date(2026, 1, 1))
    defaults.update(kw)
    return service.upsert_italy_f24_causale(
        db, organization.id, ItalyF24CausaleUpsert(**defaults))


def _build(db, organization, run, period="10/2026", **kw):
    return service.build_italy_f24_lines(
        db, organization.id, ItalyF24BuildRequest(payrollRunId=run.id,
                                                  referencePeriod=period, **kw))


# ── The catalog is governed data, and it ships empty (IT-043) ──────────────

def test_the_causale_catalog_starts_empty(db, organization):
    """Nothing was invented on our behalf. Before an administrator records real
    Agenzia delle Entrate codes, there are no codes."""
    assert service.list_italy_f24_causales(db, organization.id) == []


def test_build_refuses_rather_than_invent_a_causale(db, organization):
    """THE load-bearing refusal: with an empty catalog, a build of a run full of
    real Italian withholdings must fail loudly and write nothing.

    A fallback code here would be invisible in review and irreversible once it
    had moved money, which is exactly the failure IT-043 prohibits."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    with pytest.raises(BadRequestException) as excinfo:
        _build(db, organization, run)
    assert "IT-043" in str(excinfo.value)
    assert db.query(ItalyF24Line).count() == 0


def test_build_refuses_a_component_that_has_no_governed_causale(db, organization):
    """Mapping three components and forgetting the rest must fail the WHOLE
    build.

    Partial output is the dangerous version of this bug: the F24 would carry a
    plausible INPS line and silently omit the IRPEF withheld from the same
    payslip, understating the payment while looking like it succeeded."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization), snapshot=_FULL_SNAPSHOT)
    _causale(db, organization, "inps.employee", section="INPS", tax_code="1000")
    _causale(db, organization, "inps.employer", section="INPS", tax_code="1000")
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    # inps.additional1pct, wedge.recoveredNow and the three local-tax components
    # are all owed on this payslip, and none of them is governed.
    with pytest.raises(BadRequestException) as excinfo:
        _build(db, organization, run)
    assert "no governed causale" in str(excinfo.value)
    assert db.query(ItalyF24Line).count() == 0


def test_a_governed_causale_cannot_be_parked_on_a_component_nothing_derives(db, organization):
    """The catalog only accepts components the engine actually computes. An
    entry for an arbitrary key would look like coverage on screen while no
    derivation ever reads it - coverage that pays nothing."""
    with pytest.raises(BadRequestException) as excinfo:
        _causale(db, organization, "inps.contributoryBase")
    assert "not an F24-remittable snapshot component" in str(excinfo.value)


# ── Deriving the lines (IT-046) ─────────────────────────────────────────────

def _govern_all(db, organization):
    """Govern exactly the components _FULL_SNAPSHOT makes non-zero."""
    _causale(db, organization, "inps.employee", section="INPS", tax_code="1000")
    _causale(db, organization, "inps.employer", section="INPS", tax_code="1000")
    _causale(db, organization, "inps.additional1pct", section="INPS", tax_code="1000")
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    _causale(db, organization, "localTax.regionalSaldo", section="REGIONI",
             tax_code="1020", requiresRegion=True, requiresComune=True)
    _causale(db, organization, "localTax.municipalSaldo", section="ENTI_LOCALI",
             tax_code="1021", requiresRegion=True, requiresComune=True)
    _causale(db, organization, "localTax.municipalAcconto", section="ENTI_LOCALI",
             tax_code="1022", requiresRegion=True, requiresComune=True)
    # A wedge recovery is money coming BACK. The catalog row says so explicitly
    # - the platform does not infer it from the component's name.
    _causale(db, organization, "wedge.recoveredNow", section="ERARIO", tax_code="1002",
             direction="CREDIT")


def test_lines_carry_the_governed_codes_and_the_real_withheld_amounts(db, organization):
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, region="03", comune="F205"),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    lines = _build(db, organization, run)
    by_code = {line.tax_code: line for line in lines}
    assert by_code["1000"].debit_amount == D("4400.00")   # 1200 + 3100 + 100 IVS
    assert by_code["1001"].debit_amount == D("900.00")    # IRPEF withheld
    assert by_code["1020"].debit_amount == D("80.00")     # regional saldo
    assert by_code["1021"].debit_amount == D("40.00")     # municipal saldo
    assert by_code["1022"].debit_amount == D("30.00")     # municipal acconto
    assert by_code["1002"].credit_amount == D("50.00")    # wedge recovery credited
    assert by_code["1002"].debit_amount == D("0.00")
    assert {line.reference_period for line in lines} == {"10/2026"}


def test_one_payslips_liabilities_split_across_sections(db, organization):
    """One employee, several authorities. Collapsing this into a single line
    would tell the tax authority to pay the regional and municipal balances to
    INPS."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, region="03", comune="F205"),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    assert {line.section for line in _build(db, organization, run)} == {
        "INPS", "ERARIO", "REGIONI", "ENTI_LOCALI"}


def test_a_local_authority_line_keeps_the_employee_tax_domicile(db, organization):
    """The same regional causale is split per authority, so the codes that
    decide which authority gets paid must survive onto the line."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, region="03", comune="F205"),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    regional = [line for line in _build(db, organization, run) if line.section == "REGIONI"]
    assert len(regional) == 1
    assert (regional[0].region_code, regional[0].comune_code) == ("03", "F205")


def test_each_employee_s_tax_domicile_produces_its_own_local_line(db, organization):
    """Two employees in different comuni are two payable lines, not one merged
    national total - merging them would pay one commune's rate to another."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, code="IT1",
                                              region="03", comune="F205"),
             snapshot=_FULL_SNAPSHOT)
    _payslip(db, organization, run, _employee(db, organization, code="IT2",
                                              region="03", comune="H703"),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    regional = [line for line in _build(db, organization, run) if line.section == "REGIONI"]
    assert {(l.region_code, l.comune_code, l.debit_amount) for l in regional} == {
        ("03", "F205", D("80.00")), ("03", "H703", D("80.00"))}


def test_local_authority_lines_refuse_without_a_tax_domicile(db, organization):
    """Without region+comune there is no authority to pay, so there is no correct
    line to write. Refusing is the only safe answer."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    with pytest.raises(BadRequestException) as excinfo:
        _build(db, organization, run)
    assert "tax-domicile" in str(excinfo.value)
    assert db.query(ItalyF24Line).count() == 0


def test_a_national_causale_needs_no_tax_domicile(db, organization):
    """ERARIO and INPS are national, so an employee without region/comune must
    not be blocked from paying social security and income tax they genuinely
    owe."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization), inps={
        "employee": "1200.00", "employer": "3100.00", "base": "10000.00",
        "additional1pct": "0.00", "minimumApplied": False})
    _causale(db, organization, "inps.employee", section="INPS", tax_code="1000")
    _causale(db, organization, "inps.employer", section="INPS", tax_code="1000")
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    lines = _build(db, organization, run)
    assert {line.tax_code for line in lines} == {"1000", "1001"}
    # Nothing local was owed, so no local line was invented.
    assert all(line.region_code is None for line in lines)


def test_a_zero_component_produces_no_line(db, organization):
    """Governing a causale for a component this payslip did not withhold must not
    create a zero-value payable line - a zero F24 row is noise at best."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    _causale(db, organization, "inps.employer", section="INPS", tax_code="1000")
    assert [line.tax_code for line in _build(db, organization, run)] == ["1001"]


def test_each_line_records_which_payslips_and_components_produced_it(db, organization):
    """source_lines is what makes the figure defensible: every amount traces
    back to the payslip and snapshot key that computed it."""
    run = _run(db, organization)
    payslip = _payslip(db, organization, run, _employee(db, organization))
    _govern_all(db, organization)
    line = [l for l in _build(db, organization, run) if l.tax_code == "1001"][0]
    assert line.source_lines == [{
        "payslipItemId": payslip.id, "employeeId": payslip.employee_id,
        "componentKey": "irpef.withheld", "amount": "900.00"}]


def test_amounts_survive_as_exact_decimals(db, organization):
    """The snapshot stores strings precisely so a liability never loses a cent to
    a float; summing them must stay exact."""
    run = _run(db, organization, run_code="IT-2026-10b")
    _payslip(db, organization, run, _employee(db, organization, code="IT1"), withheld="0.10")
    _payslip(db, organization, run, _employee(db, organization, code="IT2"), withheld="0.20")
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    line = _build(db, organization, run)[0]
    assert line.debit_amount == D("0.30")
    assert isinstance(line.debit_amount, D)


# ── Committed payroll only (IT-044) ────────────────────────────────────────

@pytest.mark.parametrize("status", ["Draft", "Review"])
def test_a_run_that_is_not_committed_cannot_be_paid(db, organization, status):
    """APPROVED is the committed boundary. Building from a run still in review
    would create a payment instruction against figures that may change."""
    run = _run(db, organization, status=status)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    with pytest.raises(BadRequestException) as excinfo:
        _build(db, organization, run)
    assert "APPROVED" in str(excinfo.value)
    assert db.query(ItalyF24Line).count() == 0


@pytest.mark.parametrize("status", ["Approved", "Authorized", "Paid"])
def test_a_committed_run_can_be_paid(db, organization, status):
    run = _run(db, organization, status=status)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    assert len(_build(db, organization, run)) == 1


def test_a_run_from_another_tenant_is_not_found(db, organization):
    """The run must resolve inside the caller's tenant. Cross-tenant payroll is
    the worst possible leak in a payment path, so it reads as a 404 rather than
    an authorization leak."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    other = _run(db, organization, run_code="OTHER-ORG")
    other.organization_id = organization.id + 999
    db.commit()
    with pytest.raises(NotFoundException):
        service.build_italy_f24_lines(
            db, organization.id + 999,
            ItalyF24BuildRequest(payrollRunId=run.id, referencePeriod="10/2026"))


def test_a_linked_filing_from_another_jurisdiction_is_refused(db, organization):
    """F24 lines may only attach to an Italian filing."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    sg_filing = StatutoryFiling(organization_id=organization.id, jurisdiction="SG",
                                filing_type="IR8A", period_label="2026-10")
    db.add(sg_filing)
    db.commit()
    db.refresh(sg_filing)
    with pytest.raises(BadRequestException):
        _build(db, organization, run, statutoryFilingId=sg_filing.id)


def test_an_italian_filing_can_be_linked(db, organization):
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    filing = StatutoryFiling(organization_id=organization.id, jurisdiction="IT",
                             filing_type="F24", period_label="2026-10")
    db.add(filing)
    db.commit()
    db.refresh(filing)
    assert _build(db, organization, run, statutoryFilingId=filing.id)[0].statutory_filing_id == filing.id


# ── Idempotency: a rebuild must not become a second payment (IT-044) ───────

def test_rebuilding_the_same_period_does_not_append_duplicate_lines(db, organization):
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, region="03", comune="F205"),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    first = _build(db, organization, run)
    second = _build(db, organization, run)
    assert len(first) == len(second)
    assert db.query(ItalyF24Line).count() == len(first)
    assert {line.id for line in first} == {line.id for line in second}


def test_a_rebuild_reflects_a_corrected_committed_amount_in_place(db, organization):
    """A corrected run amount updates the existing line rather than adding a
    second one beside it."""
    run = _run(db, organization)
    payslip = _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    original = _build(db, organization, run)[0]
    payslip.it_calculation_snapshot = {**payslip.it_calculation_snapshot, "irpef": {
        "withheld": "1000.00", "refund": None, "annualNet": "42000.00",
        "detrazione": "1500.00", "additionalDeduction": "0.00"}}
    db.commit()
    rebuilt = [line for line in _build(db, organization, run) if line.id == original.id]
    assert len(rebuilt) == 1
    assert rebuilt[0].debit_amount == D("1000.00")
    assert db.query(ItalyF24Line).count() == 1


# ── The catalog is effective-dated, not mutable history ────────────────────

def test_the_causale_in_force_for_the_period_is_the_one_used(db, organization):
    """F24 causali change over time, so a period must settle with the code that
    was in force THEN - not the newest one."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001",
             effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 9, 30))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="9999",
             effectiveFrom=date(2026, 10, 1))
    assert _build(db, organization, run)[0].tax_code == "9999"


def test_a_superseded_causale_does_not_pay_a_later_period(db, organization):
    """Conversely, the newer code must not retroactively rewrite a period the old
    one governed - otherwise a filed F24 no longer matches the catalog behind
    it."""
    run = _run(db, organization, run_code="IT-2026-09")
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001",
             effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 9, 30))
    assert _build(db, organization, run, period="09/2026")[0].tax_code == "1001"


def test_recording_the_same_identity_corrects_the_code(db, organization):
    """Re-submitting the same (section, component, effectiveFrom) updates in
    place, so a typo in a code can be fixed."""
    first = _causale(db, organization, "irpef.withheld", tax_code="1001")
    corrected = _causale(db, organization, "irpef.withheld", tax_code="1111")
    assert corrected.id == first.id
    assert db.query(ItalyF24Causale).count() == 1
    assert corrected.tax_code == "1111"


def test_re_recording_the_same_identity_keeps_the_original_auditor(db, organization):
    """created_by_id records who first asserted the code; a later correction
    must not make the original author look like they entered the new value."""
    original = _causale(db, organization, "irpef.withheld", tax_code="1001")
    corrected = _causale(db, organization, "irpef.withheld", tax_code="1111")
    assert corrected.created_by_id == original.created_by_id


# ── Input hygiene ──────────────────────────────────────────────────────────

def test_a_section_outside_the_f24_sections_is_refused(db, organization):
    """The section vocabulary is closed: a typo would otherwise produce a line
    no authority could interpret."""
    with pytest.raises(BadRequestException):
        _causale(db, organization, "irpef.withheld", section="HYPOTHETICAL")


def test_an_inverted_effective_range_is_refused(db, organization):
    with pytest.raises(BadRequestException):
        _causale(db, organization, "irpef.withheld", tax_code="1001",
                 effectiveFrom=date(2026, 1, 1), effectiveTo=date(2025, 12, 31))


@pytest.mark.parametrize("period", ["2026-10", "13/2026", "00/2026", "10-2026"])
def test_a_reference_period_that_is_not_a_real_mm_yyyy_is_refused(db, organization, period):
    """The period is the instruction's own reference; deriving it wrongly is how
    a December liability lands in the wrong month. A month of 13 or 00 must not
    resolve to some adjacent date."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    with pytest.raises(BadRequestException):
        _build(db, organization, run, period=period)


@pytest.mark.parametrize("period", ["10/26", "Oct/2026", "2026-10-01", ""])
def test_a_reference_period_of_the_wrong_shape_is_rejected_before_the_service(
        db, organization, period):
    """The MM/YYYY contract is enforced at the edge, so a malformed period is a
    422 naming the field rather than a downstream 400 from a date parse."""
    with pytest.raises(PydanticValidationError):
        ItalyF24BuildRequest(payrollRunId=1, referencePeriod=period)


def test_a_causale_going_into_force_mid_month_still_settles_the_month(db, organization):
    """A code that comes into force on the 15th is in force for a liability
    referenced to the whole of that month, so the period is resolved to its END.
    Testing the 15th would pick the wrong code."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001",
             effectiveFrom=date(2026, 10, 15))
    assert _build(db, organization, run)[0].tax_code == "1001"


def test_a_non_numeric_snapshot_amount_refuses_rather_than_reading_as_zero(db, organization):
    """Treating an unreadable figure as zero would quietly underpay, so the
    build stops and says what is wrong."""
    run = _run(db, organization)
    payslip = _payslip(db, organization, run, _employee(db, organization))
    payslip.it_calculation_snapshot = {**payslip.it_calculation_snapshot,
                                       "irpef": {**payslip.it_calculation_snapshot["irpef"],
                                                 "withheld": "n/a"}}
    db.commit()
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    with pytest.raises(BadRequestException) as excinfo:
        _build(db, organization, run)
    assert "not numeric" in str(excinfo.value)
    assert db.query(ItalyF24Line).count() == 0


# ── Listing stays inside the tenant ────────────────────────────────────────

def test_lines_and_causales_are_scoped_to_the_callers_tenant(db, organization):
    """organizationId on a body is never trusted, and reads are filtered to the
    authenticated tenant rather than to whatever the caller asked for."""
    other = _run(db, organization, run_code="OTHER")
    other.organization_id = organization.id + 999
    db.commit()
    _causale(db, organization, "irpef.withheld", section="ERARIO", tax_code="1001")
    assert service.list_italy_f24_causales(db, organization.id + 999) == []
    assert service.list_italy_f24_lines(db, organization.id + 999) == []


def test_lines_can_be_filtered_by_run_period_and_section(db, organization):
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, region="03", comune="F205"),
             snapshot=_FULL_SNAPSHOT)
    _govern_all(db, organization)
    _build(db, organization, run)
    all_lines = len(service.list_italy_f24_lines(db, organization.id))
    assert len(service.list_italy_f24_lines(db, organization.id, payroll_run_id=run.id)) == all_lines
    assert len(service.list_italy_f24_lines(db, organization.id, reference_period="10/2026")) == all_lines
    assert len(service.list_italy_f24_lines(db, organization.id, section="ENTI_LOCALI")) == 2
    assert service.list_italy_f24_lines(db, organization.id, section="INAIL") == []


def test_causales_can_be_filtered_to_those_in_force_on_a_date(db, organization):
    _causale(db, organization, "irpef.withheld", tax_code="1001",
             effectiveFrom=date(2026, 1, 1), effectiveTo=date(2026, 6, 30))
    assert len(service.list_italy_f24_causales(db, organization.id, as_of=date(2026, 3, 1))) == 1
    assert service.list_italy_f24_causales(db, organization.id, as_of=date(2026, 8, 1)) == []
