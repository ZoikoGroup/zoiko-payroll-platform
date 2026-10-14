"""
bank_export/sepa_pain001.py
----------------------------
Generic SEPA Credit Transfer (pain.001.001.09) builder.

Reusable by DE, FR, IE, NL and other SEPA jurisdictions.
Produces ISO 20022 pain.001.001.09 XML for credit transfers.

Schema: https://www.iso20022.org/standardsrepository/type/pain.001.001.09
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from xml.etree import ElementTree as ET
from xml.dom import minidom


# ── Namespace constants ──────────────────────────────────────────────
NS = {
    "doc": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
SCHEMA_LOCATION = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09 pain.001.001.09.xsd"


@dataclass
class SepaParty:
    """Debtor or Creditor party."""
    name: str
    iban: str
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
    """Individual credit transfer instruction."""
    end_to_end_id: str
    amount: Decimal
    currency: str = "EUR"
    creditor: SepaParty = None
    creditor_account_iban: str = None
    creditor_agent_bic: Optional[str] = None
    remittance_info: Optional[str] = None
    purpose_code: Optional[str] = None  # e.g. "SALA" for salary
    category_purpose: Optional[str] = None
    requested_execution_date: Optional[date] = None


@dataclass
class SepaBatch:
    """Payment batch (message level)."""
    message_id: str
    initiating_party: SepaParty
    debtor: SepaParty
    debtor_account_iban: str
    debtor_agent_bic: Optional[str] = None
    requested_execution_date: Optional[date] = None
    items: List[SepaPaymentItem] = field(default_factory=list)
    batch_booking: bool = True
    charge_bearer: str = "SLEV"  # Following Service Level


class Pain001Builder:
    """Builds pain.001.001.09 XML from structured data."""

    def __init__(self):
        self._batches: List[SepaBatch] = []

    def add_batch(self, batch: SepaBatch) -> "Pain001Builder":
        self._batches.append(batch)
        return self

    def build(self, pretty: bool = True) -> str:
        """Generate the pain.001 XML string."""
        # Validate all batches
        for batch in self._batches:
            errors = validate_batch(batch)
            if errors:
                raise SepaValidationError(f"SEPA validation failed: {errors}")

        root = self._create_root()
        grp_hdr = self._create_group_header(root)
        for idx, batch in enumerate(self._batches):
            self._create_payment_info(root, batch, idx + 1)
        return self._to_string(root, pretty)

    def _create_root(self) -> ET.Element:
        root = ET.Element(
            "{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}Document",
            attrib={
                "xmlns": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            },
        )
        root.set(
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
            SCHEMA_LOCATION,
        )
        cstmr_cdt_trf = ET.SubElement(root, "{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}CstmrCdtTrfInitn")
        return cstmr_cdt_trf

    def _create_group_header(self, root: ET.Element) -> ET.Element:
        grp_hdr = ET.SubElement(root, "GrpHdr")
        # Use deterministic message ID for reproducible hashes
        batch_ids = "".join(b.message_id for b in self._batches)
        msg_id = f"MSG-{hashlib.sha256(batch_ids.encode()).hexdigest()[:30].upper()}"
        ET.SubElement(grp_hdr, "MsgId").text = msg_id
        # Use deterministic timestamp based on batch IDs for reproducible hashes
        timestamp_base = hashlib.sha256(batch_ids.encode()).hexdigest()[:16]
        # Convert first 12 hex chars to a pseudo-timestamp
        year = 2020 + int(timestamp_base[:2], 16) % 10
        month = 1 + int(timestamp_base[2:4], 16) % 12
        day = 1 + int(timestamp_base[4:6], 16) % 28
        hour = int(timestamp_base[6:8], 16) % 24
        minute = int(timestamp_base[8:10], 16) % 60
        second = int(timestamp_base[10:12], 16) % 60
        ET.SubElement(grp_hdr, "CreDtTm").text = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
        ET.SubElement(grp_hdr, "NbOfTxs").text = str(sum(len(b.items) for b in self._batches))
        total_amount = sum(item.amount for b in self._batches for item in b.items)
        ET.SubElement(grp_hdr, "CtrlSum").text = f"{total_amount:.2f}"
        initg_pty = ET.SubElement(grp_hdr, "InitgPty")
        self._add_party_name(initg_pty, self._batches[0].initiating_party if self._batches else SepaParty(name="", iban=""))
        return grp_hdr

    def _create_payment_info(self, root: ET.Element, batch: SepaBatch, idx: int) -> ET.Element:
        pmt_inf = ET.SubElement(root, "PmtInf")
        # Deterministic PmtInfId based on batch message_id and index
        pmt_inf_id = f"BATCH-{idx}-{hashlib.sha256(batch.message_id.encode()).hexdigest()[:12].upper()}"
        ET.SubElement(pmt_inf, "PmtInfId").text = pmt_inf_id
        ET.SubElement(pmt_inf, "PmtMtd").text = "TRF"
        ET.SubElement(pmt_inf, "BtchBookg").text = "true" if batch.batch_booking else "false"
        ET.SubElement(pmt_inf, "NbOfTxs").text = str(len(batch.items))
        ET.SubElement(pmt_inf, "CtrlSum").text = f"{sum(item.amount for item in batch.items):.2f}"
        ET.SubElement(pmt_inf, "PmtTpInf").extend(self._payment_type_info(batch))
        reqd_exctn = ET.SubElement(pmt_inf, "ReqdExctnDt")
        ET.SubElement(reqd_exctn, "Dt").text = (batch.requested_execution_date or date.today()).isoformat()

        # Debtor
        dbtr = ET.SubElement(pmt_inf, "Dbtr")
        self._add_party_name(dbtr, batch.debtor)
        if batch.debtor.organisation_id or batch.debtor.private_id:
            self._add_party_id(dbtr, batch.debtor)

        dbtr_acct = ET.SubElement(pmt_inf, "DbtrAcct")
        dbtr_acct_id = ET.SubElement(dbtr_acct, "Id")
        ET.SubElement(dbtr_acct_id, "IBAN").text = batch.debtor_account_iban

        if batch.debtor_agent_bic:
            dbtr_agt = ET.SubElement(pmt_inf, "DbtrAgt")
            fin_instn = ET.SubElement(dbtr_agt, "FinInstnId")
            ET.SubElement(fin_instn, "BICFI").text = batch.debtor_agent_bic

        chrg_br = ET.SubElement(pmt_inf, "ChrgBr")
        chrg_br.text = batch.charge_bearer

        for item in batch.items:
            cdt_trf = ET.SubElement(pmt_inf, "CdtTrfTxInf")
            self._add_payment_item(cdt_trf, item, batch)

        return pmt_inf

    def _payment_type_info(self, batch: SepaBatch) -> List[ET.Element]:
        """Build PmtTpInf element."""
        elements = []
        svc_lvl = ET.Element("SvcLvl")
        ET.SubElement(svc_lvl, "Cd").text = "SEPA"
        elements.append(svc_lvl)

        lcl_instrm = ET.Element("LclInstrm")
        ET.SubElement(lcl_instrm, "Cd").text = "INST"  # Instant if supported, else NORM
        elements.append(lcl_instrm)

        ctgy_purp = ET.Element("CtgyPurp")
        ET.SubElement(ctgy_purp, "Cd").text = batch.items[0].category_purpose or "SALA" if batch.items else "SALA"
        elements.append(ctgy_purp)

        return elements

    def _add_payment_item(self, parent: ET.Element, item: SepaPaymentItem, batch: SepaBatch):
        pmt_id = ET.SubElement(parent, "PmtId")
        ET.SubElement(pmt_id, "EndToEndId").text = item.end_to_end_id

        amt = ET.SubElement(parent, "Amt")
        instd_amt = ET.SubElement(amt, "InstdAmt", {"Ccy": item.currency})
        instd_amt.text = f"{item.amount:.2f}"

        if item.creditor_agent_bic:
            cdtr_agt = ET.SubElement(parent, "CdtrAgt")
            fin_instn = ET.SubElement(cdtr_agt, "FinInstnId")
            ET.SubElement(fin_instn, "BICFI").text = item.creditor_agent_bic

        cdtr = ET.SubElement(parent, "Cdtr")
        self._add_party_name(cdtr, item.creditor)
        if item.creditor.organisation_id or item.creditor.private_id:
            self._add_party_id(cdtr, item.creditor)

        cdtr_acct = ET.SubElement(parent, "CdtrAcct")
        cdtr_acct_id = ET.SubElement(cdtr_acct, "Id")
        ET.SubElement(cdtr_acct_id, "IBAN").text = item.creditor_account_iban or item.creditor.iban

        if item.purpose_code:
            purp = ET.SubElement(parent, "Purp")
            ET.SubElement(purp, "Cd").text = item.purpose_code

        if item.remittance_info:
            rmt_inf = ET.SubElement(parent, "RmtInf")
            ET.SubElement(rmt_inf, "Ustrd").text = item.remittance_info

        if item.requested_execution_date:
            reqd_exctn = ET.SubElement(parent, "ReqdExctnDt")
            ET.SubElement(reqd_exctn, "Dt").text = item.requested_execution_date.isoformat()

    def _add_party_name(self, parent: ET.Element, party: SepaParty):
        ET.SubElement(parent, "Nm").text = party.name[:70]  # Max 70 chars per ISO 20022
        if party.address_line1 or party.address_line2 or party.city or party.postal_code or party.country:
            pstl_adr = ET.SubElement(parent, "PstlAdr")
            if party.address_line1:
                ET.SubElement(pstl_adr, "AdrLine").text = party.address_line1[:70]
            if party.address_line2:
                ET.SubElement(pstl_adr, "AdrLine").text = party.address_line2[:70]
            if party.postal_code:
                ET.SubElement(pstl_adr, "PstCd").text = party.postal_code[:16]
            if party.city:
                ET.SubElement(pstl_adr, "TwnNm").text = party.city[:35]
            if party.country:
                ET.SubElement(pstl_adr, "Ctry").text = party.country

    def _add_party_id(self, parent: ET.Element, party: SepaParty):
        if party.organisation_id:
            id_elem = ET.SubElement(parent, "Id")
            org_id = ET.SubElement(id_elem, "OrgId")
            othr = ET.SubElement(org_id, "Othr")
            ET.SubElement(othr, "Id").text = party.organisation_id[:35]
        elif party.private_id:
            id_elem = ET.SubElement(parent, "Id")
            prvt_id = ET.SubElement(id_elem, "PrvtId")
            othr = ET.SubElement(prvt_id, "Othr")
            ET.SubElement(othr, "Id").text = party.private_id[:35]

    def _to_string(self, root: ET.Element, pretty: bool = True) -> str:
        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        if pretty:
            parsed = minidom.parseString(xml_bytes)
            return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        return xml_bytes.decode("utf-8")

    def sha256(self) -> str:
        """Compute SHA256 of the canonical XML (without pretty printing)."""
        xml = self.build(pretty=False)
        return hashlib.sha256(xml.encode("utf-8")).hexdigest()


# ── Convenience factory functions ────────────────────────────────────

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
) -> str:
    """Quick single-payment pain.001 generator."""
    initiating = SepaParty(
        name=initiating_party_name or debtor_name,
        iban=debtor_iban,
    )
    batch = SepaBatch(
        message_id=message_id,
        initiating_party=initiating,
        debtor=SepaParty(
            name=debtor_name,
            iban=debtor_iban,
            bic=debtor_bic,
            **(debtor_address or {}),
        ),
        debtor_account_iban=debtor_iban,
        debtor_agent_bic=debtor_bic,
        requested_execution_date=requested_execution_date,
        items=[
            SepaPaymentItem(
                end_to_end_id=end_to_end_id,
                amount=amount,
                currency=currency,
                creditor=SepaParty(
                    name=creditor_name,
                    iban=creditor_iban,
                    bic=creditor_bic,
                ),
                creditor_account_iban=creditor_iban,
                creditor_agent_bic=creditor_bic,
                remittance_info=remittance_info,
                purpose_code=purpose_code,
                category_purpose=purpose_code,
                requested_execution_date=requested_execution_date,
            )
        ],
    )
    return Pain001Builder().add_batch(batch).build()


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
) -> str:
    """Multi-item batch pain.001 generator."""
    batch = SepaBatch(
        message_id=message_id,
        initiating_party=initiating_party,
        debtor=debtor,
        debtor_account_iban=debtor_account_iban,
        debtor_agent_bic=debtor_agent_bic,
        requested_execution_date=requested_execution_date,
        items=items,
        batch_booking=batch_booking,
        charge_bearer=charge_bearer,
    )
    return Pain001Builder().add_batch(batch).build()


# ── Validation helpers ───────────────────────────────────────────────

def validate_iban(iban: str) -> bool:
    """Basic IBAN format validation (mod-97 check)."""
    iban = iban.replace(" ", "").upper()
    if len(iban) < 15 or len(iban) > 34:
        return False
    # Move first 4 chars to end
    rearranged = iban[4:] + iban[:4]
    # Convert letters to numbers (A=10, B=11, ...)
    numeric = ""
    for ch in rearranged:
        if ch.isalpha():
            numeric += str(ord(ch) - ord("A") + 10)
        else:
            numeric += ch
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def validate_bic(bic: str) -> bool:
    """Basic BIC format validation."""
    bic = bic.upper().replace(" ", "")
    return len(bic) in (8, 11) and bic[:6].isalpha() and bic[6:8].isalnum()


class SepaValidationError(ValueError):
    """Raised when SEPA data fails validation."""
    pass


def validate_batch(batch: SepaBatch) -> List[str]:
    """Validate a SEPA batch, return list of errors (empty if valid)."""
    errors = []
    if not batch.message_id:
        errors.append("Batch message_id is required")
    if not batch.debtor.name:
        errors.append("Debtor name is required")
    if not batch.debtor_account_iban:
        errors.append("Debtor IBAN is required")
    elif not validate_iban(batch.debtor_account_iban):
        errors.append(f"Invalid debtor IBAN: {batch.debtor_account_iban}")
    if batch.debtor_agent_bic and not validate_bic(batch.debtor_agent_bic):
        errors.append(f"Invalid debtor agent BIC: {batch.debtor_agent_bic}")

    for i, item in enumerate(batch.items):
        if not item.end_to_end_id:
            errors.append(f"Item {i}: end_to_end_id is required")
        if item.amount <= 0:
            errors.append(f"Item {i}: amount must be positive")
        if not item.creditor:
            errors.append(f"Item {i}: creditor is required")
        elif not item.creditor.name:
            errors.append(f"Item {i}: creditor name is required")
        # Check IBAN - either creditor_account_iban or creditor.iban must be provided
        creditor_iban = item.creditor_account_iban or (item.creditor.iban if item.creditor else None)
        if not creditor_iban:
            errors.append(f"Item {i}: creditor IBAN is required")
        elif not validate_iban(creditor_iban):
            errors.append(f"Item {i}: invalid creditor IBAN: {creditor_iban}")
        if item.creditor_agent_bic and not validate_bic(item.creditor_agent_bic):
            errors.append(f"Item {i}: invalid creditor agent BIC: {item.creditor_agent_bic}")

    return errors