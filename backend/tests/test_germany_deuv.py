"""tests/test_germany_deuv.py
----------------------------
Phase 8BR — tests for the DEÜV social insurance notification boundary
(`engine/germany_deuv.py`).

Verifies:
1. Specification-independent request contract validation
2. Recognized message types (§28a SGB IV: ANMELDUNG, ABMELDUNG, JAHRESMELDUNG, etc.)
3. Date period boundary validation
4. Deterministic fail-closed behavior of resolve_deuv_transmitter()
5. Actionable diagnostic messaging citing GKV-Spitzenverband and SPECIFICATION_REQUIRED
6. Zero fabrication of transmission references or transmission tickets
"""

from datetime import date
import pytest

from app.modules.payroll.engine.germany_deuv import (
    DEUV_MESSAGE_TYPES,
    DeuvTransmissionRequest,
    GermanyDeuvUnavailableError,
    UnavailableDeuvTransmitter,
    resolve_deuv_transmitter,
)


def test_deuv_message_types_contain_core_statutory_categories():
    """Verify standard §28a SGB IV notification categories are represented."""
    assert "ANMELDUNG" in DEUV_MESSAGE_TYPES
    assert "ABMELDUNG" in DEUV_MESSAGE_TYPES
    assert "JAHRESMELDUNG" in DEUV_MESSAGE_TYPES
    assert "UNTERBRECHUNG" in DEUV_MESSAGE_TYPES
    assert "STORNIERUNG" in DEUV_MESSAGE_TYPES


def test_deuv_request_validation_succeeds_for_well_formed_request():
    """Verify request bounds pass validation when structural inputs are correct."""
    req = DeuvTransmissionRequest(
        organization_id=1,
        message_type="ANMELDUNG",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        employee_id=101,
        betriebsnummer_employer="12345678",
        versicherungsnummer_employee="12345678A123",
    )
    req.validate_request_bounds()


def test_deuv_request_validation_fails_on_missing_org():
    """Verify request validation enforces tenant boundary."""
    req = DeuvTransmissionRequest(
        organization_id=0,
        message_type="ANMELDUNG",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    with pytest.raises(GermanyDeuvUnavailableError) as exc_info:
        req.validate_request_bounds()
    assert "organization_id must be provided" in str(exc_info.value)


def test_deuv_request_validation_fails_on_unrecognized_message_type():
    """Verify request rejects invented/unsupported message types."""
    req = DeuvTransmissionRequest(
        organization_id=1,
        message_type="INVALID_MELDUNG_TYPE",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    with pytest.raises(GermanyDeuvUnavailableError) as exc_info:
        req.validate_request_bounds()
    assert "Unknown DEÜV message type" in str(exc_info.value)


def test_deuv_request_validation_fails_on_inverted_dates():
    """Verify request rejects date boundaries where period_end precedes period_start."""
    req = DeuvTransmissionRequest(
        organization_id=1,
        message_type="JAHRESMELDUNG",
        period_start=date(2026, 12, 31),
        period_end=date(2026, 1, 1),
    )
    with pytest.raises(GermanyDeuvUnavailableError) as exc_info:
        req.validate_request_bounds()
    assert "period_end cannot precede period_start" in str(exc_info.value)


def test_resolve_deuv_transmitter_returns_unavailable_transmitter():
    """Verify resolver always returns UnavailableDeuvTransmitter."""
    transmitter = resolve_deuv_transmitter()
    assert isinstance(transmitter, UnavailableDeuvTransmitter)


def test_unavailable_transmitter_fails_closed_with_specification_required():
    """Verify transmit call raises GermanyDeuvUnavailableError with SPECIFICATION_REQUIRED."""
    transmitter = resolve_deuv_transmitter()
    req = DeuvTransmissionRequest(
        organization_id=1,
        message_type="ABMELDUNG",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )
    with pytest.raises(GermanyDeuvUnavailableError) as exc_info:
        transmitter.transmit(req)
    assert "SPECIFICATION_REQUIRED" in str(exc_info.value)
    assert "GKV-Spitzenverband" in str(exc_info.value)
    assert exc_info.value.code == "GERMANY_DEUV_UNAVAILABLE"
