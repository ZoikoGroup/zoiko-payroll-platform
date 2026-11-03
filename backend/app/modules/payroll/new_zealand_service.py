"""
modules/payroll/new_zealand_service.py
--------------------------------------
New Zealand statutory workflows (ZP-NZ-ENG-001) — the ONLY New Zealand service
module, on the shared platform the same way japan_service.py is.

Scope (Phase 1): seeding the canonical NZ-PAYROLL-2026-27 Draft pack (and the
empty NZ-ELA-2028 staging pack) from engine/countries/new_zealand_content.py,
and the pack activation refusal. The New Zealand tables, calc inputs and
platform hooks arrive with Phases 2 and 4 and are registered in
jurisdiction_hooks._MODULES only then — registering a module that lacks a
hook the platform calls would make every New Zealand code path raise
(fail-closed).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

NZ = "NZ"
SPEC = "ZP-NZ-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"


def _ensure_sources(db: Session, content) -> dict:
    from app.modules.payroll.models import SourceArtifact

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-NZ-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id
    return sources


def _draft_pack(db: Session, pack_id: str, window_from: date, window_to: Optional[date]):
    from app.modules.payroll.models import JurisdictionPack

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")
    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=NZ, pack_type="tax",
                                effective_from=window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_from = window_from
    pack.effective_to = window_to
    return pack


def seed_nz_pack(db: Session, *, status: str = "Draft") -> "JurisdictionPack":
    """Write new_zealand_content.py into the NZ-PAYROLL-2026-27 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S10), reused if present;
      * every scalar parameter (ContributionRate) with its value in the slot
        its kind names and its own legal effective_from / effective_to;
      * the PAYE and ESCT bands (TaxSlab NZ_PAYE_BAND / NZ_ESCT_BAND);
      * the tax-code catalogue (TaxSlab NZ_TAX_CODE);
      * every earning-classification row (TaxSlab NZ_EARNING_CLASS).
    The authority tables the specification does not reproduce
    (content.NZ_EMPTY_TABLES) write no rows: they are filled from archived
    artefacts at their gate, and until then the engine BLOCKS. Every row is
    labelled PENDING G1.

    Also writes the Employment Leave Act 2026 staging pack NZ-ELA-2028 as an
    EMPTY Draft (spec §8, AC-NZ-08); nz_pack_activation_refusal keeps it
    from ever being activated before 6 August 2028.

    Draft only; a pack that has left Draft is never rewritten, and a Draft
    pack's canonical rows are replaced wholesale from the content."""
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if status != "Draft":
        raise ValueError("seed_nz_pack only writes Draft content")
    pack_id, window_from, window_to = content.NZ_2026_27
    pack = _draft_pack(db, pack_id, window_from, window_to)
    sources = _ensure_sources(db, content)
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "Inland Revenue / Employment New Zealand / ACC"
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
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to) in content.NZ_SCALAR_CONTENT:
        order += 1
        if text is None and flat is None:
            # Empty by design (content.NZ_EMPTY_BY_DESIGN): the specification gives
            # no value, so the row exists only to make "not configured" explicit.
            total = "NOT CONFIGURED"
        elif content.NZ_PARAMETER_KEYS[key] == "pct_total":
            total = f"{flat}%"
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share="—", employer_share="—", total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for rule_type, bands, src, what in ((content.NZ_PAYE_BAND_RULE, content.NZ_PAYE_BANDS, "S3", "PAYE band"),
                                        (content.NZ_ESCT_BAND_RULE, content.NZ_ESCT_BANDS, "S3", "ESCT band")):
        for low, high, rate in bands:
            order += 1
            span = f"over {low}" + (f" to {high}" if high is not None else "")
            db.add(TaxSlab(
                jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
                rule_type=rule_type, min_amount=dec(low), max_amount=dec(high), rate_pct=dec(rate),
                rate_label=pending(f"{what} {span}: {rate}%", True, 150), tax_formula=f"{what} {span}"[:150],
                effective_from=window_from, effective_to=window_to,
                source_document_id=sources.get(src), sort_order=order))

    for code, income_class, code_status, student_loan, ietc, label in content.NZ_TAX_CODES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
            rule_type=content.NZ_TAX_CODE_RULE, min_amount=Decimal("0"), max_amount=None,
            rate_pct=Decimal("0"), rate_label=pending(f"{code}: {label}", True, 150),
            tax_formula=f"{code} {income_class} {code_status}"[:150],
            filing_status=code, tax_regime=income_class, assessment_basis=code_status,
            tax_column="SL" if student_loan else None, tax_table_number="IETC" if ietc else None,
            source_document_id=sources.get("S1"), sort_order=order))

    for (obligation, treatment, component, label, src) in content.NZ_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
            rule_type=content.NZ_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=pending(label, True, 150), tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    ela_id, ela_from, ela_to = content.NZ_ELA_2028
    ela = _draft_pack(db, ela_id, ela_from, ela_to)
    ela.regulatory_authority = "Employment New Zealand"
    ela.source_document_id = sources["S8"]
    ela.change_summary = ("Employment Leave Act 2026 staging pack — empty; cannot be activated before "
                          f"{content.ELA_EARLIEST_EFFECTIVE.isoformat()} (ZP-NZ-ENG-001 §8, AC-NZ-08).")
    db.flush()
    return pack


# ── shared validation helpers ───────────────────────────────────────────────
def nz_pack_activation_refusal(db: Session, pack, actor_id: Optional[int] = None,
                               today: Optional[date] = None) -> Optional[str]:
    """Why a New Zealand pack may not be activated, or None.

    * NZ-ELA-2028 (Employment Leave Act 2026): never before 6 August 2028
      (AC-NZ-08), and never while it holds no signed content.
    * Any NZ pack: refused while a canonical row is still PENDING G1, or while
      an authority table the engine needs (content.NZ_EMPTY_TABLES) has no
      rows (gate G1/G2)."""
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if pack is None or (pack.jurisdiction_country or "").upper() != NZ:
        return None
    today = today or date.today()
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.organization_id.is_(None))
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                     TaxSlab.organization_id.is_(None))
    ela_id, _from, _to = content.NZ_ELA_2028
    if pack.pack_id == ela_id:
        if today < content.ELA_EARLIEST_EFFECTIVE:
            return (f"{ela_id} (Employment Leave Act 2026) cannot be activated before "
                    f"{content.ELA_EARLIEST_EFFECTIVE.isoformat()}; the Holidays Act 2003 stays in force until then")
        if not rates.count() and not slabs.count():
            return f"{ela_id} holds no signed content and cannot be activated"
    marker = f"%{PENDING_G1_SUFFIX.strip()}%"
    pending_rows = (rates.filter(ContributionRate.label.like(marker)).count()
                    + slabs.filter(TaxSlab.rate_label.like(marker)).count())
    if pending_rows:
        return (f"{pending_rows} New Zealand pack row(s) are still PENDING G1 - "
                "they must be signed at gate G1 before the pack can be activated")
    if pack.pack_id != ela_id:
        missing = [name for name, table in content.NZ_EMPTY_TABLES.items()
                   if not table.get("employer_content")
                   and not slabs.filter(TaxSlab.rule_type == table["rule_type"]).count()]
        if missing:
            return ("New Zealand authority tables are empty: " + ", ".join(sorted(missing))
                    + " — they are filled from archived authority evidence at their release gate")
    return None
