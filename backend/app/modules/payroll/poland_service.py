"""
modules/payroll/poland_service.py
---------------------------------
Poland statutory workflows (ZP-PL-ENG-001) — the ONLY Poland service module,
on the shared platform the same way south_africa_service.py and
new_zealand_service.py are.

Phase 1 scope: seeding the canonical PL-PAYROLL-2026 Draft pack from
engine/countries/poland_content.py, and the activation refusal that keeps a
pack carrying unsigned ([PENDING G1]) or empty content from ever becoming
Active. The platform hooks (calc_inputs, run preflight, retention, ...) arrive
with the service phase (P4) and are registered in jurisdiction_hooks._MODULES
only then — until that point nothing on the shared platform reaches this
module, and the seed script is the only caller.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

PL = "PL"
SPEC = "ZP-PL-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"
NOT_CONFIGURED = "NOT CONFIGURED"


def seed_poland_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                     status: str = "Draft") -> "JurisdictionPack":
    """Write poland_content.py into the PL-PAYROLL-2026 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S12), reused if present;
      * every scalar parameter (ContributionRate) with its value in the slot its
        kind names (employee/employer pct, flat_amount, text_value) and its own
        legal effective_from / effective_to where it has one; empty-by-design
        rows are written as NOT CONFIGURED and pending;
      * the PIT scale (TaxSlab rule_type="PL_PIT_BAND", published bases);
      * every earning-classification row (TaxSlab rule_type="PL_EARNING_CLASS",
        filing_status = component, tax_regime = obligation,
        assessment_basis = treatment).

    Draft only; a pack that has left Draft is never rewritten, and a Draft
    pack's canonical rows are replaced wholesale from the content (org-scoped
    rows are an organisation's overrides and are never touched)."""
    from app.modules.payroll.engine.countries import poland_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if status != "Draft":
        raise ValueError("seed_poland_pack only writes Draft content")
    pack_id, window_from, window_to = content.PL_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-PL-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency[:200]).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=PL, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "Ministry of Finance (KAS) / ZUS / PFR (PPK) / Ministry of Family, Labour and Social Policy"
    pack.source_document_id = sources["S3"]
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    def pending(label, flag, limit):
        return (label[:limit - len(PENDING_G1_SUFFIX)] + PENDING_G1_SUFFIX) if flag else label[:limit]

    order = 0
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to, _basis) in content.POLAND_SCALAR_CONTENT:
        order += 1
        ee_shown = f"{ee}%" if ee is not None else "—"
        er_shown = f"{er}%" if er is not None else "—"
        if ee is not None or er is not None:
            total = " / ".join(s for s in (ee_shown, er_shown) if s != "—")
        elif text is None and flat is None:
            total = NOT_CONFIGURED          # content.POLAND_EMPTY_BY_DESIGN
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=PL,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share=ee_shown[:50], employer_share=er_shown[:50], total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for (lo, hi, rate, base, label, src) in content.POLAND_PIT_BANDS:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=PL,
            rule_type=content.PL_PIT_BAND_RULE,
            min_amount=dec(lo), max_amount=dec(hi), rate_pct=dec(rate), flat_amount=dec(base),
            rate_label=f"{Decimal(rate).normalize():f}%"[:150], tax_formula=label[:150],
            source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.POLAND_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=PL,
            rule_type=content.PL_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=label[:150], tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    db.flush()
    return pack


def pl_pack_activation_refusal(db: Session, pack, actor_id: Optional[int] = None) -> Optional[str]:
    """Why a Polish pack must NOT be activated, or None.

    A pack is refused while ANY canonical row still carries the [PENDING G1]
    marker or is NOT CONFIGURED (spec §15 G1: NO-GO if any supported result
    relies on guessed or uncited content), or while a scalar row has no
    source document. Becomes the `pack_activation_refusal` hook in Phase 4;
    four-eyes approval is enforced separately by the shared approval lists."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if (getattr(pack, "jurisdiction_country", None) or "").upper() != PL:
        return None
    rates = (db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                     ContributionRate.organization_id.is_(None)).all())
    if not rates:
        return "Poland pack has no statutory content — seed it from poland_content.py first."
    unsigned = sorted(r.component_key for r in rates
                      if (r.label or "").endswith(PENDING_G1_SUFFIX.strip()) or r.total == NOT_CONFIGURED
                      or (r.text_value or "") == "PENDING_G1")
    if unsigned:
        shown = ", ".join(unsigned[:8]) + (f" (+{len(unsigned) - 8} more)" if len(unsigned) > 8 else "")
        return (f"Poland pack {pack.pack_id} still has {len(unsigned)} unsigned or unconfigured row(s): "
                f"{shown}. Gate G1 must sign them before activation (ZP-PL-ENG-001 §15).")
    unsourced = sorted(r.component_key for r in rates if r.source_document_id is None)
    if unsourced:
        return f"Poland pack {pack.pack_id} has rows without a source document: {', '.join(unsourced[:8])}."
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    if not any(s.rule_type == "PL_PIT_BAND" for s in slabs):
        return f"Poland pack {pack.pack_id} has no PIT scale."
    return None
