"""
tests/test_germany_elster.py
-----------------------------
Phase 8BF — the ELSTER transmission boundary (engine/germany_elster.py +
service.py's create/validate/transmit functions + the two new models).
No real ELSTER connector exists or is authorized anywhere in this
codebase; every test here proves the fail-closed guarantee holds
(including when a certificate reference IS configured — see
test_resolve_elster_transmitter_always_unavailable_even_when_configured)
and that the transmission-attempt audit trail behaves correctly, never
that a real filing was ever transmitted.
"""

from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.engine.germany_elster import (
    ElsterTransmissionRequest, GermanyElsterUnavailableError, resolve_elster_transmitter,
)
from app.modules.payroll.models import GermanyElsterTransmission
from app.modules.payroll.schemas import GermanyElsterTransmissionCreate


def test_certificate_config_starts_unconfigured(db, organization):
    assert service.get_elster_certificate_config(db, organization.id) is None


def test_set_certificate_config_records_reference_never_empty(db, organization):
    with pytest.raises(BadRequestException):
        service.set_elster_certificate_config(db, organization.id, "", None, actor_id=1)

    row = service.set_elster_certificate_config(
        db, organization.id, "vault://de-org-1/elster-cert", "Employer's own ELSTER org certificate", actor_id=1,
    )
    assert row.is_configured is True
    assert row.certificate_reference == "vault://de-org-1/elster-cert"
    assert row.configured_by_id == 1

    fetched = service.get_elster_certificate_config(db, organization.id)
    assert fetched.id == row.id


def test_resolve_elster_transmitter_always_unavailable_even_when_configured(db, organization):
    # The single most important guarantee this boundary makes: configuring
    # a certificate REFERENCE must never, by itself, make the resolver
    # return anything other than the fail-closed transmitter — there is no
    # real ELSTER client in this codebase at all.
    cert_config = service.set_elster_certificate_config(
        db, organization.id, "vault://de-org-1/elster-cert", None, actor_id=1,
    )
    transmitter = resolve_elster_transmitter(cert_config)
    request = ElsterTransmissionRequest(
        organization_id=organization.id, transmission_type="LOHNSTEUER_ANMELDUNG",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    with pytest.raises(GermanyElsterUnavailableError):
        transmitter.transmit(request)


def test_create_transmission_rejects_invalid_period(db, organization):
    with pytest.raises(BadRequestException):
        service.create_elster_transmission(
            db, organization.id,
            GermanyElsterTransmissionCreate(
                transmission_type="LOHNSTEUER_ANMELDUNG",
                period_start=date(2026, 2, 1), period_end=date(2026, 1, 1),
            ),
            actor_id=1,
        )
    assert db.query(GermanyElsterTransmission).count() == 0


def test_validate_transmission_moves_draft_to_validated(db, organization):
    row = service.create_elster_transmission(
        db, organization.id,
        GermanyElsterTransmissionCreate(
            transmission_type="LOHNSTEUER_ANMELDUNG",
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        ),
        actor_id=1,
    )
    assert row.status == "DRAFT"

    validated = service.validate_elster_transmission(db, row.id, organization.id, actor_id=1)
    assert validated.status == "VALIDATED"
    assert validated.validation_errors is None


def test_validate_transmission_rejects_empty_type(db, organization):
    row = service.create_elster_transmission(
        db, organization.id,
        GermanyElsterTransmissionCreate(
            transmission_type="X", period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        ),
        actor_id=1,
    )
    # Mutate the persisted row directly to simulate an empty type slipping
    # through (the Create schema itself requires a non-empty str, so this
    # exercises validate_elster_transmission's own defense-in-depth check).
    row.transmission_type = "   "
    db.commit()

    validated = service.validate_elster_transmission(db, row.id, organization.id, actor_id=1)
    assert validated.status == "REJECTED"
    assert validated.validation_errors


def test_transmit_requires_validated_status(db, organization):
    row = service.create_elster_transmission(
        db, organization.id,
        GermanyElsterTransmissionCreate(
            transmission_type="LOHNSTEUER_ANMELDUNG",
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        ),
        actor_id=1,
    )
    with pytest.raises(BadRequestException):
        service.attempt_transmit_elster_transmission(db, row.id, organization.id, actor_id=1)


def test_transmit_always_blocked_external_and_is_retryable(db, organization):
    row = service.create_elster_transmission(
        db, organization.id,
        GermanyElsterTransmissionCreate(
            transmission_type="LOHNSTEUER_ANMELDUNG",
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        ),
        actor_id=1,
    )
    service.validate_elster_transmission(db, row.id, organization.id, actor_id=1)

    attempted = service.attempt_transmit_elster_transmission(db, row.id, organization.id, actor_id=1)
    assert attempted.status == "BLOCKED_EXTERNAL"
    assert attempted.blocked_reason
    assert "ELSTER" in attempted.blocked_reason

    # Retrying an already-BLOCKED_EXTERNAL transmission must be allowed
    # (this is the expected, only-possible outcome today, not a terminal
    # caller error) and must land on the identical outcome again.
    retried = service.attempt_transmit_elster_transmission(db, row.id, organization.id, actor_id=1)
    assert retried.status == "BLOCKED_EXTERNAL"
    assert retried.blocked_reason == attempted.blocked_reason


def test_transmissions_are_tenant_scoped(db, organization):
    from app.modules.organizations.models import Organization

    other_org = Organization(organization_name="Other Org", organization_code="ELSTEROTHER")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    service.create_elster_transmission(
        db, organization.id,
        GermanyElsterTransmissionCreate(
            transmission_type="LOHNSTEUER_ANMELDUNG",
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        ),
        actor_id=1,
    )
    assert service.list_elster_transmissions(db, organization.id) != []
    assert service.list_elster_transmissions(db, other_org.id) == []
