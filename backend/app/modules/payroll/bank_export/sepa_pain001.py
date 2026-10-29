"""
bank_export/sepa_pain001.py
----------------------------
SEPA Credit Transfer initiation (ISO 20022 pain.001.001.09) builder.

Reusable by every SEPA jurisdiction (NL today; DE / FR / IE can adopt it).
Every file is validated against the official XSD
(bank_export/schemas/pain.001.001.09.xsd) before it is returned — a file a
bank would reject is never produced.

Phase 4.2 (2026-10-23) rewrite of the earlier builder, which emitted
CstmrCdtTrfInitn without its Document root, un-namespaced children, a
CreDtTm fabricated from a hash, ReqdExctnDt inside CdtTrfTxInf, a hard-coded
instant-payment LclInstrm, no DbtrAgt without a BIC and IBANs with spaces.

Element order follows the pain.001.001.09 XSD (GrpHdr, PmtInf,
CdtTrfTxInf, PartyIdentification135, PostalAddress24).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from lxml import etree

NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
XSD_PATH = Path(__file__).resolve().parent / "schemas" / "pain.001.001.09.xsd"
NOT_PROVIDED = "NOTPROVIDED"           # agent identification when no BIC is known (pain.001 usage rule)

_MAX_ID = 35                           # Max35Text: MsgId, PmtInfId, EndToEndId, Othr/Id
_MAX_NAME = 140                        # Max140Text: Nm
_MAX_USTRD = 140                       # Max140Text: RmtInf/Ustrd


@dataclass
class SepaParty:
    """Debtor, creditor or initiating party."""
    name: str
    iban: str = ""
    bic: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    organisation_id: Optional[str] = None  # e.g. tax ID, KVK
    private_id: Optional[str] = None


@dataclass
class SepaPaymentItem:
    """One credit transfer. `requested_execution_date` is accepted for
    backwards compatibility but the date is a payment-information (batch)
    element in pain.001.001.09 — the batch date governs."""
    end_to_end_id: str
    amount: Decimal
    currency: str = "EUR"
    creditor: SepaParty = None
    creditor_account_iban: str = None
    creditor_agent_bic: Optional[str] = None
    remittance_info: Optional[str] = None
    purpose_code: Optional[str] = None      # e.g. "SALA"
    category_purpose: Optional[str] = None
    requested_execution_date: Optional[date] = None
    structured_reference: Optional[str] = None   # RmtInf/Strd creditor reference (e.g. betalingskenmerk)


@dataclass
class SepaBatch:
    """One payment-information block (one debtor account, one execution date)."""
    message_id: str
    initiating_party: SepaParty
    debtor: SepaParty
    debtor_account_iban: str
    debtor_agent_bic: Optional[str] = None
    requested_execution_date: Optional[date] = None
    items: List[SepaPaymentItem] = field(default_factory=list)
    batch_booking: bool = True
    charge_bearer: str = "SLEV"
    service_level: str = "SEPA"
    local_instrument: Optional[str] = None   # e.g. "INST" only when the debtor bank offers it
    category_purpose: Optional[str] = None   # e.g. "SALA" (salary) / "TAXS"


class SepaValidationError(ValueError):
    """Raised when SEPA data or the built file fails validation."""


def normalise_iban(value: Optional[str]) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def mask_iban(value: Optional[str]) -> str:
    raw = normalise_iban(value)
    return f"{raw[:2]}**…{raw[-4:]}" if len(raw) > 6 else "****"


def validate_iban(iban: str) -> bool:
    """ISO 13616 mod-97 check (shape 2 letters + 2 digits + 10-30 alphanumerics)."""
    raw = normalise_iban(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", raw):
        return False
    return int("".join(str(int(ch, 36)) for ch in raw[4:] + raw[:4])) % 97 == 1


def validate_bic(bic: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", re.sub(r"\s+", "", str(bic or "")).upper()))


def validate_batch(batch: SepaBatch) -> List[str]:
    """Data errors for one batch (empty = valid). IBANs are masked in messages."""
    errors = []
    if not batch.message_id:
        errors.append("Batch message_id is required")
    elif len(batch.message_id) > _MAX_ID:
        errors.append(f"Batch message_id is longer than {_MAX_ID} characters")
    if not batch.debtor or not batch.debtor.name:
        errors.append("Debtor name is required")
    if not batch.debtor_account_iban:
        errors.append("Debtor IBAN is required")
    elif not validate_iban(batch.debtor_account_iban):
        errors.append(f"Invalid debtor IBAN {mask_iban(batch.debtor_account_iban)}")
    if batch.debtor_agent_bic and not validate_bic(batch.debtor_agent_bic):
        errors.append("Invalid debtor agent BIC")
    if not batch.items:
        errors.append("A batch needs at least one payment")
    for i, item in enumerate(batch.items):
        if not item.end_to_end_id:
            errors.append(f"Item {i}: end_to_end_id is required")
        elif len(item.end_to_end_id) > _MAX_ID:
            errors.append(f"Item {i}: end_to_end_id is longer than {_MAX_ID} characters")
        if item.amount is None or Decimal(item.amount) <= 0:
            errors.append(f"Item {i}: amount must be positive")
        if not item.creditor:
            errors.append(f"Item {i}: creditor is required")
        elif not item.creditor.name:
            errors.append(f"Item {i}: creditor name is required")
        creditor_iban = item.creditor_account_iban or (item.creditor.iban if item.creditor else None)
        if not creditor_iban:
            errors.append(f"Item {i}: creditor IBAN is required")
        elif not validate_iban(creditor_iban):
            errors.append(f"Item {i}: invalid creditor IBAN {mask_iban(creditor_iban)}")
        if item.creditor_agent_bic and not validate_bic(item.creditor_agent_bic):
            errors.append(f"Item {i}: invalid creditor agent BIC")
    return errors


_SCHEMA = None


def validate_against_xsd(xml: str) -> None:
    """Raise SepaValidationError unless `xml` is valid pain.001.001.09."""
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = etree.XMLSchema(etree.parse(str(XSD_PATH)))
    doc = etree.fromstring(xml.encode("utf-8"))
    if not _SCHEMA.validate(doc):
        raise SepaValidationError("pain.001.001.09 schema validation failed: "
                                  + "; ".join(str(e.message) for e in list(_SCHEMA.error_log)[:5]))


def _el(parent, tag: str, text: Optional[str] = None):
    node = etree.SubElement(parent, f"{{{NAMESPACE}}}{tag}")
    if text is not None:
        node.text = str(text)
    return node


def _amount(value) -> str:
    return f"{Decimal(value):.2f}"


class Pain001Builder:
    """Builds one schema-valid pain.001.001.09 message.

    `created_at` is the message's CreDtTm. A caller that stores the file (or
    must rebuild identical bytes) passes its stored creation time; otherwise
    the current UTC time is used — never a fabricated date."""

    def __init__(self, created_at: Optional[datetime] = None):
        self._batches: List[SepaBatch] = []
        self._created_at = created_at

    def add_batch(self, batch: SepaBatch) -> "Pain001Builder":
        self._batches.append(batch)
        return self

    def message_id(self) -> str:
        """Deterministic MsgId from the batch ids (max 35 characters)."""
        digest = hashlib.sha256("|".join(b.message_id for b in self._batches).encode()).hexdigest()
        return f"MSG-{digest[:31].upper()}"

    def build(self, pretty: bool = True) -> str:
        if not self._batches:
            raise SepaValidationError("SEPA validation failed: no payment batch")
        errors = [e for b in self._batches for e in validate_batch(b)]
        if errors:
            raise SepaValidationError(f"SEPA validation failed: {errors}")
        created = (self._created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)

        document = etree.Element(f"{{{NAMESPACE}}}Document", nsmap={None: NAMESPACE})
        initiation = _el(document, "CstmrCdtTrfInitn")
        header = _el(initiation, "GrpHdr")
        _el(header, "MsgId", self.message_id())
        _el(header, "CreDtTm", created.strftime("%Y-%m-%dT%H:%M:%S"))
        _el(header, "NbOfTxs", sum(len(b.items) for b in self._batches))
        _el(header, "CtrlSum", _amount(sum(Decimal(i.amount) for b in self._batches for i in b.items)))
        self._party(_el(header, "InitgPty"), self._batches[0].initiating_party)
        for index, batch in enumerate(self._batches, start=1):
            self._payment_information(initiation, batch, index)

        xml = etree.tostring(document, encoding="utf-8", xml_declaration=True, pretty_print=pretty).decode("utf-8")
        validate_against_xsd(xml)
        return xml

    def sha256(self) -> str:
        return hashlib.sha256(self.build(pretty=False).encode("utf-8")).hexdigest()

    # ── blocks (XSD order) ────────────────────────────────────────────
    def _payment_information(self, parent, batch: SepaBatch, index: int) -> None:
        info = _el(parent, "PmtInf")
        digest = hashlib.sha256(batch.message_id.encode()).hexdigest()[:24].upper()
        _el(info, "PmtInfId", f"PMT-{index}-{digest}"[:_MAX_ID])
        _el(info, "PmtMtd", "TRF")
        _el(info, "BtchBookg", "true" if batch.batch_booking else "false")
        _el(info, "NbOfTxs", len(batch.items))
        _el(info, "CtrlSum", _amount(sum(Decimal(i.amount) for i in batch.items)))
        type_info = _el(info, "PmtTpInf")
        _el(_el(type_info, "SvcLvl"), "Cd", batch.service_level)
        if batch.local_instrument:
            _el(_el(type_info, "LclInstrm"), "Cd", batch.local_instrument)
        category = batch.category_purpose or next((i.category_purpose for i in batch.items if i.category_purpose), None)
        if category:
            _el(_el(type_info, "CtgyPurp"), "Cd", category)
        execution = (batch.requested_execution_date
                     or next((i.requested_execution_date for i in batch.items if i.requested_execution_date), None))
        if execution is None:
            raise SepaValidationError("SEPA validation failed: a requested execution date is required")
        _el(_el(info, "ReqdExctnDt"), "Dt", execution.isoformat())
        self._party(_el(info, "Dbtr"), batch.debtor)
        _el(_el(_el(info, "DbtrAcct"), "Id"), "IBAN", normalise_iban(batch.debtor_account_iban))
        self._agent(_el(info, "DbtrAgt"), batch.debtor_agent_bic)
        _el(info, "ChrgBr", batch.charge_bearer)
        for item in batch.items:
            self._transfer(_el(info, "CdtTrfTxInf"), item)

    def _transfer(self, tx, item: SepaPaymentItem) -> None:
        _el(_el(tx, "PmtId"), "EndToEndId", item.end_to_end_id)
        amount = _el(_el(tx, "Amt"), "InstdAmt", _amount(item.amount))
        amount.set("Ccy", item.currency)
        if item.creditor_agent_bic:
            self._agent(_el(tx, "CdtrAgt"), item.creditor_agent_bic)
        self._party(_el(tx, "Cdtr"), item.creditor)
        _el(_el(_el(tx, "CdtrAcct"), "Id"), "IBAN", normalise_iban(item.creditor_account_iban or item.creditor.iban))
        if item.purpose_code:
            _el(_el(tx, "Purp"), "Cd", item.purpose_code)
        if item.remittance_info or item.structured_reference:
            remittance = _el(tx, "RmtInf")
            if item.structured_reference:
                reference = _el(_el(remittance, "Strd"), "CdtrRefInf")
                _el(_el(_el(reference, "Tp"), "CdOrPrtry"), "Cd", "SCOR")
                _el(reference, "Ref", item.structured_reference[:_MAX_ID])
            elif item.remittance_info:
                _el(remittance, "Ustrd", item.remittance_info[:_MAX_USTRD])

    @staticmethod
    def _agent(parent, bic: Optional[str]) -> None:
        institution = _el(parent, "FinInstnId")
        if bic:
            _el(institution, "BICFI", re.sub(r"\s+", "", bic).upper())
        else:
            _el(_el(institution, "Othr"), "Id", NOT_PROVIDED)

    @staticmethod
    def _party(parent, party: SepaParty) -> None:
        _el(parent, "Nm", (party.name or "")[:_MAX_NAME])
        if party.postal_code or party.city or party.country or party.address_line1 or party.address_line2:
            address = _el(parent, "PstlAdr")
            if party.postal_code:
                _el(address, "PstCd", party.postal_code[:16])
            if party.city:
                _el(address, "TwnNm", party.city[:35])
            if party.country:
                _el(address, "Ctry", party.country[:2].upper())
            for line in (party.address_line1, party.address_line2):
                if line:
                    _el(address, "AdrLine", line[:70])
        if party.organisation_id:
            _el(_el(_el(_el(parent, "Id"), "OrgId"), "Othr"), "Id", party.organisation_id[:_MAX_ID])
        elif party.private_id:
            _el(_el(_el(_el(parent, "Id"), "PrvtId"), "Othr"), "Id", party.private_id[:_MAX_ID])


# ── Convenience factory functions (unchanged signatures) ───────────────

def create_pain001(
    *,
    message_id: str,
    debtor_name: str,
    debtor_iban: str,
    debtor_bic: Optional[str] = None,
    debtor_address: Optional[dict] = None,
    creditor_name: str,
    creditor_iban: str,
    creditor_bic: Optional[str] = None,
    amount: Decimal,
    currency: str = "EUR",
    end_to_end_id: str,
    remittance_info: Optional[str] = None,
    purpose_code: Optional[str] = "SALA",
    requested_execution_date: Optional[date] = None,
    initiating_party_name: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> str:
    """Single-payment pain.001 message."""
    batch = SepaBatch(
        message_id=message_id,
        initiating_party=SepaParty(name=initiating_party_name or debtor_name, iban=debtor_iban),
        debtor=SepaParty(name=debtor_name, iban=debtor_iban, bic=debtor_bic, **(debtor_address or {})),
        debtor_account_iban=debtor_iban,
        debtor_agent_bic=debtor_bic,
        requested_execution_date=requested_execution_date,
        category_purpose=purpose_code,
        items=[SepaPaymentItem(end_to_end_id=end_to_end_id, amount=amount, currency=currency,
                               creditor=SepaParty(name=creditor_name, iban=creditor_iban, bic=creditor_bic),
                               creditor_account_iban=creditor_iban, creditor_agent_bic=creditor_bic,
                               remittance_info=remittance_info, purpose_code=purpose_code)],
    )
    return Pain001Builder(created_at=created_at).add_batch(batch).build()


def create_pain001_batch(
    *,
    message_id: str,
    debtor: SepaParty,
    debtor_account_iban: str,
    debtor_agent_bic: Optional[str] = None,
    initiating_party: SepaParty,
    items: List[SepaPaymentItem],
    requested_execution_date: Optional[date] = None,
    batch_booking: bool = True,
    charge_bearer: str = "SLEV",
    category_purpose: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> str:
    """Multi-payment pain.001 message (one payment-information block)."""
    batch = SepaBatch(message_id=message_id, initiating_party=initiating_party, debtor=debtor,
                      debtor_account_iban=debtor_account_iban, debtor_agent_bic=debtor_agent_bic,
                      requested_execution_date=requested_execution_date, items=items,
                      batch_booking=batch_booking, charge_bearer=charge_bearer, category_purpose=category_purpose)
    return Pain001Builder(created_at=created_at).add_batch(batch).build()
