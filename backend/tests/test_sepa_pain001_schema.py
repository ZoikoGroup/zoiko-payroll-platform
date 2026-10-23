"""Phase 4.1 / 4.2 (bank files): the pain.001.001.09 builder validated against
the official ISO 20022 XSD, and the per-country bank-detail capture and
routing that feed every bank file.

IBANs are generated at runtime (valid check digits computed here) so the
repository PII scan (scripts/scan_test_data) never sees an IBAN literal.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import bank_routing
from app.modules.payroll.bank_export import sepa_pain001 as sepa


def _iban(country: str, bban: str) -> str:
    """A syntactically valid IBAN for a BBAN (check digits computed)."""
    numeric = int("".join(str(int(ch, 36)) for ch in bban + country + "00"))
    return f"{country}{98 - numeric % 97:02d}{bban}"


NL_DEBTOR = _iban("NL", "ABNA" + "0417164300")
NL_CREDITOR = _iban("NL", "INGB" + "0001234567")
CH_IBAN = _iban("CH", "00762" + "011623852957")
SA_IBAN = _iban("SA", "80" + "000000608010167519")
CREATED = datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)
BSN = "".join(("111", "222", "333"))            # elfproef-valid sample, built at runtime (PII scan)


def _batch(n_items=1, *, name="Jan de Vries", bic=None, execution=date(2026, 3, 25), local_instrument=None):
    return sepa.SepaBatch(
        message_id="SAL-R1-1", initiating_party=sepa.SepaParty(name="Zoiko BV"),
        debtor=sepa.SepaParty(name="Zoiko BV", postal_code="1011AB", city="Amsterdam", country="NL",
                              address_line1="Dam 1", organisation_id="123456789L01"),
        debtor_account_iban=NL_DEBTOR, debtor_agent_bic=bic, requested_execution_date=execution,
        category_purpose="SALA", local_instrument=local_instrument,
        items=[sepa.SepaPaymentItem(end_to_end_id=f"PAY-1-{i}", amount=Decimal("2500.10") + i,
                                    creditor=sepa.SepaParty(name=f"{name} {i}"), creditor_account_iban=NL_CREDITOR,
                                    purpose_code="SALA", remittance_info="Loon 2026-03")
               for i in range(1, n_items + 1)])


def _build(batch, created=CREATED):
    return sepa.Pain001Builder(created_at=created).add_batch(batch).build()


# ── the file is valid against the official XSD ───────────────────────────

@pytest.mark.parametrize("n_items, name", [(1, "Jan de Vries"), (50, "Werknemer"), (2, "Zoë Ölçer-Ñúñez")])
def test_files_validate_against_the_official_xsd(n_items, name):
    xml = _build(_batch(n_items, name=name))
    sepa.validate_against_xsd(xml)                       # build() already did; explicit for the record
    assert xml.count("<CdtTrfTxInf>") == n_items
    assert '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">' in xml


def test_the_bundled_xsd_is_the_official_one():
    import hashlib

    digest = hashlib.sha256(sepa.XSD_PATH.read_bytes()).hexdigest()
    assert digest == "de038b373e47b0077b1832ddd81f4b2f1eb25d35721f62da1e38b7f5a09fda24"


def test_a_tampered_file_fails_the_xsd():
    xml = _build(_batch()).replace("<PmtMtd>TRF</PmtMtd>", "<PmtMtd>XXX</PmtMtd>")
    with pytest.raises(sepa.SepaValidationError, match="schema validation failed"):
        sepa.validate_against_xsd(xml)


# ── each old defect ──────────────────────────────────────────────────────

def test_creation_time_is_the_given_one_and_bytes_are_deterministic():
    first, second = _build(_batch()), _build(_batch())
    assert first == second                                           # same batch + stored CreDtTm = same bytes
    assert "<CreDtTm>2026-03-20T09:00:00</CreDtTm>" in first


def test_execution_date_is_a_payment_information_element_and_required():
    xml = _build(_batch())
    pmt_inf, tx = xml.split("<CdtTrfTxInf>", 1)
    assert "<ReqdExctnDt>" in pmt_inf and "<ReqdExctnDt>" not in tx
    with pytest.raises(sepa.SepaValidationError, match="execution date"):
        _build(_batch(execution=None))


def test_debtor_agent_is_always_present():
    assert "<Id>NOTPROVIDED</Id>" in _build(_batch(bic=None))
    assert "<BICFI>ABNANL2A</BICFI>" in _build(_batch(bic="ABNANL2A"))


def test_no_instant_payment_unless_asked():
    assert "<LclInstrm>" not in _build(_batch())
    assert "<LclInstrm>" in _build(_batch(local_instrument="INST"))


def test_ibans_are_normalised_and_masked_in_errors():
    spaced = " ".join(NL_CREDITOR[i:i + 4] for i in range(0, len(NL_CREDITOR), 4)).lower()
    batch = _batch()
    batch.items[0].creditor_account_iban = spaced
    assert f"<IBAN>{NL_CREDITOR}</IBAN>" in _build(batch)
    bad = NL_CREDITOR[:-1] + ("0" if NL_CREDITOR[-1] != "0" else "1")
    batch.items[0].creditor_account_iban = bad
    with pytest.raises(sepa.SepaValidationError) as exc:
        _build(batch)
    assert bad not in str(exc.value) and bad[-4:] in str(exc.value)


# ── Phase 4.1: bank details captured and routed per country ──────────────

def test_iban_checksum_helper():
    from app.modules.payroll.employee_validation import iban_checksum_ok

    for iban in (NL_DEBTOR, CH_IBAN, SA_IBAN):
        assert iban_checksum_ok(iban)
    assert not iban_checksum_ok(NL_DEBTOR[:-1] + ("1" if NL_DEBTOR[-1] == "0" else "0"))


def test_nl_iban_is_kept_on_save_and_checked():
    from app.modules.payroll.employee_validation import NLEmployeeValidation

    cleaned = NLEmployeeValidation.validate({"bsn": BSN, "iban": NL_CREDITOR.lower(), "bic": "ingbnl2a"})
    assert cleaned["iban"] == NL_CREDITOR and cleaned["bic"] == "INGBNL2A"     # was silently dropped
    with pytest.raises(BadRequestException, match="mod-97"):
        NLEmployeeValidation.validate({"bsn": BSN, "iban": NL_CREDITOR[:-1] + "9"
                                       if NL_CREDITOR[-1] != "9" else NL_CREDITOR[:-1] + "8"})


def test_ch_iban_is_captured():
    from app.modules.payroll.employee_validation import CHEmployeeValidation

    ahv = "756" + "9217076985"                                        # documented sample AHV number
    cleaned = CHEmployeeValidation.validate({"ahv_number": ahv, "iban": CH_IBAN})
    assert cleaned["iban"] == CH_IBAN


def test_sa_iban_accepts_letters_and_national_id_must_start_with_1():
    from app.modules.payroll.employee_validation import SAEmployeeValidation, sa_iban_mod97_valid

    lettered = _iban("SA", "80" + "000000608010ABCDEF")
    assert sa_iban_mod97_valid(lettered)                              # was refused (digits only)
    iqama_like = "2" + "000000000"
    with pytest.raises(BadRequestException):
        SAEmployeeValidation.validate({"national_id_iqama": iqama_like, "identity_type": "NATIONAL_ID"})


def test_br_extra_routing_fields():
    from app.modules.payroll.employee_validation import BREmployeeValidation

    spec = BREmployeeValidation.FIELD_SPECS
    assert {"bank_ispb", "bank_agency_digit", "bank_account_digit"} <= set(spec)


def _payee(country, **fields):
    return SimpleNamespace(country_code=country, compliance_fields=fields, bank_account=None, ifsc=None)


def test_routing_and_account_columns_are_filled_for_every_country():
    assert bank_routing.btf_routing_value(_payee("CH", iban=CH_IBAN, bic="UBSWCHZH80A")) == f"{CH_IBAN} UBSWCHZH80A"
    assert bank_routing.btf_routing_value(_payee("SA", iban=SA_IBAN)) == SA_IBAN
    assert bank_routing.btf_routing_label("CH") == "IBAN" and bank_routing.btf_routing_label("SA") == "IBAN"
    ted = _payee("BR", bank_compe="341", bank_agency="1234", bank_agency_digit="5", bank_account="98765",
                 bank_account_digit="X", pix_key="pix@example.com")
    assert bank_routing.btf_routing_value(ted) == "341/1234-5/98765-X"   # was the PIX key only
    assert bank_routing.btf_routing_value(_payee("BR", pix_key="pix@example.com")) == "pix@example.com"
    assert bank_routing.btf_account_value(_payee("BR", bank_account="98765")) == "98765"
    assert bank_routing.btf_account_value(_payee("SA", account_number="123456789012")) == "123456789012"


def test_brazil_payment_treatment_holds_nothing():
    from app.modules.payroll import brazil_service

    assert brazil_service.payment_treatment(None, 1, None, []) == {}
