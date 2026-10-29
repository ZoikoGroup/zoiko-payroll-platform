"""
modules/payroll/japan_service.py
--------------------------------
Japan statutory workflows (ZP-JP-ENG-001) — the ONLY Japan service module, on
the shared platform the same way south_africa_service.py is.

Scope (Phase 1): seeding the canonical JP-PAYROLL-2026 Draft pack from
engine/countries/japan_content.py. The Japan tables, calc inputs and platform
hooks (calc_inputs, run preflight, pack activation refusal, retention,
service-registry transition, …) arrive with Phases 2 and 5 and are registered
in jurisdiction_hooks._MODULES only then — registering a module that lacks a
hook the platform calls would make every Japan code path raise (fail-closed).
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

JP = "JP"
SPEC = "ZP-JP-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"


def seed_japan_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                    status: str = "Draft") -> "JurisdictionPack":
    """Write japan_content.py into the JP-PAYROLL-2026 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S17), reused if present;
      * every scalar parameter (ContributionRate) with its real value in the
        slot its kind names (employee/employer pct, flat_amount, text_value)
        and its own legal effective_from / effective_to where it has one;
      * every earning-classification row (TaxSlab rule_type="JP_EARNING_CLASS",
        filing_status = component, tax_regime = obligation,
        assessment_basis = treatment).
    The authority tables the specification does not reproduce
    (content.JP_EMPTY_TABLES) write no rows: they are filled from archived
    artefacts at G1/G3/G4, and until then the engine BLOCKS.

    Draft by default; a pack that has left Draft is never rewritten, and a
    Draft pack's canonical rows are replaced wholesale from the content."""
    from app.modules.payroll.engine.countries import japan_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if status != "Draft":
        raise ValueError("seed_japan_pack only writes Draft content")
    pack_id, window_from, window_to = content.JP_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-JP-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=JP, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "NTA / Japan Pension Service / MHLW / Municipalities"
    pack.source_document_id = sources["S1"]
    # Canonical rows only: org-scoped rows (organization_id IS NOT NULL) are an
    # organisation's overrides and are never deleted by a re-seed.
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    def pending(label, flag, limit):
        return (label + (PENDING_G1_SUFFIX if flag else ""))[:limit]

    order = 0
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to) in content.JP_SCALAR_CONTENT:
        order += 1
        ee_shown = f"{ee}%" if ee is not None else "—"
        er_shown = f"{er}%" if er is not None else "—"
        if ee is not None or er is not None:
            total = " / ".join(s for s in (ee_shown, er_shown) if s != "—")
        elif text is None and flat is None:
            # Empty by design (content.JP_EMPTY_BY_DESIGN): the specification gives
            # no value, so the row exists only to make "not configured" explicit.
            total = "NOT CONFIGURED"
        elif content.JP_PARAMETER_KEYS[key] == "pct_total":
            total = f"{flat}% total"
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=JP,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share=ee_shown[:50], employer_share=er_shown[:50], total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.JP_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=JP,
            rule_type=content.JP_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=pending(label, True, 150), tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    db.flush()
    return pack


# ── shared validation helpers ───────────────────────────────────────────────
def _as_date(value, field: str):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


def _money(value, field: str):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal amount.")
