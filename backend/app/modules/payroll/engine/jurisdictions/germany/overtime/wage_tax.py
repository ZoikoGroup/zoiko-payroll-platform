"""
engine/jurisdictions/germany/overtime/wage_tax.py
------------------------------------------------------------
Phase 8AF — Germany overtime/shift-premium WAGE-TAX (§3b EStG) calculation.

WAGE TAX ONLY. No social-insurance amount, no §1 SvEV treatment, no
SOCIAL_INSURANCE Grundlohn cap is ever read by this module (Phase 8AG's
job). No payslip line, no GermanyOvertimePremiumComponent, no snapshot
integration (Phase 8AH's job). Consumes — never mutates — Phase 8AE's
GermanyOvertimeTimeSegment rows and Phase 8AD's PUBLISHED registries.

── STATUTORY FACT vs. ENGINEERING DESIGN vs. UNRESOLVED QUESTION ─────────
See docs/PHASE_8AF_GERMANY_OVERTIME_WAGE_TAX_CALCULATION.md for the full
verification trail. Summary:

STATUTORY FACT (Gate 1 — fresh administrative-guidance verification this
phase, independent of Phase 8AE's own primary-text-only finding):

  Phase 8AE found no "Zusammentreffen" (concurrence) sentence in §3b
  EStG's own text. This phase went further and fetched the OFFICIAL BMF
  "Amtliches Lohnsteuer-Handbuch" (LStH 2025 edition — the 2026 edition's
  page is blocked by the same Radware bot-challenge this project has
  hit before on bundesfinanzministerium.de subdomains; the concurrence
  rule below is long-standing, stable administrative guidance, not an
  annually-changing rate, so the 2025 text is treated as current
  evidence for 2026, disclosed as such rather than silently assumed
  identical). R 3b (a BINDING Richtlinie, not a non-binding Hinweis) Abs.
  3 states, verbatim:

    "Wird an Sonntagen und Feiertagen oder in der zu diesen Tagen nach
    § 3b Abs. 3 Nr. 2 EStG gehörenden Zeit Nachtarbeit geleistet, kann
    die Steuerbefreiung nach § 3b Abs. 1 Nr. 2 bis 4 EStG neben der
    Steuerbefreiung nach § 3b Abs. 1 Nr. 1 EStG in Anspruch genommen
    werden. Dabei ist der steuerfreie Zuschlagssatz für Nachtarbeit mit
    dem steuerfreien Zuschlagssatz für Sonntags- oder Feiertagsarbeit
    auch dann zusammenzurechnen, wenn nur ein Zuschlag gezahlt wird."

  I.e.: when NIGHT work (§3b Abs. 1 Nr. 1) concurs with Sunday/holiday
  work (Nr. 2 to 4), the tax-free percentages are ADDED TOGETHER — even
  if the employer pays only one combined surcharge. This is
  `STATUTORY_CONCURRENCE_RULE_VERIFIED`, but ONLY for this exact pairing
  (one night category + one Sunday/holiday category).

  The fetched text does NOT address SUNDAY concurring with a HOLIDAY (no
  night involved) — it treats "Sonntags- oder Feiertagsarbeit" as one
  side of the night-combination rule, never states how a date that is
  BOTH Sunday AND a holiday resolves between the two Nr. 2/Nr. 3/Nr. 4
  rates. That combination, and any 3-way (night + Sunday + holiday)
  combination, is NOT covered by the verified text.

  Decision: `STATUTORY_CONCURRENCE_RULE_VERIFIED` for {one NIGHT_*} +
  {one of SUNDAY/HOLIDAY_STANDARD/HOLIDAY_SPECIAL} → SUM the two
  published percentages. `STATUTORY_CONCURRENCE_RULE_NOT_ESTABLISHED`
  for every other multi-category combination (Sunday+Holiday without
  night, or any 3-way) → FAIL CLOSED (`calculation_status =
  STATUTORY_RULE_UNRESOLVED`), never summed/maxed/first-picked.

ENGINEERING DESIGN (not statutory fact — disclosed, not hidden):

  §3b's own mechanism caps the Grundlohn used IN THE TAX-FREE
  CALCULATION at €50/hour ("ist... mit höchstens 50 Euro anzusetzen") —
  it does not cap what an employer actually pays. This codebase has NO
  field anywhere (Phase 8AB/8AC/8AE) recording an actual premium
  AMOUNT PAID — only hours worked. This module therefore computes:

    gross_qualifying_premium_amount = combined_pct × ACTUAL Grundlohn × hours
    tax_free_premium_amount         = combined_pct × CAPPED Grundlohn × hours
    taxable_premium_amount          = gross_qualifying_premium_amount − tax_free_premium_amount

  i.e. the statutory premium computed at the employee's real hourly
  Grundlohn is treated as the reference "gross qualifying" amount, and
  the €50 cap creates the taxable excess exactly where the employee's
  actual Grundlohn exceeds it (taxable = 0 whenever actual ≤ cap). This
  is the natural reading of the cap's own literal mechanism, not an
  invented formula — but it is NOT the same as knowing what an employer
  actually paid as a premium, which remains untracked anywhere in this
  codebase. A future phase reconciling this against a real paid amount
  (once one exists) is Phase 8AH's concern, not this one's.

  Rounding: no statutory rounding rule was found for this specific
  calculation. Reuses this codebase's own established convention
  (`germany_pap/core.py`'s `_r2`: `Decimal.quantize(Decimal("0.01"),
  ROUND_HALF_UP)`) — an engineering convention, not a statutory rule,
  applied once at the final output amounts only (not at intermediate
  steps, since no statutory intermediate-rounding point was found
  either).

UNRESOLVED QUESTIONS, explicitly not decided by this phase:
  - Sunday+Holiday (no night) and any 3-way concurrence — fails closed.
  - Whether the "gross qualifying premium at actual Grundlohn" design
    choice above should instead be reconciled against a real employer-
    paid premium amount once such a field exists.
"""

from dataclasses import dataclass
from datetime import date as date_cls
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from sqlalchemy.orm import Session

_NIGHT_CATEGORIES = {"NIGHT_STANDARD", "NIGHT_EXTENDED"}
_OTHER_CATEGORIES = {"SUNDAY", "HOLIDAY_STANDARD", "HOLIDAY_SPECIAL"}

_CALCULATED = "CALCULATED"
_NOT_CONFIGURED = "NOT_CONFIGURED"
_STATUTORY_RULE_UNRESOLVED = "STATUTORY_RULE_UNRESOLVED"
_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class GermanyOvertimeWageTaxError(Exception):
    """Base: this work record cannot safely be wage-tax calculated at
    all (structural precondition failure — e.g. never classified). A
    SEPARATE hierarchy from GermanyCalculationError (germany_pap/core.py)
    and from GermanyOvertimeClassificationError (germany_overtime_classifier.py)
    — this is neither the real PAP calculation path nor the classifier."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class GermanyOvertimeNotClassifiedError(GermanyOvertimeWageTaxError):
    def __init__(self, message: str):
        super().__init__("NOT_CLASSIFIED", message)


def _r2(value: Decimal) -> Decimal:
    """Established Zoiko engineering rounding convention (matches
    germany_pap/core.py's own `_r2`) — not a statutory rule. Applied
    only to final output amounts."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class _GroupResult:
    segment_start: object
    segment_end: object
    work_date_local: date_cls
    qualifying_hours: Decimal
    actual_grundlohn_hourly: Optional[Decimal] = None
    tax_grundlohn_hourly: Optional[Decimal] = None
    grundlohn_cap_rule_id: Optional[int] = None
    primary_category_code: Optional[str] = None
    primary_category_rule_id: Optional[int] = None
    concurrent_category_code: Optional[str] = None
    concurrent_category_rule_id: Optional[int] = None
    combined_tax_free_pct: Optional[Decimal] = None
    gross_qualifying_premium_amount: Optional[Decimal] = None
    tax_free_premium_amount: Optional[Decimal] = None
    taxable_premium_amount: Optional[Decimal] = None
    calculation_status: str = _NOT_CONFIGURED
    calculation_note: Optional[str] = None

    def as_dict(self) -> dict:
        return dict(
            segment_start=self.segment_start, segment_end=self.segment_end,
            work_date_local=self.work_date_local, qualifying_hours=self.qualifying_hours,
            actual_grundlohn_hourly=self.actual_grundlohn_hourly, tax_grundlohn_hourly=self.tax_grundlohn_hourly,
            grundlohn_cap_rule_id=self.grundlohn_cap_rule_id,
            primary_category_code=self.primary_category_code, primary_category_rule_id=self.primary_category_rule_id,
            concurrent_category_code=self.concurrent_category_code,
            concurrent_category_rule_id=self.concurrent_category_rule_id,
            combined_tax_free_pct=self.combined_tax_free_pct,
            gross_qualifying_premium_amount=self.gross_qualifying_premium_amount,
            tax_free_premium_amount=self.tax_free_premium_amount, taxable_premium_amount=self.taxable_premium_amount,
            calculation_status=self.calculation_status, calculation_note=self.calculation_note,
        )


def _group_segments_by_physical_range(segments: List) -> dict:
    """Groups GermanyOvertimeTimeSegment rows sharing the identical
    [segment_start, segment_end) — concurrent categories over the same
    physical time (Phase 8AE's own invariant) must be resolved TOGETHER,
    never as independent monetary lines (that would double-pay the same
    physical time)."""
    groups: dict = {}
    for seg in segments:
        key = (seg.segment_start, seg.segment_end)
        groups.setdefault(key, []).append(seg)
    return groups


def _calculate_one_group(db: Session, work_record, start, end, segs: List) -> _GroupResult:
    from app.modules.payroll import service

    work_date_local = segs[0].work_date_local
    hours = Decimal(segs[0].hours)
    categories = [s.premium_category for s in segs]

    result = _GroupResult(segment_start=start, segment_end=end, work_date_local=work_date_local, qualifying_hours=hours)

    # ── Resolve the employee's effective Grundlohn (Phase 8AB) ──────────
    profile = service.resolve_employee_statutory_profile(
        db, work_record.employee_id, work_record.organization_id, as_of=work_date_local,
    )
    if profile is None or profile.de_grundlohn_hourly is None:
        result.calculation_status = _INSUFFICIENT_DATA
        result.calculation_note = (
            "No effective EmployeeStatutoryProfile.de_grundlohn_hourly for this employee as of "
            f"{work_date_local} — never derived from salary/hours/any formula (Phase 8AB)."
        )
        return result
    actual_grundlohn = Decimal(profile.de_grundlohn_hourly)
    result.actual_grundlohn_hourly = actual_grundlohn

    # ── Resolve the PUBLISHED WAGE_TAX Grundlohn cap (Phase 8AD) ─────────
    cap_row = service.resolve_germany_overtime_grundlohn_cap(db, "WAGE_TAX", as_of=work_date_local)
    if cap_row is None:
        result.calculation_status = _NOT_CONFIGURED
        result.calculation_note = f"No PUBLISHED WAGE_TAX GermanyOvertimeGrundlohnCap as of {work_date_local}."
        return result
    result.grundlohn_cap_rule_id = cap_row.id
    tax_grundlohn = min(actual_grundlohn, Decimal(cap_row.hourly_cap_amount))
    result.tax_grundlohn_hourly = tax_grundlohn

    # ── Resolve category rate(s) — single category, or the ONE verified
    # concurrence combination (Gate 1: R 3b Abs. 3 LStH) ─────────────────
    night = [c for c in categories if c in _NIGHT_CATEGORIES]
    other = [c for c in categories if c in _OTHER_CATEGORIES]

    if len(categories) == 1:
        rule = service.resolve_germany_overtime_premium_category(db, categories[0], as_of=work_date_local)
        if rule is None:
            result.calculation_status = _NOT_CONFIGURED
            result.calculation_note = f"No PUBLISHED GermanyOvertimePremiumCategory for {categories[0]} as of {work_date_local}."
            return result
        result.primary_category_code = categories[0]
        result.primary_category_rule_id = rule.id
        result.combined_tax_free_pct = Decimal(rule.wage_tax_free_pct)
    elif len(night) == 1 and len(other) == 1 and len(categories) == 2:
        night_rule = service.resolve_germany_overtime_premium_category(db, night[0], as_of=work_date_local)
        other_rule = service.resolve_germany_overtime_premium_category(db, other[0], as_of=work_date_local)
        if night_rule is None or other_rule is None:
            result.calculation_status = _NOT_CONFIGURED
            missing = night[0] if night_rule is None else other[0]
            result.calculation_note = f"No PUBLISHED GermanyOvertimePremiumCategory for {missing} as of {work_date_local}."
            return result
        result.primary_category_code = night[0]
        result.primary_category_rule_id = night_rule.id
        result.concurrent_category_code = other[0]
        result.concurrent_category_rule_id = other_rule.id
        # STATUTORY_CONCURRENCE_RULE_VERIFIED (R 3b Abs. 3 Satz 2 LStH) —
        # summed, never max()'d or first-picked.
        result.combined_tax_free_pct = Decimal(night_rule.wage_tax_free_pct) + Decimal(other_rule.wage_tax_free_pct)
    else:
        # Sunday+Holiday (no night) or any 3-way — NOT covered by the
        # verified R 3b text. Fail closed; never invent a priority/sum/max.
        result.calculation_status = _STATUTORY_RULE_UNRESOLVED
        result.calculation_note = (
            f"Categories {sorted(categories)} concurrence is not established by verified administrative "
            "guidance (R 3b LStH only addresses night + one Sunday/holiday category) — "
            "STATUTORY_CONCURRENCE_RULE_NOT_ESTABLISHED for this combination."
        )
        return result

    # ── Compute (Decimal throughout; round only the final amounts) ──────
    pct_fraction = result.combined_tax_free_pct / Decimal(100)
    gross = pct_fraction * actual_grundlohn * hours
    tax_free = pct_fraction * tax_grundlohn * hours
    gross_rounded = _r2(gross)
    tax_free_rounded = _r2(tax_free)

    result.gross_qualifying_premium_amount = gross_rounded
    result.tax_free_premium_amount = tax_free_rounded
    result.taxable_premium_amount = gross_rounded - tax_free_rounded
    result.calculation_status = _CALCULATED
    return result


def calculate_wage_tax_groups(db: Session, work_record) -> List[_GroupResult]:
    """Pure calculation (no persistence) — one _GroupResult per distinct
    physical time range classified for this work record. Raises
    GermanyOvertimeNotClassifiedError if Phase 8AE classification has
    never been run (no GermanyOvertimeTimeSegment rows exist)."""
    from app.modules.payroll.models import GermanyOvertimeTimeSegment

    segments = (
        db.query(GermanyOvertimeTimeSegment)
        .filter(GermanyOvertimeTimeSegment.work_record_id == work_record.id)
        .order_by(GermanyOvertimeTimeSegment.segment_start)
        .all()
    )
    if not segments:
        raise GermanyOvertimeNotClassifiedError(
            "No GermanyOvertimeTimeSegment rows exist for this work record — run Phase 8AE classification first."
        )

    groups = _group_segments_by_physical_range(segments)
    return [
        _calculate_one_group(db, work_record, start, end, segs)
        for (start, end), segs in sorted(groups.items(), key=lambda kv: kv[0][0])
    ]


def calculate_germany_overtime_wage_tax(db: Session, work_record, persist: bool = True, actor_id=None) -> List:
    """Calculates and (if persist) replaces any existing
    GermanyOvertimeWageTaxResult rows for this work record with the
    freshly-computed set — same idempotent re-derivation pattern as
    Phase 8AE's classifier (nothing downstream is finalized yet; a
    future finalization phase, Phase 8AH, is responsible for freezing
    whatever it actually consumes)."""
    from app.modules.payroll.models import GermanyOvertimeWageTaxResult

    group_results = calculate_wage_tax_groups(db, work_record)

    if not persist:
        return group_results

    db.query(GermanyOvertimeWageTaxResult).filter(
        GermanyOvertimeWageTaxResult.work_record_id == work_record.id,
    ).delete()
    rows = []
    for gr in group_results:
        row = GermanyOvertimeWageTaxResult(
            organization_id=work_record.organization_id, work_record_id=work_record.id,
            created_by_id=actor_id, **gr.as_dict(),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows
