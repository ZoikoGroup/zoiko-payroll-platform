"""
tests/test_netherlands_security.py
----------------------------------
ZP-NL-ENG-001 §19 T8 (security / recovery), NL-051/NL-052 and the gate /
go-live controls of §19:

  * no duplicate salary batch, authority batch or jaaropgaaf from a repeated
    request (a retry returns the same record);
  * Digipoort is never resent blindly — an in-flight or accepted submission
    refuses a new send, and a retry after reconciliation only resends a
    submission that was definitively REJECTED;
  * BSN, IBAN and certificate material never reach application logs across a
    whole run -> approval -> return -> submission -> jaaropgaaf -> SEPA flow,
    and the API masks them;
  * an expired PKIoverheid certificate blocks readiness;
  * gate G1–G8 states come only from independently reviewed evidence;
  * the Netherlands stays out of public registration until G1–G8 are signed.

In-memory SQLite, SYNTHETIC wage-tax rows (see the payment test fixture).
"""

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from datetime import date as _date

EXECUTION_TODAY = _date(2026, 1, 1)          # before the fixture pay dates

from app.modules.payroll import netherlands_annual_service as annual
from app.modules.payroll import netherlands_digipoort as digi
from app.modules.payroll import netherlands_filing_service as filings
from app.modules.payroll import netherlands_payment_service as pay
from app.modules.payroll import netherlands_service as nl
from app.modules.payroll.models import (
    PayrollNlDigipoortSubmission, PayrollNlEmployerProfile, PayrollNlPaymentBatch, SourceArtifact,
)
from tests.test_hong_kong_governance import _http
from tests.test_netherlands_payment import _run_and_approve, nlx  # noqa: F401

BSN = "111222333"
EMPLOYEE_IBAN = "NL44RABO0123456789"
EMPLOYER_IBAN = "NL91ABNA0417164300"
CERT_FINGERPRINT = "AB:CD:EF:01:23:45:67:89:SECRET-CERT-FP"


def _employer(db, nlx):
    return db.query(PayrollNlEmployerProfile).filter_by(organization_id=nlx.org.id).one()


def _reconciled_return(db, nlx, month=3):
    _run_and_approve(db, nlx, month)
    ret = filings.build_loonaangifte_return(db, organization_id=nlx.org.id, employer_profile_id=_employer(db, nlx).id,
                                            tax_year=2026, period_code=f"2026{month:02d}", return_type="REGULAR",
                                            actor_id=801)
    filings.reconcile_return(db, ret.id, 801)
    return ret


# ── duplicate filing / payment (T8) ──────────────────────────────────────────

class TestNoDuplicates:
    def test_salary_batch_retry_returns_the_same_batch(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        # The fixture's 2026 pay dates are in the past; execution dates may not be (Phase 4.2).
        first = pay.create_salary_payment_batch(db, run.id, 801, today=EXECUTION_TODAY)
        db.commit()
        again = pay.create_salary_payment_batch(db, run.id, 802, today=EXECUTION_TODAY)   # another operator, later
        db.commit()
        assert again.id == first.id
        assert db.query(PayrollNlPaymentBatch).filter_by(payroll_run_id=run.id).count() == 1

    def test_salary_batch_retry_over_http(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        principal = SimpleNamespace(id=801, organization_id=nlx.org.id, role="org_admin", is_active=True)
        with _http(db, principal) as c:
            body = {"requested_execution_date": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()}
            a = c.post(f"/api/payroll/netherlands/runs/{run.id}/salary-batch", json=body)
            b = c.post(f"/api/payroll/netherlands/runs/{run.id}/salary-batch", json=body)
        assert a.status_code == 200, a.text
        assert a.json()["id"] == b.json()["id"]

    def test_authority_batch_retry_returns_the_same_batch(self, db, nlx):
        payments = [{"creditor_name": "Belastingdienst", "creditor_iban": "NL03RABO0000000001",
                     "amount": "1325.08", "payment_reference": "LOONHEFFING-202603", "creditor_bic": "RABONL2U"}]
        first = pay.create_authority_payment_batch(db, nlx.org.id, payments, 801)
        db.commit()
        again = pay.create_authority_payment_batch(db, nlx.org.id, list(payments), 802)
        assert again.id == first.id

    def test_jaaropgaaf_generate_twice_is_one_statement(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        first = annual.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        db.commit()
        again = annual.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=802)
        assert again.id == first.id


# ── restore / outbox: never blind-replay Digipoort (NL-052) ──────────────────

class TestNoBlindResend:
    def test_second_send_of_an_acknowledged_return_is_refused(self, db, nlx):
        ret = _reconciled_return(db, nlx)
        assert digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE).transport_status == "ACK"
        with pytest.raises(digi.DigipoortError, match="never resent blindly"):
            digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)

    def _unknown(self, db, ret, ref):
        sub = PayrollNlDigipoortSubmission(return_id=ret.id, attempt_no=1, channel="DIGIPOORT", cert_fingerprint="fp",
                                           payload_sha256="sha", transport_status="UNKNOWN", digipoort_reference=ref,
                                           sent_at=datetime.utcnow() - timedelta(hours=1), idempotency_key=f"k-{ref}")
        db.add(sub)
        db.flush()
        return sub

    def test_unknown_that_reconciles_to_ack_is_not_resent(self, db, nlx):
        ret = _reconciled_return(db, nlx)
        sub = self._unknown(db, ret, "R-ACK")
        transport = MagicMock()
        transport.poll_acknowledgement.return_value = digi.TransportResult(
            success=True, transport_status=digi.TransportStatus.ACK, digipoort_reference="R-ACK", ack_payload="<Ack/>")
        with patch.object(digi, "get_transport", return_value=transport):
            with pytest.raises(digi.DigipoortError, match="reconciled as ACK"):
                digi.retry_submission(db, sub.id)
        transport.send.assert_not_called()
        assert db.query(PayrollNlDigipoortSubmission).filter_by(return_id=ret.id).count() == 1

    def test_unknown_that_stays_unknown_is_not_resent(self, db, nlx):
        ret = _reconciled_return(db, nlx)
        sub = self._unknown(db, ret, "R-UNK")
        transport = MagicMock()
        transport.poll_acknowledgement.return_value = digi.TransportResult(
            success=True, transport_status=digi.TransportStatus.SENT, digipoort_reference="R-UNK")
        with patch.object(digi, "get_transport", return_value=transport):
            with pytest.raises(digi.DigipoortError, match="reconciled as UNKNOWN"):
                digi.retry_submission(db, sub.id)
        transport.send.assert_not_called()

    def test_send_is_refused_while_an_attempt_is_unknown(self, db, nlx):
        ret = _reconciled_return(db, nlx)
        self._unknown(db, ret, "R-OPEN")
        with pytest.raises(digi.DigipoortError, match="status UNKNOWN"):
            digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)

    def test_a_crash_during_send_is_unknown_and_blocks_a_resend(self, db, nlx):
        """An exception while sending does not prove the return never arrived."""
        ret = _reconciled_return(db, nlx)
        transport = MagicMock()
        transport.send.side_effect = ConnectionError("connection reset by peer")
        with patch.object(digi, "get_transport", return_value=transport):
            with pytest.raises(ConnectionError):
                digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)
        sub = db.query(PayrollNlDigipoortSubmission).filter_by(return_id=ret.id).one()
        assert sub.transport_status == "UNKNOWN"
        assert sub.error_codes[0]["code"] == "TRANSPORT_ERROR"
        with pytest.raises(digi.DigipoortError, match="status UNKNOWN"):
            digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)


# ── NL-051: no BSN / IBAN / certificate material in logs ─────────────────────

class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.texts = []

    def emit(self, record):
        text = record.getMessage()
        if record.exc_info:
            text += logging.Formatter().formatException(record.exc_info)
        self.texts.append(f"{record.name}: {text}")


def test_no_identity_or_bank_or_certificate_material_in_logs(db, nlx):
    profile = _employer(db, nlx)
    profile.pki_cert_fingerprint = CERT_FINGERPRINT
    db.commit()
    root = logging.getLogger()
    handler, old_level = _Collect(), root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        run = _run_and_approve(db, nlx, 3)
        ret = filings.build_loonaangifte_return(db, organization_id=nlx.org.id, employer_profile_id=profile.id,
                                                tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)
        digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)
        annual.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        batch = pay.create_salary_payment_batch(db, run.id, 801, today=EXECUTION_TODAY)
        db.commit()
        principal = SimpleNamespace(id=801, organization_id=nlx.org.id, role="org_admin", is_active=True)
        with _http(db, principal) as c:
            record = c.get(f"/api/payroll/netherlands/employees/{nlx.emp.id}")
            batch_view = c.get(f"/api/payroll/netherlands/payment-batches/{batch.id}")
            employee = c.get(f"/api/payroll/employees/{nlx.emp.id}")
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)

    assert handler.texts, "the flow must actually log something, or this check proves nothing"
    logged = "\n".join(handler.texts)
    for secret in (BSN, EMPLOYEE_IBAN, EMPLOYER_IBAN, CERT_FINGERPRINT):
        assert secret not in logged, f"{secret[:4]}... appeared in application logs"
    # ... and the API never returns them in plaintext either.
    assert BSN not in record.text and BSN not in employee.text, "BSN must be masked in API responses"
    assert batch_view.status_code == 200 and EMPLOYEE_IBAN not in batch_view.text


# ── certificate expiry blocks readiness (T8) ─────────────────────────────────

@pytest.mark.parametrize("delta_days, status", [(-1, "BLOCKED"), (90, "COMPLETE")])
def test_expired_pki_certificate_blocks_readiness(db, nlx, delta_days, status):
    profile = _employer(db, nlx)
    profile.pki_cert_expires_at = datetime.now(timezone.utc) + timedelta(days=delta_days)
    db.commit()
    card = nl.get_employer_readiness_card(db, organization_id=nlx.org.id)
    items = {i.key: i for s in card.sections for i in s.items}
    assert items["pki_cert_expiry"].status == status


# ── gates G1–G8 come only from independently reviewed evidence ──────────────

def _evidence(db, tag, created_by, reviewer=None, file_path="evidence/g1.pdf"):
    row = SourceArtifact(agency="Belastingdienst", title=f"{tag} evidence", form_number=tag,
                         created_by_id=created_by, reviewer_id=reviewer, file_path=file_path)
    db.add(row)
    db.flush()
    return row


def test_gate_states_need_independent_review(db, nlx):
    states = {g["gate"]: g["state"] for g in nl.gate_states(db)}
    assert set(states) == {f"G{i}" for i in range(1, 9)} and set(states.values()) == {"OPEN"}

    _evidence(db, "NL-GATE-G1", created_by=801)                              # submitted, not reviewed
    _evidence(db, "NL-GATE-G2", created_by=801, reviewer=801)                # self-review is not a review
    _evidence(db, "NL-GATE-G3", created_by=801, reviewer=802, file_path=None)  # no document, no signature
    _evidence(db, "NL-GATE-G4", created_by=801, reviewer=802)                # independent review + document
    states = {g["gate"]: g["state"] for g in nl.gate_states(db)}
    assert states["G1"] == states["G2"] == states["G3"] == "SUBMITTED"
    assert states["G4"] == "SIGNED"
    assert states["G5"] == "OPEN"


# ── go-live guard ────────────────────────────────────────────────────────────

def test_netherlands_is_not_open_for_registration():
    from app.core.jurisdiction import JURISDICTION_TAX_SCHEMAS, REGISTRATION_COUNTRIES

    assert "Netherlands" in REGISTRATION_COUNTRIES and "NL" not in REGISTRATION_COUNTRIES  # owner decision 2026-10-29
    assert "NL" in JURISDICTION_TAX_SCHEMAS            # schema only — the gate decides go-live
