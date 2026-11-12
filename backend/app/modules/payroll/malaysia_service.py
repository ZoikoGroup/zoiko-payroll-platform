"""
modules/payroll/malaysia_service.py
-----------------------------------
Malaysia statutory workflows (ZP-MY-ENG-001) — the ONLY Malaysia service
module, on the shared platform the same way poland_service.py is.

Phase 1 (this section): seeding the canonical MY-PAYROLL-2026 Draft pack
from engine/countries/malaysia_content.py, the activation refusal that keeps
a pack carrying any unsigned, unconfigured or empty content from ever
becoming Active, and Malaysia's PLANNED service-registry row.

Every seeded row is UNSIGNED ("[PENDING G1]"): a value taken from a document
— even the specification — is "extracted", not verified. Rows become usable
only when signed through my_super_admin (source stored, hashed and reviewed
by a second Super Admin).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

MY = "MY"
SPEC = "ZP-MY-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"
NOT_CONFIGURED = "NOT CONFIGURED"


def _content():
    from app.modules.payroll.engine.countries import malaysia_content as content

    return content


def pending_label(label: str, limit: int) -> str:
    """An UNSIGNED label: the [PENDING G1] marker always fits."""
    return label[:limit - len(PENDING_G1_SUFFIX)] + PENDING_G1_SUFFIX


def rate_total(ee, er, flat, text) -> str:
    """The display `total` of a ContributionRate row."""
    if ee is not None or er is not None:
        return " / ".join(f"{v}%" for v in (ee, er) if v is not None)[:50]
    if text is None and flat is None:
        return NOT_CONFIGURED
    return str(text if text is not None else flat)[:50]


def seed_sources(db: Session) -> dict:
    """One SourceArtifact per evidence-register entry (S1–S15), reused if present.
    Seeded artifacts carry no file: they are references, not archived evidence."""
    from app.modules.payroll.models import SourceArtifact

    content = _content()
    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-MY-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency[:200]).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id
    return sources


def seed_malaysia_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                       status: str = "Draft") -> "JurisdictionPack":
    """Write malaysia_content.py into the MY-PAYROLL-2026 tax pack:
      * every scalar parameter (ContributionRate) in the slot its kind names,
        with its own legal effective dates where it has one, territorial rows
        carrying jurisdiction_state = territory;
      * every earning-classification row (TaxSlab rule_type="MY_EARNING_CLASS");
      * NO schedule, holiday or PCB-table rows — those come from the official
        documents through the workbook.
    Every row is written UNSIGNED. Draft only; a pack that has left Draft is
    never rewritten, and a Draft pack's canonical rows are replaced wholesale
    (organisation-scoped rows are never touched)."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    content = _content()
    if status != "Draft":
        raise ValueError("seed_malaysia_pack only writes Draft content")
    pack_id, window_from, window_to = content.MY_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")
    sources = seed_sources(db)

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=MY, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "HASiL / KWSP (EPF) / PERKESO / HRD Corp / MOHR (JTK Peninsular, Sabah, Sarawak)"
    pack.source_document_id = sources["S1"]
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    order = 0
    for (key, label, ee, er, flat, text, src, _spec, eff_from, eff_to, _basis, territory) \
            in content.MALAYSIA_SCALAR_CONTENT:
        order += 1
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=MY,
            jurisdiction_state=territory, component_key=key, label=pending_label(label, 100),
            employee_share=(f"{ee}%" if ee is not None else "—")[:50],
            employer_share=(f"{er}%" if er is not None else "—")[:50],
            total=rate_total(ee, er, flat, text),
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er), flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to, source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.MALAYSIA_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=MY,
            rule_type=content.MY_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=pending_label(label, 150), tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))
    db.flush()
    return pack


def my_pack_activation_refusal(db: Session, pack, actor_id: Optional[int] = None) -> Optional[str]:
    """Why a Malaysian pack must NOT be activated, or None.

    Refused while ANY canonical row is unsigned ([PENDING G1]), NOT
    CONFIGURED or PENDING_G1, while a row has no source document, or while a
    required table (EPF / PERKESO / EIS / foreign-worker schedules, public
    holidays) holds no rows (spec §16 G1: NO-GO if a supported result relies
    on guessed or uncited content; MY-005 schedules are legal content)."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if (getattr(pack, "jurisdiction_country", None) or "").upper() != MY:
        return None
    content = _content()
    marker = PENDING_G1_SUFFIX.strip()
    rates = (db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                     ContributionRate.organization_id.is_(None)).all())
    if not rates:
        return "Malaysia pack has no statutory content — seed it from malaysia_content.py first."
    unsigned = sorted(r.component_key for r in rates
                      if marker in (r.label or "") or r.total == NOT_CONFIGURED
                      or (r.text_value or "") == content.PENDING)
    if unsigned:
        shown = ", ".join(unsigned[:8]) + (f" (+{len(unsigned) - 8} more)" if len(unsigned) > 8 else "")
        return (f"Malaysia pack {pack.pack_id} still has {len(unsigned)} unsigned or unconfigured row(s): "
                f"{shown}. Gate G1 must sign them before activation (ZP-MY-ENG-001 §16).")
    unsourced = sorted(r.component_key for r in rates if r.source_document_id is None)
    if unsourced:
        return f"Malaysia pack {pack.pack_id} has rows without a source document: {', '.join(unsourced[:8])}."
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    unsigned_slabs = [s for s in slabs if marker in (s.rate_label or "")]
    if unsigned_slabs:
        kinds = sorted({s.rule_type for s in unsigned_slabs})
        return (f"Malaysia pack {pack.pack_id} still has {len(unsigned_slabs)} unsigned table row(s) "
                f"({', '.join(kinds)}).")
    present = {s.rule_type for s in slabs}
    missing = [rule for rule in content.REQUIRED_TABLES if rule not in present]
    if missing:
        return (f"Malaysia pack {pack.pack_id} has no rows for: {', '.join(missing)} — load them from the "
                "official schedules (MY-005).")
    return None


def ensure_my_service_registry_row(db: Session) -> str:
    """Malaysia's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == MY).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=MY, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"
