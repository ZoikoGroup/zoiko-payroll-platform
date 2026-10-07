"""Ireland RPN snapshot ingestion and the Italy filing outbox (IT-044/IT-048).

Both surfaces exist so that authority DOCUMENTS and delivery INTENT are
recorded outside the calculator: the engine reads a frozen Revenue Payroll
Notification instead of calling Revenue (IE-022), and an Italian filing is
queued from committed payroll rather than transmitted from inside a
calculation that must not fail because a government endpoint is down.

The behaviour under test is therefore mostly about refusal and idempotency:
a snapshot may only be attached to an Irish employee, re-posting the identical
authority response must not duplicate history, and an outbox row may only be
queued once per (action, filing, period) - with UNKNOWN resolving through
reconciliation rather than a blind replay.

SQLite `db` fixture only - nothing here reaches a real database.
"""
from decimal import Decimal as D

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import (
    IrelandRpnSnapshot, ItalyFilingOutboxItem, PayrollEmployee, StatutoryFiling,
)
from app.modules.payroll.schemas import (
    IrelandRpnSnapshotUpsert, ItalyFilingOutboxCreate,
)


def _employee(db, organization, code, country):
    employee = PayrollEmployee(organization_id=organization.id, employee_code=code,
                               name=f"Worker {code}", country_code=country)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _rpn(**kw):
    defaults = dict(employeeId=1, rpnNumber="RPN-2026-0001", issuedAt="2026-01-05T09:00:00",
                    taxYear="2026", calculationBasis="CUMULATIVE", ppsnSupplied=True,
                    standardRateBand=D("34000"), taxCredit=D("3300"),
                    standardRateBandPeriod=D("2833.33"), taxCreditPeriod=D("275"),
                    previousTaxablePayYtd=D("0"), previousPayYtd=D("0"), periodsElapsed=1,
                    lptInstructed=False, rawHash="a" * 64)
    defaults.update(kw)
    return IrelandRpnSnapshotUpsert(**defaults)


# ── Ireland: frozen RPN snapshots (IE-005/IE-022/IE-033/IE-045) ───────────

def test_rpn_snapshot_requires_an_ireland_employee(db, organization):
    """IE-022's whole point is that the Irish calculation reads an Irish
    document. Attaching one to a Singaporean employee would be a silent data
    error, so it is refused rather than stored."""
    sg = _employee(db, organization, "SG1", "SG")
    with pytest.raises(BadRequestException):
        service.record_ie_rpn_snapshot(db, organization.id, _rpn(employeeId=sg.id))
    assert db.query(IrelandRpnSnapshot).count() == 0


def test_rpn_snapshot_is_content_addressed_so_reposting_does_not_duplicate(
        db, organization):
    """The same authority response (same raw_hash) is the same fact. A second
    ingest returns the existing row, so history cannot be forked by a retry."""
    ie = _employee(db, organization, "IE1", "IE")
    first = service.record_ie_rpn_snapshot(db, organization.id, _rpn(employeeId=ie.id))
    again = service.record_ie_rpn_snapshot(db, organization.id, _rpn(employeeId=ie.id))
    assert again.id == first.id
    assert db.query(IrelandRpnSnapshot).count() == 1


def test_a_genuine_reissue_adds_an_immutable_row_rather_than_overwriting(
        db, organization):
    """IE-045: a historical payroll must stay reproducible from the snapshot
    that was in force, so a changed authority response is a NEW row."""
    ie = _employee(db, organization, "IE1", "IE")
    first = service.record_ie_rpn_snapshot(db, organization.id, _rpn(employeeId=ie.id))
    second = service.record_ie_rpn_snapshot(
        db, organization.id,
        _rpn(employeeId=ie.id, rawHash="b" * 64, issuedAt="2026-02-05T09:00:00",
             standardRateBand=D("38000")))
    rows = db.query(IrelandRpnSnapshot).all()
    assert {r.id for r in rows} == {first.id, second.id}
    assert first.standard_rate_band == D("34000")


def test_rpn_body_cannot_name_another_organization(db, organization):
    """organizationId on the body is never trusted: tenancy comes from the
    authenticated caller, and the employee must resolve inside it."""
    ie = _employee(db, organization, "IE1", "IE")
    row = service.record_ie_rpn_snapshot(db, organization.id, _rpn(employeeId=ie.id))
    assert row.organization_id == organization.id

    other = _employee(db, organization, "IE2", "IE")
    stranger = _rpn(employeeId=other.id, organizationId=999)
    stored = service.record_ie_rpn_snapshot(db, organization.id, stranger)
    assert stored.organization_id == organization.id


def test_listing_rpn_snapshots_is_tenant_scoped_and_newest_first(
        db, organization, ):
    from app.modules.organizations.models import Organization

    other_org = Organization(organization_name="Other", organization_code="OTHERORG")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    ie = _employee(db, organization, "IE1", "IE")
    outsider = _employee(db, other_org, "IE9", "IE")
    old = service.record_ie_rpn_snapshot(
        db, organization.id, _rpn(employeeId=ie.id, rawHash="c" * 64,
                                  issuedAt="2026-01-05T09:00:00"))
    new = service.record_ie_rpn_snapshot(
        db, organization.id, _rpn(employeeId=ie.id, rawHash="d" * 64,
                                  issuedAt="2026-06-05T09:00:00"))
    service.record_ie_rpn_snapshot(db, other_org.id, _rpn(employeeId=outsider.id))

    rows = service.list_ie_rpn_snapshots(db, organization.id)
    assert [r.id for r in rows] == [new.id, old.id]

    assert [r.id for r in service.list_ie_rpn_snapshots(db, organization.id, ie.id)] == [new.id, old.id]
    assert service.list_ie_rpn_snapshots(db, organization.id, tax_year="2025") == []
    assert [r.id for r in service.list_ie_rpn_snapshots(db, organization.id, tax_year="2026")] == [new.id, old.id]


# ── Italy filing outbox (IT-044/IT-048) ───────────────────────────────────

def _filing(db, organization, jurisdiction="IT", filing_type="UNIEMENS"):
    filing = StatutoryFiling(organization_id=organization.id, jurisdiction=jurisdiction,
                             filing_type=filing_type, period_label="2026-01")
    db.add(filing)
    db.commit()
    db.refresh(filing)
    return filing


def test_outbox_rejects_an_action_that_is_not_an_italian_filing(db, organization):
    """The action vocabulary is closed: a typo must not become a queue row
    nothing will ever drain."""
    with pytest.raises(BadRequestException):
        service.create_italy_filing_outbox_item(
            db, organization.id, ItalyFilingOutboxCreate(action="SEND_SOMETHING"))
    assert db.query(ItalyFilingOutboxItem).count() == 0


def test_enqueueing_the_same_filing_action_twice_is_one_row(db, organization):
    """IT-044's idempotency key is the (org, action, filing, period) IDENTITY,
    not the payload - so a retry carrying a corrected payload still resolves to
    the one row instead of queueing a duplicate transmission."""
    filing = _filing(db, organization)
    first = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT", statutoryFilingId=filing.id,
                                periodKey="2026-01", payload={"gross": 100}))
    second = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT", statutoryFilingId=filing.id,
                                periodKey="2026-01", payload={"gross": 999}))
    assert second.id == first.id
    assert second.payload == {"gross": 100}
    assert db.query(ItalyFilingOutboxItem).count() == 1


def test_a_correction_queues_separately_from_the_filing_it_corrects(db, organization):
    """CORRECTION is a distinct action precisely because it must be able to
    queue alongside - not collapse into - the original transmission."""
    filing = _filing(db, organization)
    original = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT", statutoryFilingId=filing.id,
                                periodKey="2026-01"))
    correction = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="CORRECTION", statutoryFilingId=filing.id,
                                periodKey="2026-01"))
    assert correction.id != original.id
    assert db.query(ItalyFilingOutboxItem).count() == 2


def test_outbox_refuses_a_filing_owned_by_another_tenant(db, organization):
    """An outbox row pointing at another organization's filing would leak that
    organization's filing into this tenant's delivery queue."""
    from app.modules.organizations.models import Organization

    other_org = Organization(organization_name="Other", organization_code="OTHERORG")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    foreign = _filing(db, other_org)

    with pytest.raises(NotFoundException):
        service.create_italy_filing_outbox_item(
            db, organization.id,
            ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT",
                                    statutoryFilingId=foreign.id))
    assert db.query(ItalyFilingOutboxItem).count() == 0


def test_outbox_refuses_a_filing_that_is_not_italian(db, organization):
    """Linking an Italian outbox row to, say, a UK filing would let the two
    authorities' delivery states be conflated."""
    french = _filing(db, organization, jurisdiction="FR", filing_type="DSN")
    with pytest.raises(BadRequestException):
        service.create_italy_filing_outbox_item(
            db, organization.id,
            ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT",
                                    statutoryFilingId=french.id))


def test_unknown_transmission_cannot_be_marked_failed_without_reconciliation(
        db, organization):
    """IT-048: a timeout means UNKNOWN, and only proven non-receipt may become
    FAILED. Requiring the reconciliation result is what stops "no receipt" from
    being written as a failure that invites a duplicate transmission."""
    filing = _filing(db, organization)
    item = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="F24_SUBMIT", statutoryFilingId=filing.id,
                                periodKey="2026-Q1"))

    item = service.transition_italy_filing_outbox_item(
        db, organization.id, item.id, "SENT")
    item = service.transition_italy_filing_outbox_item(
        db, organization.id, item.id, "UNKNOWN")
    assert item.status == "UNKNOWN"

    with pytest.raises(BadRequestException):
        service.transition_italy_filing_outbox_item(
            db, organization.id, item.id, "FAILED")

    resolved = service.transition_italy_filing_outbox_item(
        db, organization.id, item.id, "ACKNOWLEDGED")
    assert resolved.status == "ACKNOWLEDGED"
    assert resolved.acknowledged_at is not None
    assert resolved.attempts == 1


def test_unknown_can_be_failed_once_non_receipt_is_proven(db, organization):
    filing = _filing(db, organization)
    item = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="LUL_REGISTER", statutoryFilingId=filing.id,
                                periodKey="2026-03"))
    service.transition_italy_filing_outbox_item(db, organization.id, item.id, "UNKNOWN")
    item = service.transition_italy_filing_outbox_item(
        db, organization.id, item.id, "FAILED", last_error="Agenzia confirmed no receipt")
    assert item.status == "FAILED"
    assert item.last_error == "Agenzia confirmed no receipt"


def test_transitions_that_skip_delivery_are_refused(db, organization):
    """ACKNOWLEDGED is terminal, and a fresh PENDING row cannot jump straight
    to it - that would mean a filing was acknowledged without ever being sent."""
    filing = _filing(db, organization)
    item = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="CU_TRANSMIT", statutoryFilingId=filing.id,
                                periodKey="2026-Q2"))
    with pytest.raises(BadRequestException):
        service.transition_italy_filing_outbox_item(
            db, organization.id, item.id, "ACKNOWLEDGED")
    assert item.status == "PENDING"


def test_transitioning_another_tenants_outbox_row_is_not_found(db, organization):
    from app.modules.organizations.models import Organization

    other_org = Organization(organization_name="Other", organization_code="OTHERORG")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    foreign = service.create_italy_filing_outbox_item(
        db, other_org.id, ItalyFilingOutboxCreate(action="770_TRANSMIT"))

    with pytest.raises(NotFoundException):
        service.transition_italy_filing_outbox_item(
            db, organization.id, foreign.id, "SENT")


def test_an_unrecognised_transport_status_is_refused_before_anything_is_read(
        db, organization):
    """The status vocabulary is checked first, so a typo can never be recorded
    as a delivery attempt against whatever row the id happens to resolve to."""
    with pytest.raises(BadRequestException):
        service.transition_italy_filing_outbox_item(
            db, organization.id, 999999, "NOT_A_STATUS")


def test_listing_outbox_items_is_tenant_scoped_and_filterable(db, organization):
    from app.modules.organizations.models import Organization

    other_org = Organization(organization_name="Other", organization_code="OTHERORG")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    filing = _filing(db, organization)
    uniemens = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT", statutoryFilingId=filing.id,
                                periodKey="2026-01"))
    f24 = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="F24_SUBMIT", statutoryFilingId=filing.id,
                                periodKey="2026-01"))
    foreign = service.create_italy_filing_outbox_item(
        db, other_org.id, ItalyFilingOutboxCreate(action="770_TRANSMIT"))

    rows = service.list_italy_filing_outbox_items(db, organization.id)
    assert {r.id for r in rows} == {uniemens.id, f24.id}
    assert all(r.organization_id == organization.id for r in rows)

    assert [r.id for r in service.list_italy_filing_outbox_items(
        db, organization.id, action="F24_SUBMIT")] == [f24.id]
    assert {r.id for r in service.list_italy_filing_outbox_items(
        db, organization.id, statutory_filing_id=filing.id)} == {uniemens.id, f24.id}
    # The other tenant's row is reachable only from its own organization.
    assert [r.id for r in service.list_italy_filing_outbox_items(
        db, other_org.id)] == [foreign.id]


def test_failed_may_be_resent_and_counts_the_attempt(db, organization):
    """A DEFINITE failure is the one case a resend is allowed, and each send
    is counted rather than overwriting the prior attempt."""
    filing = _filing(db, organization)
    item = service.create_italy_filing_outbox_item(
        db, organization.id,
        ItalyFilingOutboxCreate(action="UNIEMENS_TRANSMIT", statutoryFilingId=filing.id,
                                periodKey="2026-04"))
    item = service.transition_italy_filing_outbox_item(
        db, organization.id, item.id, "FAILED", last_error="endpoint refused")
    item = service.transition_italy_filing_outbox_item(
        db, organization.id, item.id, "SENT")
    assert item.status == "SENT"
    assert item.attempts == 1
    assert item.sent_at is not None
