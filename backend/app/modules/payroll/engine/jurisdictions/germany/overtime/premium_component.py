"""
engine/jurisdictions/germany/overtime/premium_component.py
------------------------------------------------------------
Phase 8AH — Germany overtime PREMIUM COMPONENT: combines the two already
-independently-calculated GermanyOvertimeWageTaxResult (Phase 8AF) and
GermanyOvertimeSocialInsuranceResult (Phase 8AG) rows for the same
physical time range into a single presentable, four-dimension output
unit.

This module performs NO statutory interpretation and NO calculation of
its own — it only reads the two existing, already-verified result tables
and joins them by (work_record_id, segment_start, segment_end), exactly
the grouping key both Phase 8AF and Phase 8AG already use internally
(see germany_overtime_social_insurance.py's own `_group_segments_by_physical_range`).

── STATUTORY FACT vs. ENGINEERING DESIGN vs. UNRESOLVED QUESTION ─────────
No new statutory fact is asserted here (Phase 8AH §24 — reuse, don't
re-interpret).

ENGINEERING DESIGN (disclosed):
  - Both Phase 8AF and Phase 8AG independently compute
    gross_qualifying_premium_amount from the SAME underlying facts
    (GermanyOvertimeTimeSegment + GermanyOvertimePremiumCategory +
    EmployeeStatutoryProfile.de_grundlohn_hourly), so they MUST agree.
    If they disagree beyond a one-cent rounding tolerance, that is a
    genuine defect in one of the two calculation paths, not a value
    judgement this module is entitled to resolve — combination_status
    becomes AMOUNT_MISMATCH and gross_premium_amount is left NULL
    (fail closed, never averaged/preferred/guessed).
  - A component is buildable for a physical range as soon as EITHER
    dimension has a CALCULATED result — the other dimension's absence
    or failure is preserved, never inferred from the one that
    succeeded (Phase 8AH §8: never assume tax-free implies SI-free, and
    symmetrically never assume one dimension's success implies the
    other's).

UNRESOLVED QUESTIONS, explicitly not decided by this module (see
service.py's attach function and its own docstring for how these are
handled downstream, and docs/PHASE_8AH_..._REPORT.md for the full
reasoning):
  - Whether a component may be attached to a real payslip line is NOT
    decided here — this module only builds/combines; attachment is a
    separate, explicit service-layer action.
"""

from dataclasses import dataclass
from datetime import date as date_cls
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

_COMPLETE = "COMPLETE"
_PARTIAL_WAGE_TAX_ONLY = "PARTIAL_WAGE_TAX_ONLY"
_PARTIAL_SI_ONLY = "PARTIAL_SOCIAL_INSURANCE_ONLY"
_AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
_NONE_STATUS = "NONE"

_CALCULATED = "CALCULATED"

# Reconciliation tolerance between the two independently-computed gross
# figures — one cent, matching each path's own final-rounding precision
# (_r2 in both germany_overtime_wage_tax.py and
# germany_overtime_social_insurance.py). Not a statutory value.
_RECONCILIATION_TOLERANCE = Decimal("0.01")


class GermanyOvertimePremiumComponentError(Exception):
    """Base — a SEPARATE hierarchy from every other overtime engine
    module's own error hierarchy (Phase 8AE/8AF/8AG each keep their own)."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class GermanyOvertimePremiumComponentNoResultsError(GermanyOvertimePremiumComponentError):
    def __init__(self, message: str):
        super().__init__("NO_RESULTS", message)


@dataclass
class _PremiumComponentGroup:
    segment_start: object
    segment_end: object
    work_date_local: date_cls
    qualifying_hours: Decimal
    wage_tax_result_id: Optional[int] = None
    social_insurance_result_id: Optional[int] = None
    combination_status: str = _NONE_STATUS
    calculation_note: Optional[str] = None
    gross_premium_amount: Optional[Decimal] = None
    wage_tax_free_amount: Optional[Decimal] = None
    wage_taxable_amount: Optional[Decimal] = None
    si_exempt_amount: Optional[Decimal] = None
    si_contributory_amount: Optional[Decimal] = None

    def as_dict(self) -> dict:
        return dict(
            segment_start=self.segment_start, segment_end=self.segment_end,
            work_date_local=self.work_date_local, qualifying_hours=self.qualifying_hours,
            wage_tax_result_id=self.wage_tax_result_id,
            social_insurance_result_id=self.social_insurance_result_id,
            combination_status=self.combination_status, calculation_note=self.calculation_note,
            gross_premium_amount=self.gross_premium_amount,
            wage_tax_free_amount=self.wage_tax_free_amount, wage_taxable_amount=self.wage_taxable_amount,
            si_exempt_amount=self.si_exempt_amount, si_contributory_amount=self.si_contributory_amount,
        )


def _combine_one(wt_row, si_row) -> _PremiumComponentGroup:
    anchor = wt_row or si_row
    group = _PremiumComponentGroup(
        segment_start=anchor.segment_start, segment_end=anchor.segment_end,
        work_date_local=anchor.work_date_local, qualifying_hours=Decimal(anchor.qualifying_hours),
        wage_tax_result_id=wt_row.id if wt_row else None,
        social_insurance_result_id=si_row.id if si_row else None,
    )

    wt_ok = bool(wt_row and wt_row.calculation_status == _CALCULATED)
    si_ok = bool(si_row and si_row.calculation_status == _CALCULATED)

    if wt_ok:
        group.wage_tax_free_amount = Decimal(wt_row.tax_free_premium_amount)
        group.wage_taxable_amount = Decimal(wt_row.taxable_premium_amount)
    if si_ok:
        group.si_exempt_amount = Decimal(si_row.si_free_premium_amount)
        group.si_contributory_amount = Decimal(si_row.si_contributory_premium_amount)

    if wt_ok and si_ok:
        wt_gross = Decimal(wt_row.gross_qualifying_premium_amount)
        si_gross = Decimal(si_row.gross_qualifying_premium_amount)
        if abs(wt_gross - si_gross) > _RECONCILIATION_TOLERANCE:
            group.combination_status = _AMOUNT_MISMATCH
            group.calculation_note = (
                f"Wage-tax path gross ({wt_gross}) and social-insurance path gross ({si_gross}) "
                "disagree beyond the one-cent reconciliation tolerance — both paths read the same "
                "underlying facts and must agree; this indicates a defect in one of the two "
                "calculation paths, not resolved here (fail closed, no amount guessed)."
            )
        else:
            group.combination_status = _COMPLETE
            group.gross_premium_amount = wt_gross
    elif wt_ok:
        group.combination_status = _PARTIAL_WAGE_TAX_ONLY
        group.gross_premium_amount = Decimal(wt_row.gross_qualifying_premium_amount)
        group.calculation_note = (
            "Social-insurance result is absent or not CALCULATED for this physical range "
            f"(status={si_row.calculation_status if si_row else 'NO_ROW'}) — only the wage-tax "
            "dimension is populated."
        )
    elif si_ok:
        group.combination_status = _PARTIAL_SI_ONLY
        group.gross_premium_amount = Decimal(si_row.gross_qualifying_premium_amount)
        group.calculation_note = (
            "Wage-tax result is absent or not CALCULATED for this physical range "
            f"(status={wt_row.calculation_status if wt_row else 'NO_ROW'}) — only the "
            "social-insurance dimension is populated."
        )
    else:
        group.combination_status = _NONE_STATUS
        group.calculation_note = (
            f"Neither dimension is CALCULATED for this physical range (wage-tax="
            f"{wt_row.calculation_status if wt_row else 'NO_ROW'}, social-insurance="
            f"{si_row.calculation_status if si_row else 'NO_ROW'})."
        )
    return group


def build_premium_component_groups(db: Session, work_record) -> List[_PremiumComponentGroup]:
    """Pure combination (no persistence). Raises
    GermanyOvertimePremiumComponentNoResultsError if NEITHER Phase 8AF nor
    Phase 8AG has ever been calculated for this work record."""
    from app.modules.payroll.models import GermanyOvertimeWageTaxResult, GermanyOvertimeSocialInsuranceResult

    wt_rows = (
        db.query(GermanyOvertimeWageTaxResult)
        .filter(GermanyOvertimeWageTaxResult.work_record_id == work_record.id)
        .all()
    )
    si_rows = (
        db.query(GermanyOvertimeSocialInsuranceResult)
        .filter(GermanyOvertimeSocialInsuranceResult.work_record_id == work_record.id)
        .all()
    )
    if not wt_rows and not si_rows:
        raise GermanyOvertimePremiumComponentNoResultsError(
            "No GermanyOvertimeWageTaxResult or GermanyOvertimeSocialInsuranceResult rows exist for "
            "this work record — run Phase 8AF and/or Phase 8AG calculation first."
        )

    wt_by_range = {(r.segment_start, r.segment_end): r for r in wt_rows}
    si_by_range = {(r.segment_start, r.segment_end): r for r in si_rows}
    all_ranges = sorted(set(wt_by_range) | set(si_by_range), key=lambda k: k[0])

    return [
        _combine_one(wt_by_range.get(rng), si_by_range.get(rng))
        for rng in all_ranges
    ]
