"""
tests/test_netherlands_sepa.py
-------------------------------
Generic SEPA pain.001 builder tests (Phase 10).
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.modules.payroll.bank_export.sepa_pain001 import (
    Pain001Builder,
    SepaBatch,
    SepaParty,
    SepaPaymentItem,
    SepaValidationError,
    validate_batch,
    validate_iban,
    validate_bic,
    create_pain001,
    create_pain001_batch,
)


class TestIbanBicValidation:
    def test_valid_iban_nl(self):
        assert validate_iban("NL91ABNA0417164300") is True

    def test_valid_iban_de(self):
        assert validate_iban("DE89370400440532013000") is True

    def test_invalid_iban_too_short(self):
        assert validate_iban("NL12") is False

    def test_invalid_iban_checksum(self):
        assert validate_iban("NL91ABNA0417164301") is False  # Wrong check digits

    def test_valid_bic_8(self):
        assert validate_bic("ABNANL2A") is True

    def test_valid_bic_11(self):
        assert validate_bic("ABNANL2AXXX") is True

    def test_invalid_bic_too_short(self):
        assert validate_bic("ABNANL") is False


class TestSepaParty:
    def test_minimal_party(self):
        party = SepaParty(name="Test BV", iban="NL91ABNA0417164300")
        assert party.name == "Test BV"
        assert party.iban == "NL91ABNA0417164300"
        assert party.bic is None

    def test_full_party(self):
        party = SepaParty(
            name="Test BV",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            address_line1="Amsterdamstraat 1",
            city="Amsterdam",
            postal_code="1000 AA",
            country="NL",
            organisation_id="123456789",
        )
        assert party.organisation_id == "123456789"


class TestSepaPaymentItem:
    def test_minimal_item(self):
        item = SepaPaymentItem(
            end_to_end_id="E2E-001",
            amount=Decimal("1000.00"),
            creditor=SepaParty(name="John Doe", iban="NL91ABNA0417164300"),
        )
        assert item.amount == Decimal("1000.00")
        assert item.currency == "EUR"
        assert item.purpose_code is None

    def test_full_item(self):
        item = SepaPaymentItem(
            end_to_end_id="E2E-002",
            amount=Decimal("2500.50"),
            currency="EUR",
            creditor=SepaParty(name="Jane Smith", iban="DE89370400440532013000", bic="COBADEFF"),
            creditor_account_iban="DE89370400440532013000",
            creditor_agent_bic="COBADEFF",
            remittance_info="Salary March 2026",
            purpose_code="SALA",
            category_purpose="SALA",
            requested_execution_date=date(2026, 3, 25),
        )
        assert item.remittance_info == "Salary March 2026"
        assert item.requested_execution_date == date(2026, 3, 25)


class TestSepaBatch:
    def test_minimal_batch(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[
                SepaPaymentItem(
                    end_to_end_id="E2E-001",
                    amount=Decimal("1000.00"),
                    creditor=SepaParty(name="Employee", iban="NL91RABO0123456789"),
                )
            ],
        )
        assert batch.message_id == "MSG-001"
        assert len(batch.items) == 1
        assert batch.batch_booking is True


class TestBatchValidation:
    def test_valid_batch(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[
                SepaPaymentItem(
                    end_to_end_id="E2E-001",
                    amount=Decimal("1000.00"),
                    creditor=SepaParty(name="Employee", iban="NL44RABO0123456789"),
                )
            ],
        )
        errors = validate_batch(batch)
        assert errors == []

    def test_missing_message_id(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[],
        )
        errors = validate_batch(batch)
        assert "message_id is required" in str(errors)

    def test_missing_debtor_name(self):
        party = SepaParty(name="", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[],
        )
        errors = validate_batch(batch)
        assert "Debtor name is required" in str(errors)

    def test_invalid_debtor_iban(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164301")  # Bad checksum
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164301",
            items=[],
        )
        errors = validate_batch(batch)
        assert "Invalid debtor IBAN" in str(errors)

    def test_item_missing_creditor(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[SepaPaymentItem(end_to_end_id="E2E-001", amount=Decimal("1000.00"))],
        )
        errors = validate_batch(batch)
        assert "creditor is required" in str(errors)

    def test_item_negative_amount(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[SepaPaymentItem(
                end_to_end_id="E2E-001",
                amount=Decimal("-100.00"),
                creditor=SepaParty(name="Employee", iban="NL44RABO0123456789"),
            )],
        )
        errors = validate_batch(batch)
        assert "amount must be positive" in str(errors)

    def test_invalid_creditor_iban(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[SepaPaymentItem(
                end_to_end_id="E2E-001",
                amount=Decimal("1000.00"),
                creditor=SepaParty(name="Employee", iban="NL44RABO0123456780"),  # Bad checksum
            )],
        )
        errors = validate_batch(batch)
        assert "invalid creditor IBAN" in str(errors)


class TestPain001Builder:
    def test_single_payment_xml(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[
                SepaPaymentItem(
                    end_to_end_id="E2E-001",
                    amount=Decimal("1000.00"),
                    creditor=SepaParty(name="Employee", iban="NL44RABO0123456789"),
                )
            ],
        )
        xml = Pain001Builder().add_batch(batch).build()
        assert "<?xml" in xml
        assert "CstmrCdtTrfInitn" in xml
        assert "GrpHdr" in xml
        assert "PmtInf" in xml
        assert "CdtTrfTxInf" in xml
        assert "E2E-001" in xml
        assert "1000.00" in xml
        assert "Employee" in xml
        assert "NL44RABO0123456789" in xml

    def test_multiple_batches(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch1 = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[
                SepaPaymentItem(
                    end_to_end_id="E2E-001",
                    amount=Decimal("1000.00"),
                    creditor=SepaParty(name="Employee 1", iban="NL44RABO0123456789"),
                )
            ],
        )
        batch2 = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-002",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[
                SepaPaymentItem(
                    end_to_end_id="E2E-002",
                    amount=Decimal("2000.00"),
                    creditor=SepaParty(name="Employee 2", iban="NL20INGB0001234567"),
                )
            ],
        )
        xml = Pain001Builder().add_batch(batch1).add_batch(batch2).build()
        # Count PmtInf in the non-namespaced form
        assert xml.count("<PmtInf>") == 2
        assert "E2E-001" in xml
        assert "E2E-002" in xml

    def test_sha256_deterministic(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[
                SepaPaymentItem(
                    end_to_end_id="E2E-001",
                    amount=Decimal("1000.00"),
                    creditor=SepaParty(name="Employee", iban="NL44RABO0123456789"),
                )
            ],
        )
        builder = Pain001Builder().add_batch(batch)
        hash1 = builder.sha256()
        hash2 = builder.sha256()
        assert hash1 == hash2
        assert len(hash1) == 64


class TestConvenienceFunctions:
    def test_create_pain001_single(self):
        xml = create_pain001(
            requested_execution_date=date(2026, 3, 25),
            message_id="MSG-001",
            debtor_name="Employer BV",
            debtor_iban="NL91ABNA0417164300",
            creditor_name="Employee",
            creditor_iban="NL44RABO0123456789",
            amount=Decimal("1000.00"),
            end_to_end_id="E2E-001",
            remittance_info="Salary",
        )
        assert "CstmrCdtTrfInitn" in xml
        assert "E2E-001" in xml
        assert "1000.00" in xml

    def test_create_pain001_batch(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        items = [
            SepaPaymentItem(
                end_to_end_id="E2E-001",
                amount=Decimal("1000.00"),
                creditor=SepaParty(name="Employee 1", iban="NL44RABO0123456789"),
            ),
            SepaPaymentItem(
                end_to_end_id="E2E-002",
                amount=Decimal("2000.00"),
                creditor=SepaParty(name="Employee 2", iban="NL20INGB0001234567"),
            ),
        ]
        xml = create_pain001_batch(
            requested_execution_date=date(2026, 3, 25),
            message_id="BATCH-001",
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            initiating_party=party,
            items=items,
        )
        assert "CstmrCdtTrfInitn" in xml
        assert "E2E-001" in xml
        assert "E2E-002" in xml
        # Count CdtTrfTxInf in the non-namespaced form
        assert xml.count("<CdtTrfTxInf>") == 2


class TestSepaValidationError:
    def test_raised_on_invalid_batch(self):
        party = SepaParty(name="Employer BV", iban="NL91ABNA0417164300")
        batch = SepaBatch(
            requested_execution_date=date(2026, 3, 25),
            message_id="",
            initiating_party=party,
            debtor=party,
            debtor_account_iban="NL91ABNA0417164300",
            items=[],
        )
        with pytest.raises(SepaValidationError):
            Pain001Builder().add_batch(batch).build()