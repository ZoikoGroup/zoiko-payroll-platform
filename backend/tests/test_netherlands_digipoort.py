"""
tests/test_netherlands_digipoort.py
------------------------------------
Digipoort transport adapter tests (Phase 9).

Covers:
  - Validation service (sandbox) synchronous ACK
  - Sandbox transport with PKI cert
  - Live transport locked until G3
  - Timeout -> UNKNOWN, reconciliation before retry (NL-052)
  - Transport/statutory acceptance/payment as three separate states (NL-038)
"""
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.modules.payroll import netherlands_digipoort as digi
from app.modules.payroll import netherlands_filing_service as filings
from app.modules.payroll.models import (
    PayrollNlAuthorityPayment,
    PayrollNlDigipoortSubmission,
    PayrollNlEmployerProfile,
    PayrollNlLoonaangifteReturn,
    PayrollRun,
)
from app.core.exceptions import BadRequestException


class TestValidationServiceTransport:
    def test_send_valid_xml_returns_ack(self):
        transport = digi.ValidationServiceTransport()
        xml = '<?xml version="1.0"?><Loonaangifte><Header/><Totals/><Regels/></Loonaangifte>'
        result = transport.send(xml, "test-cert-fp", "idempotency-123")
        assert result.success is True
        assert result.transport_status == digi.TransportStatus.ACK
        assert result.digipoort_reference is not None
        assert "VALID" in result.ack_payload

    def test_send_invalid_xml_rejected(self):
        transport = digi.ValidationServiceTransport()
        xml = 'not valid xml'
        result = transport.send(xml, "test-cert-fp", "idempotency-123")
        assert result.success is False
        assert result.transport_status == digi.TransportStatus.REJECTED
        assert result.error_codes is not None
        assert any(e["code"] == "SCHEMA_INVALID" for e in result.error_codes)

    def test_poll_ack_synchronous(self):
        transport = digi.ValidationServiceTransport()
        result = transport.poll_acknowledgement("VAL-abc123")
        assert result.success is True
        assert result.transport_status == digi.TransportStatus.ACK

    def test_health_check(self):
        transport = digi.ValidationServiceTransport()
        assert transport.health_check() is True


class TestSandboxTransport:
    def test_disabled_by_default(self):
        transport = digi.SandboxTransport()
        result = transport.send("<xml/>", "fp", "idem")
        assert result.success is False
        assert "not enabled" in result.error_message

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("NL_DIGIPOORT_SANDBOX_ENABLED", "true")
        transport = digi.SandboxTransport()
        result = transport.send("<xml/>", "fp", "idem")
        assert result.success is True
        assert result.transport_status == digi.TransportStatus.SENT


class TestLiveTransport:
    def test_locked_by_default(self):
        transport = digi.LiveTransport()
        assert transport.enabled is False
        with pytest.raises(digi.LiveTransportLockedError):
            transport.send("<xml/>", "fp", "idem")

    def test_unlock_requires_cert_and_evidence(self):
        transport = digi.LiveTransport()
        with pytest.raises(digi.CertificateError):
            transport.unlock("/nonexistent/cert.pfx", "password", 1)

    def test_unlock_enables(self, tmp_path, monkeypatch):
        cert = tmp_path / "test.pfx"
        cert.write_bytes(b"dummy")
        transport = digi.LiveTransport()
        transport.unlock(str(cert), "password", 123)
        assert transport.enabled is True
        assert transport.cert_path == str(cert)
        assert transport.test_evidence_id == 123


# Helper fixtures
def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _pack(db):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from app.modules.payroll.engine.countries.netherlands_content import (
        NL_CAR_ADDITION_BANDS, NL_MIN_WAGE_RATES, NL_PERIOD_MAXIMA, NL_SCALAR_CONTENT, NL_WKR_BANDS,
    )
    from decimal import Decimal as D

    pack = JurisdictionPack(pack_id="NL-PAYROLL-TEST", jurisdiction_country="NL", version="1.0", pack_type="tax",
                            status="Active", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(pack)
    db.flush()
    for key, label, ee, er, flat, text, _src, _g1 in NL_SCALAR_CONTENT:
        db.add(ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="NL", organization_id=None,
                                component_key=key, label=label[:100], employee_share="-", employer_share="-", total="-",
                                employee_rate_pct=D(ee) if ee else None, employer_rate_pct=D(er) if er else None,
                                flat_amount=D(flat) if flat else None, text_value=text))
    order = 0

    def slab(rule, key, *, rate="0", lo="0", hi=None, amount=None, eff_from=None, eff_to=None):
        nonlocal order
        order += 1
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="NL", organization_id=None, rule_type=rule,
                       filing_status=key, min_amount=D(lo), max_amount=D(hi) if hi else None, rate_pct=D(rate),
                       flat_amount=D(amount) if amount else None, rate_label=f"TEST {rule} {key}", tax_formula="-",
                       effective_from=eff_from, effective_to=eff_to, sort_order=order))

    for cohort, amount, eff_from, eff_to, _s, _g in NL_MIN_WAGE_RATES:
        slab("NL_MIN_WAGE", cohort, amount=amount, eff_from=eff_from, eff_to=eff_to)
    for code, amount, _s, _g in NL_PERIOD_MAXIMA:
        slab("NL_PERIOD_MAX", code, amount=amount)
    for kind, lo, hi, rate, _s, _g in NL_WKR_BANDS:
        slab("NL_WKR_BAND", kind, lo=lo, hi=hi, rate=rate)
    for car_class, rate, eff_from, eff_to, _s, _g in NL_CAR_ADDITION_BANDS:
        slab("NL_CAR_ADDITION", car_class, rate=rate, eff_from=eff_from, eff_to=eff_to)
    db.flush()
    return pack


def _table(db, pack):
    from app.modules.payroll.models import PayrollNlTaxTableFile, PayrollNlTaxTableRow
    from decimal import Decimal as D

    f = PayrollNlTaxTableFile(jurisdiction_pack_id=pack.id, tax_year=2026, table_color="WHITE", table_kind="PERIOD",
                              period="MONTH", residence_variant="NL", source_filename="SYNTHETIC.csv",
                              file_sha256="c" * 64, row_count=3, status="ACTIVE", effective_from=date(2026, 1, 1))
    db.add(f)
    db.flush()
    for n, (lo, hi, credit, amount) in enumerate([("0", "5000", True, "1000.00"), ("5000", None, True, "1325.08"),
                                                  ("0", None, False, "1900.00")], start=1):
        db.add(PayrollNlTaxTableRow(file_id=f.id, row_no=n, wage_from=D(lo), wage_to=D(hi) if hi else None,
                                    aow_cohort="BELOW_AOW", with_tax_credit=credit, withholding_amount=D(amount),
                                    row_sha256=f"{n:064d}"))
    db.flush()
    return f


@pytest.fixture()
def nlx(db, organization, monkeypatch):
    from app.modules.payroll import netherlands_service as nl
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollNlEmployerProfile, PayrollEmployee, EmployeeStatutoryProfile, PayrollNlTaxCreditInstruction, PayrollNlContractVersion
    from datetime import date
    from decimal import Decimal as D

    _stub_codes(monkeypatch)
    org = organization
    pack = _pack(db)
    table = _table(db, pack)
    db.add(CompanyComplianceDetails(organization_id=org.id, jurisdiction_country="Netherlands", active_pack_id=pack.id))
    db.add(PayrollNlEmployerProfile(organization_id=org.id, effective_from=date(2026, 1, 1), legal_name="TEST BV",
                                    loonheffingennummer="123456789L01", registration_verified_at=date(2026, 1, 2),
                                    cao_status="NONE"))
    emp = PayrollEmployee(organization_id=org.id, employee_code="NL-001", name="Test Werknemer", country_code="NL",
                          ctc=D("60000"), basic=D("60000"), hra=D("0"), date_of_birth=date(1990, 5, 15),
                          date_of_joining=date(2025, 1, 1), pay_frequency="Monthly",
                          compliance_fields={"bsn": "111222333"})
    db.add(emp)
    db.flush()
    db.add(EmployeeStatutoryProfile(employee_id=emp.id, organization_id=org.id, country_code="NL",
                                    effective_from=date(2026, 1, 1), nl_table_color="WHITE", nl_residence_variant="NL",
                                    nl_zvw_path="EMPLOYER_LEVY", nl_ei_insured=True, nl_cross_border_status="NONE",
                                    nl_contract_hours_per_week=D("40"), nl_bsn_verified_at=date(2026, 1, 2)))
    db.add(PayrollNlTaxCreditInstruction(organization_id=org.id, employee_id=emp.id, apply_tax_credit=True,
                                         signed_at=date(2025, 12, 20), effective_from=date(2026, 1, 1)))
    db.add(PayrollNlContractVersion(organization_id=org.id, employee_id=emp.id, version=1, contract_term="INDEFINITE",
                                    written_record=True, on_call=False, start_date=date(2025, 1, 1),
                                    effective_from=date(2025, 1, 1)))
    decision = nl.create_premium_decision(db, organization_id=org.id, tax_year=2026, aof_size_class="SMALL",
                                          aof_basis_year=2024, aof_basis_premium_wage=D("500000"),
                                          decision_reference="BD-WHK-TEST", decision_date=date(2025, 11, 1),
                                          effective_from=date(2026, 1, 1), actor_id=801,
                                          whk_wga_pct=D("0.5000"), whk_zw_flex_pct=D("0.2000"))
    nl.activate_premium_decision(db, decision.id, org.id, actor_id=802)
    nl.create_earning_classification(db, organization_id=None, earning_code="base_salary",
                                     effective_from=date(2026, 1, 1), remuneration_type="REGULAR", wage_tax=True,
                                     employee_insurance_wage=True, zvw_wage=True, pensionable=True,
                                     wkr_treatment="WAGE", vacation_allowance_basis=True, minimum_wage_reckonable=True)
    db.commit()
    return type("NLX", (), dict(org=org, emp=emp, pack=pack, table=table, decision=decision))()


def _run_and_approve(db, nlx, month):
    from app.modules.payroll import service
    PREPARER, APPROVER = 801, 802
    end = date(2026, month, 30 if month in (4, 6, 9, 11) else 31)
    run = PayrollRun(organization_id=nlx.org.id, period_label=f"2026-{month:02d}", period_start=date(2026, month, 1),
                     period_end=end, pay_date=end, created_by=PREPARER,
                     attendance_override_reason="TEST")
    db.add(run)
    db.commit()
    db.refresh(run)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, nlx.org.id)
    service.advance_payroll_run_status(db, run.id, APPROVER, nlx.org.id)
    db.refresh(run)
    return run


from datetime import date
from decimal import Decimal as D


class TestTransportIntegration:
    def test_submit_return_creates_submission_record(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)

        sub = digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)
        assert sub.return_id == ret.id
        assert sub.attempt_no == 1
        assert sub.channel == "VALIDATION_SERVICE"
        assert sub.transport_status == "ACK"
        assert sub.digipoort_reference is not None
        assert sub.ack_payload is not None

    def test_submit_return_requires_payload(self, db, nlx):
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = PayrollNlLoonaangifteReturn(
            organization_id=nlx.org.id,
            employer_profile_id=employer.id,
            loonheffingennummer=employer.loonheffingennummer,
            tax_year=2026,
            period_code="202603",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            due_date=date(2026, 4, 30),
            payment_due_date=date(2026, 4, 30),
            version=1,
            return_type="REGULAR",
            status="READY",
            total_payable=D("0"),
            idempotency_key="test-no-payload",
        )
        db.add(ret)
        db.flush()
        with pytest.raises(BadRequestException, match="no XML payload"):
            digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)

    def test_submit_return_marks_filed_on_success(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)
        digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)
        db.refresh(ret)
        assert ret.status == "READY"
        filed = filings.mark_filed(db, ret.id, 801, digipoort_reference="DIGI-123")
        assert filed.status == "FILED"

    def test_timeout_becomes_unknown(self, db, nlx, monkeypatch):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)

        slow_transport = MagicMock()
        slow_transport.send.return_value = digi.TransportResult(
            success=True, transport_status=digi.TransportStatus.SENT,
            digipoort_reference="SLOW-123"
        )
        # Poll never returns ACK/REJECTED - returns SENT so loop continues until timeout
        slow_transport.poll_acknowledgement.return_value = digi.TransportResult(
            success=True, transport_status=digi.TransportStatus.SENT,
            digipoort_reference="SLOW-123"
        )

        with patch.object(digi, "get_transport", return_value=slow_transport):
            with pytest.raises(digi.TimeoutError):
                digi.submit_return(db, ret.id, digi.DigipoortChannel.DIGIPOORT, timeout_seconds=1)

        sub = db.query(PayrollNlDigipoortSubmission).filter(
            PayrollNlDigipoortSubmission.return_id == ret.id).one()
        assert sub.transport_status == "UNKNOWN"
        assert sub.error_codes is not None
        assert any(e["code"] == "TIMEOUT" for e in sub.error_codes)

    def test_reconcile_unknown_before_retry(self, db, nlx, monkeypatch):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)

        sub = PayrollNlDigipoortSubmission(
            return_id=ret.id, attempt_no=1, channel="DIGIPOORT",
            cert_fingerprint="fp", payload_sha256="sha256",
            transport_status="UNKNOWN", digipoort_reference="RECON-123",
            sent_at=datetime.utcnow() - timedelta(hours=25),
            idempotency_key="idem-recon"
        )
        db.add(sub)
        db.flush()

        mock_transport = MagicMock()
        mock_transport.poll_acknowledgement.return_value = digi.TransportResult(
            success=True, transport_status=digi.TransportStatus.ACK,
            digipoort_reference="RECON-123", ack_payload="<Ack/>"
        )

        with patch.object(digi, "get_transport", return_value=mock_transport):
            count = digi.reconcile_unknown_submissions(db, max_age_hours=24)

        assert count == 1
        db.refresh(sub)
        assert sub.transport_status == "ACK"
        assert sub.reconciled_at is not None

    def test_retry_after_reconciliation(self, db, nlx, monkeypatch):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)

        sub = PayrollNlDigipoortSubmission(
            return_id=ret.id, attempt_no=1, channel="DIGIPOORT",
            cert_fingerprint="fp", payload_sha256="sha256",
            transport_status="UNKNOWN", digipoort_reference="RETRY-123",
            sent_at=datetime.utcnow() - timedelta(hours=25),
            idempotency_key="idem-retry"
        )
        db.add(sub)
        db.flush()

        mock_transport = MagicMock()
        mock_transport.send.return_value = digi.TransportResult(
            success=True, transport_status=digi.TransportStatus.SENT,
            digipoort_reference="RETRY-NEW-123"
        )
        # Reconciliation proves the first attempt was REJECTED; only then is it resent.
        mock_transport.poll_acknowledgement.side_effect = [
            digi.TransportResult(success=False, transport_status=digi.TransportStatus.REJECTED,
                                 digipoort_reference="RETRY-123", error_codes=[{"code": "REJ"}]),
            digi.TransportResult(success=True, transport_status=digi.TransportStatus.ACK,
                                 digipoort_reference="RETRY-NEW-123", ack_payload="<Ack/>"),
        ]

        with patch.object(digi, "get_transport", return_value=mock_transport):
            new_sub = digi.retry_submission(db, sub.id)

        assert new_sub.attempt_no == 2
        assert new_sub.transport_status == "ACK"

    def test_three_separate_states_transport_acceptance_payment(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)

        digi.submit_return(db, ret.id, digi.DigipoortChannel.VALIDATION_SERVICE)

        filings.mark_filed(db, ret.id, 801, digipoort_reference="DIGI-123")
        db.refresh(ret)
        assert ret.status == "FILED"

        accepted = filings.mark_accepted(db, ret.id)
        assert accepted.status == "ACCEPTED"

        payment = filings.prepare_authority_payment(db, ret.id, 801, "PAY-123")
        assert payment.status == "PREPARED"
        filings.release_payment(db, payment.id, 802)  # four-eyes: not the preparer
        filings.settle_payment(db, payment.id, "BANK-456", "MT103")
        db.refresh(payment)
        assert payment.status == "SETTLED"

    def test_get_transport_status(self):
        status = digi.get_transport_status(digi.DigipoortChannel.VALIDATION_SERVICE)
        assert status["channel"] == "VALIDATION_SERVICE"
        assert status["enabled"] is True
        assert status["healthy"] is True

        status = digi.get_transport_status(digi.DigipoortChannel.DIGIPOORT)
        assert status["enabled"] is False