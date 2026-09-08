"""
engine/germany_overtime_social_insurance.py
------------------------------------------------------------
Phase 8AG — Germany overtime/shift-premium SOCIAL-INSURANCE (§1 SvEV)
calculation.

SOCIAL INSURANCE ONLY. Completely independent of Phase 8AF's wage-tax
path — this module never reads GermanyOvertimeWageTaxResult, never reads
the WAGE_TAX Grundlohn cap dimension, and never assumes tax-free implies
SI-free. No payslip line, no GermanyOvertimePremiumComponent, no
engine/countries/germany.py wiring, no ctx.overtime activation (all
explicitly deferred to Phase 8AH — see this phase's own report for the
reasoning on why full engine/payslip integration stays out of scope here,
consistent with every prior overtime phase's stated boundary).

── STATUTORY FACT vs. ENGINEERING DESIGN vs. UNRESOLVED QUESTION ─────────
See docs/PHASE_8AG_GERMANY_OVERTIME_SOCIAL_INSURANCE_TREATMENT_REPORT.md
for the full verification trail. Summary:

STATUTORY FACT (Gate 1 — fresh, independent of Phase 8Z's earlier
citation of the same provision):

  §1 Absatz (1) Satz 1 Nummer 1 SvEV (Sozialversicherungsentgeltverordnung),
  fetched directly from gesetze-im-internet.de this phase:

    "einmalige Einnahmen, laufende Zulagen, Zuschläge, Zuschüsse sowie
    ähnliche Einnahmen, die zusätzlich zu Löhnen oder Gehältern gewährt
    werden, soweit sie lohnsteuerfrei sind; dies gilt nicht für Sonntags-,
    Feiertags- und Nachtarbeitszuschläge, soweit das Entgelt, auf dem sie
    berechnet werden, mehr als 25 Euro für jede Stunde beträgt"

  I.e.: SFN-Zuschläge are contribution-free UNLESS the Grundlohn they are
  computed on exceeds €25/hour — and "soweit" (insofar as / to the
  extent that) is the same proportional-basis-cap language pattern as
  §3b EStG's own "höchstens... anzusetzen" (at most... to be applied),
  not a binary cliff. This module therefore mirrors Phase 8AF's exact
  capped-basis mechanic, independently, with €25 instead of €50.

  §1 Absatz (2) SvEV (the genuinely new finding this phase, not
  previously surfaced in this project): "In der gesetzlichen
  Unfallversicherung und in der Seefahrt sind auch lohnsteuerfreie
  Zuschläge für Sonntags-, Feiertags- und Nachtarbeit dem Arbeitsentgelt
  zuzurechnen" — i.e. in statutory ACCIDENT INSURANCE (Unfallversicherung)
  and maritime employment, these surcharges are FULLY contribution-liable
  regardless of the €25 cap. This EXPLICITLY calls out Unfallversicherung
  as the ONE branch treated differently — by contrast, GKV/PV/RV/ALV
  (the branches this module actually calculates) are NOT differentiated
  from one another anywhere in the text. `applicable_si_branches =
  "GKV_PV_RV_ALV"` on every result row reflects this verified finding,
  not an assumption. Unfallversicherung itself is OUT OF SCOPE for this
  module (handled by the existing, unrelated `EmployerTaxProfile`
  mechanism — Phase 8M/8U — untouched by this phase).

  §1 SvEV is SILENT on concurrence — no "zusammenzurechnen" language
  exists anywhere in the regulation, and it does not incorporate §3b
  EStG's own R 3b combination rule by reference.

ENGINEERING DESIGN (not statutory fact — disclosed, not hidden):

  Since §1 SvEV's own "Zuschläge" concept is the SAME surcharge §3b EStG
  defines (SvEV does not define its own separate percentage scheme), and
  Phase 8AF's verified combination rule (R 3b Abs. 3 LStH: night +
  Sunday/holiday percentages summed) determines the SIZE of that
  surcharge, this module REUSES the identical concurrence resolution
  (same one verified pairing; every other combination fails closed) for
  the SI side — this is an inference from §1 SvEV referencing the same
  underlying "Zuschlag" concept, NOT a separately SI-verified
  administrative rule. Disclosed as such, not presented as an
  independently-confirmed SI-side finding.

  gross_qualifying_premium_amount is computed independently here (same
  formula as Phase 8AF: combined_pct × ACTUAL Grundlohn × hours) rather
  than read from GermanyOvertimeWageTaxResult — deliberately, to keep the
  two calculation paths with zero code-level dependency on each other,
  per this phase's own "completely separate" instruction. Both paths
  necessarily arrive at the same gross figure because they read the same
  underlying facts (GermanyOvertimeTimeSegment + GermanyOvertimePremiumCategory
  + EmployeeStatutoryProfile.de_grundlohn_hourly), not because one reuses
  the other's output.

  Rounding: reuses the same Zoiko engineering convention as Phase 8AF
  (`_r2`: `Decimal.quantize(Decimal("0.01"), ROUND_HALF_UP)`), applied
  once at the final output amounts.

UNRESOLVED QUESTIONS, explicitly not decided by this phase:
  - Whether §1 SvEV's "soweit" is genuinely a capped-basis mechanic
    (this module's assumption, mirroring §3b's own analogous language) or
    a binary cliff — no explicit numeric example was found in the fetched
    text to disambiguate this definitively; flagged for future dedicated
    verification (administrative commentary/case law), not invented past
    what was read.
  - Whether the concurrence-summing inference above (borrowed from the
    wage-tax side) is itself SI-verified anywhere in GKV-Spitzenverband
    or other SI-administrative guidance — not searched this phase.
  - Sunday+Holiday (no night) and 3-way concurrence — inherits Phase
    8AF's own unresolved status; fails closed here too.
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

_APPLICABLE_SI_BRANCHES = "GKV_PV_RV_ALV"  # verified — see module docstring, §1 Abs. 2 SvEV contrast


class GermanyOvertimeSocialInsuranceError(Exception):
    """Base — a SEPARATE hierarchy from GermanyOvertimeWageTaxError
    (Phase 8AF), GermanyOvertimeClassificationError (Phase 8AE), and
    GermanyCalculationError (germany_pap/core.py). This is neither the
    wage-tax path, the classifier, nor the real PAP calculation path."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class GermanyOvertimeSINotClassifiedError(GermanyOvertimeSocialInsuranceError):
    def __init__(self, message: str):
        super().__init__("NOT_CLASSIFIED", message)


def _r2(value: Decimal) -> Decimal:
    """Established Zoiko engineering rounding convention (matches
    germany_pap/core.py's `_r2` and Phase 8AF's own copy of it) — not a
    statutory rule. Applied only to final output amounts."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class _SIGroupResult:
    segment_start: object
    segment_end: object
    work_date_local: date_cls
    qualifying_hours: Decimal
    actual_grundlohn_hourly: Optional[Decimal] = None
    si_grundlohn_hourly: Optional[Decimal] = None
    si_cap_rule_id: Optional[int] = None
    primary_category_code: Optional[str] = None
    primary_category_rule_id: Optional[int] = None
    concurrent_category_code: Optional[str] = None
    concurrent_category_rule_id: Optional[int] = None
    combined_premium_pct: Optional[Decimal] = None
    applicable_si_branches: Optional[str] = None
    gross_qualifying_premium_amount: Optional[Decimal] = None
    si_free_premium_amount: Optional[Decimal] = None
    si_contributory_premium_amount: Optional[Decimal] = None
    calculation_status: str = _NOT_CONFIGURED
    calculation_note: Optional[str] = None

    def as_dict(self) -> dict:
        return dict(
            segment_start=self.segment_start, segment_end=self.segment_end,
            work_date_local=self.work_date_local, qualifying_hours=self.qualifying_hours,
            actual_grundlohn_hourly=self.actual_grundlohn_hourly, si_grundlohn_hourly=self.si_grundlohn_hourly,
            si_cap_rule_id=self.si_cap_rule_id,
            primary_category_code=self.primary_category_code, primary_category_rule_id=self.primary_category_rule_id,
            concurrent_category_code=self.concurrent_category_code,
            concurrent_category_rule_id=self.concurrent_category_rule_id,
            combined_premium_pct=self.combined_premium_pct, applicable_si_branches=self.applicable_si_branches,
            gross_qualifying_premium_amount=self.gross_qualifying_premium_amount,
            si_free_premium_amount=self.si_free_premium_amount,
            si_contributory_premium_amount=self.si_contributory_premium_amount,
            calculation_status=self.calculation_status, calculation_note=self.calculation_note,
        )


def _group_segments_by_physical_range(segments: List) -> dict:
    groups: dict = {}
    for seg in segments:
        key = (seg.segment_start, seg.segment_end)
        groups.setdefault(key, []).append(seg)
    return groups


def _calculate_one_si_group(db: Session, work_record, start, end, segs: List) -> _SIGroupResult:
    from app.modules.payroll import service

    work_date_local = segs[0].work_date_local
    hours = Decimal(segs[0].hours)
    categories = [s.premium_category for s in segs]

    result = _SIGroupResult(segment_start=start, segment_end=end, work_date_local=work_date_local, qualifying_hours=hours)

    # ── Resolve the employee's effective Grundlohn (Phase 8AB) — same
    # source as the wage-tax path, resolved independently here ──────────
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

    # ── Resolve the PUBLISHED SOCIAL_INSURANCE Grundlohn cap (Phase 8AD)
    # — NEVER the WAGE_TAX dimension, never hardcoded €25 ────────────────
    cap_row = service.resolve_germany_overtime_grundlohn_cap(db, "SOCIAL_INSURANCE", as_of=work_date_local)
    if cap_row is None:
        result.calculation_status = _NOT_CONFIGURED
        result.calculation_note = f"No PUBLISHED SOCIAL_INSURANCE GermanyOvertimeGrundlohnCap as of {work_date_local}."
        return result
    result.si_cap_rule_id = cap_row.id
    si_grundlohn = min(actual_grundlohn, Decimal(cap_row.hourly_cap_amount))
    result.si_grundlohn_hourly = si_grundlohn

    # ── Resolve category rate(s) — same verified-concurrence pairing as
    # Phase 8AF (see module docstring's ENGINEERING DESIGN disclosure) ───
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
        result.combined_premium_pct = Decimal(rule.wage_tax_free_pct)
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
        result.combined_premium_pct = Decimal(night_rule.wage_tax_free_pct) + Decimal(other_rule.wage_tax_free_pct)
    else:
        result.calculation_status = _STATUTORY_RULE_UNRESOLVED
        result.calculation_note = (
            f"Categories {sorted(categories)} concurrence is not established by verified guidance "
            "(inherits Phase 8AF's wage-tax-side finding — R 3b LStH only addresses night + one "
            "Sunday/holiday category; §1 SvEV itself is silent on concurrence entirely) — "
            "STATUTORY_CONCURRENCE_RULE_NOT_ESTABLISHED for this combination."
        )
        return result

    # ── Compute (Decimal throughout; round only the final amounts) ──────
    pct_fraction = result.combined_premium_pct / Decimal(100)
    gross = pct_fraction * actual_grundlohn * hours
    si_free = pct_fraction * si_grundlohn * hours
    gross_rounded = _r2(gross)
    si_free_rounded = _r2(si_free)

    result.gross_qualifying_premium_amount = gross_rounded
    result.si_free_premium_amount = si_free_rounded
    result.si_contributory_premium_amount = gross_rounded - si_free_rounded
    result.applicable_si_branches = _APPLICABLE_SI_BRANCHES
    result.calculation_status = _CALCULATED
    return result


def calculate_social_insurance_groups(db: Session, work_record) -> List[_SIGroupResult]:
    """Pure calculation (no persistence). Raises
    GermanyOvertimeSINotClassifiedError if Phase 8AE classification has
    never been run for this work record."""
    from app.modules.payroll.models import GermanyOvertimeTimeSegment

    segments = (
        db.query(GermanyOvertimeTimeSegment)
        .filter(GermanyOvertimeTimeSegment.work_record_id == work_record.id)
        .order_by(GermanyOvertimeTimeSegment.segment_start)
        .all()
    )
    if not segments:
        raise GermanyOvertimeSINotClassifiedError(
            "No GermanyOvertimeTimeSegment rows exist for this work record — run Phase 8AE classification first."
        )

    groups = _group_segments_by_physical_range(segments)
    return [
        _calculate_one_si_group(db, work_record, start, end, segs)
        for (start, end), segs in sorted(groups.items(), key=lambda kv: kv[0][0])
    ]


def calculate_germany_overtime_social_insurance(db: Session, work_record, persist: bool = True, actor_id=None) -> List:
    """Same idempotent re-derivation pattern as Phase 8AE/8AF: replaces
    any existing GermanyOvertimeSocialInsuranceResult rows for this work
    record with the freshly-computed set."""
    from app.modules.payroll.models import GermanyOvertimeSocialInsuranceResult

    group_results = calculate_social_insurance_groups(db, work_record)

    if not persist:
        return group_results

    db.query(GermanyOvertimeSocialInsuranceResult).filter(
        GermanyOvertimeSocialInsuranceResult.work_record_id == work_record.id,
    ).delete()
    rows = []
    for gr in group_results:
        row = GermanyOvertimeSocialInsuranceResult(
            organization_id=work_record.organization_id, work_record_id=work_record.id,
            created_by_id=actor_id, **gr.as_dict(),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows
