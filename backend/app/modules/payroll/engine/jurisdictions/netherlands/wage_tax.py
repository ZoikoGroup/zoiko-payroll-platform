"""
engine/jurisdictions/netherlands/wage_tax.py
---------------------------------------------
Pure NL wage-tax withholding engine (ZP-NL-ENG-001 NL-005..NL-010).

Doctrine (spec §0 "Critical doctrine", NL-005):
  * Ordinary withholding MUST reproduce the official 2026 Belastingdienst
    wage-tax tables exactly. No formula approximations.
  * Tables are authoritative; the engine only looks up.
  * Every result carries the full table key for audit (NL-007).

The rows come from an ACTIVE payroll_nl_tax_table_files row (imported,
validated and four-eyes approved by netherlands_tables_service). The service
resolves them and passes them in (ctx.nl_wage_tax_rows / the `rows` argument);
this module never reads the database. The in-memory registry below is kept
only for direct unit tests — the payroll path never depends on it, because a
process-local cache is empty after a restart and differs between workers.

BLOCKED until G1: without the official 2026 tables every lookup raises NLBlock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


class NLError(Exception):
    pass


class NLBlock(NLError):
    """Explicit block: required table data missing (do not invent)."""


class TableColor(str, Enum):
    WHITE = "WHITE"
    GREEN = "GREEN"


class TableKind(str, Enum):
    PERIOD = "PERIOD"
    SPECIAL_REMUNERATION = "SPECIAL_REMUNERATION"


class PeriodCode(str, Enum):
    DAY = "DAY"
    WEEK = "WEEK"
    FOUR_WEEK = "FOUR_WEEK"
    MONTHLY = "MONTHLY"
    QUARTER = "QUARTER"
    YEAR = "YEAR"


# PeriodCode -> payroll_nl_tax_table_files.period (CHECK-constrained values).
TABLE_FILE_PERIOD = {
    PeriodCode.DAY: "DAY", PeriodCode.WEEK: "WEEK", PeriodCode.FOUR_WEEK: "FOUR_WEEK",
    PeriodCode.MONTHLY: "MONTH", PeriodCode.QUARTER: "QUARTER", PeriodCode.YEAR: "YEAR",
}


class AowCohort(str, Enum):
    BELOW_AOW = "BELOW_AOW"
    AOW_AGE = "AOW_AGE"


# Statutory AOW (state pension) age by calendar year. 2026 = 67 years
# (Belastingdienst / SVB). Any other year is absent on purpose: the cohort
# selection BLOCKS rather than guessing — add the year with its source at G1.
AOW_AGE_YEARS = {2026: 67}


@dataclass(frozen=True)
class NlTableKey:
    """Full table key carried on every result (NL-007 audit requirement)."""
    tax_year: int
    table_color: TableColor
    table_kind: TableKind
    period: Optional[PeriodCode]  # None for SPECIAL_REMUNERATION
    residence_variant: str  # "NL" or derivation code
    aow_cohort: AowCohort
    with_tax_credit: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tax_year": self.tax_year,
            "table_color": self.table_color.value,
            "table_kind": self.table_kind.value,
            "period": self.period.value if self.period else None,
            "residence_variant": self.residence_variant,
            "aow_cohort": self.aow_cohort.value,
            "with_tax_credit": self.with_tax_credit,
        }


@dataclass(frozen=True)
class NlWithholdingResult:
    """Result of a single wage-tax lookup."""
    table_key: NlTableKey
    gross_wage: Decimal
    withholding_amount: Decimal
    percentage_applied: Optional[Decimal] = None  # for special-remuneration
    method: str = "TABLE_LOOKUP"
    warnings: Tuple[str, ...] = ()
    remediation_hints: Tuple[str, ...] = ()
    row: Optional[Dict[str, Any]] = None  # the exact table row used (NL-054)

    def as_dict(self) -> Dict[str, Any]:
        d = {
            "table_key": self.table_key.as_dict(),
            "gross_wage": str(self.gross_wage),
            "withholding_amount": str(self.withholding_amount),
            "method": self.method,
            "warnings": list(self.warnings),
            "remediation_hints": list(self.remediation_hints),
        }
        if self.percentage_applied is not None:
            d["percentage_applied"] = str(self.percentage_applied)
        if self.row is not None:
            d["row"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.row.items()}
        return d


# ── Test-only registry (see module docstring) ────────────────────────────────
_TABLE_CACHE: Dict[Tuple, Any] = {}


def _cache_key(table_key: NlTableKey) -> Tuple:
    return (table_key.tax_year, table_key.table_color, table_key.table_kind, table_key.period,
            table_key.residence_variant, table_key.aow_cohort, table_key.with_tax_credit)


def register_table_rows(table_key: NlTableKey, rows: list[Mapping[str, Any]]) -> None:
    _TABLE_CACHE[_cache_key(table_key)] = rows


def is_table_loaded(table_key: NlTableKey) -> bool:
    return _cache_key(table_key) in _TABLE_CACHE


def _aow_cohort_from_dob(dob: date, pay_date: date) -> AowCohort:
    aow_age = AOW_AGE_YEARS.get(pay_date.year)
    if aow_age is None:
        raise NLBlock(f"statutory AOW age for {pay_date.year} is not recorded — cannot select the table cohort")
    age = pay_date.year - dob.year - ((pay_date.month, pay_date.day) < (dob.month, dob.day))
    return AowCohort.AOW_AGE if age >= aow_age else AowCohort.BELOW_AOW


def select_table_key(ctx: Any, *, special_remuneration: bool = False) -> NlTableKey:
    """Pick the table key from context (NL-005, NL-007). Raises NLBlock if a
    required fact is missing. The tax credit applies ONLY on a signed employee
    instruction in force (NL-006/NL-031): no instruction -> without credit."""
    if getattr(ctx, "pay_date", None) is None:
        raise NLBlock("ctx.pay_date required for NL wage-tax table selection")
    period_code = getattr(ctx, "payroll_period_code", None)
    if period_code is None and not special_remuneration:
        raise NLBlock("ctx.payroll_period_code required for NL wage-tax table selection")
    dob = getattr(ctx, "employee_date_of_birth", None) or getattr(ctx, "date_of_birth", None)
    if dob is None:
        raise NLBlock("employee_date_of_birth required to determine AOW cohort")
    color = getattr(ctx, "nl_table_color", None)
    if not color:
        raise NLBlock("wage-tax table colour not recorded on the employee's NL profile")
    if TableColor(color) != TableColor.WHITE:
        raise NLBlock("GREEN-table (former employment) payments are not certified in this release (NL-001)")
    return NlTableKey(
        tax_year=ctx.pay_date.year,
        table_color=TableColor(color),
        table_kind=TableKind.SPECIAL_REMUNERATION if special_remuneration else TableKind.PERIOD,
        period=None if special_remuneration else PeriodCode(str(period_code).upper()),
        residence_variant=getattr(ctx, "nl_residence_variant", None) or "NL",
        aow_cohort=_aow_cohort_from_dob(dob, ctx.pay_date),
        with_tax_credit=bool(getattr(ctx, "nl_with_tax_credit", False)),
    )


def _lookup_in_rows(wage: Decimal, rows: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The row where wage_from <= wage < wage_to (wage_to NULL = open top band)."""
    for row in rows:
        w_from = Decimal(str(row["wage_from"]))
        w_to = row.get("wage_to")
        if w_to is not None:
            if w_from <= wage < Decimal(str(w_to)):
                return row
        elif w_from <= wage:
            return row
    return None


def _rows_for(table_key: NlTableKey, rows: Optional[Sequence[Mapping[str, Any]]], ctx: Any,
              ctx_attr: str) -> Sequence[Mapping[str, Any]]:
    """Rows for this key's cohort + credit column. Explicit rows win, then the
    rows the service resolved onto ctx, then the test registry."""
    source = rows if rows is not None else getattr(ctx, ctx_attr, None)
    if source is None:
        source = _TABLE_CACHE.get(_cache_key(table_key))
    if source is None:
        raise NLBlock(
            f"NL wage-tax table not available: {table_key.as_dict()} — import and activate the official "
            f"Belastingdienst {table_key.tax_year} file via netherlands_tables_service (gate G1)")
    selected = [r for r in source
                if str(r.get("aow_cohort", table_key.aow_cohort.value)) == table_key.aow_cohort.value
                and bool(r.get("with_tax_credit", table_key.with_tax_credit)) == table_key.with_tax_credit]
    if not selected:
        raise NLBlock(f"active NL wage-tax table has no rows for {table_key.as_dict()}")
    return selected


def lookup_period_withholding(ctx: Any, gross_wage: Decimal, rows: Optional[Sequence[Mapping[str, Any]]] = None
                              ) -> NlWithholdingResult:
    """Period-table withholding lookup (NL-005, NL-007)."""
    table_key = select_table_key(ctx, special_remuneration=False)
    if gross_wage < 0:
        raise NLBlock("negative table wage — use the correction workflow, not a period lookup (NL-011)")
    row = _lookup_in_rows(gross_wage, _rows_for(table_key, rows, ctx, "nl_wage_tax_rows"))
    if row is None:
        raise NLBlock(f"No matching row in NL wage-tax table for wage {gross_wage} with key {table_key.as_dict()}")
    return NlWithholdingResult(table_key=table_key, gross_wage=gross_wage,
                               withholding_amount=Decimal(str(row["withholding_amount"])),
                               method="TABLE_LOOKUP", row=dict(row))


def special_remuneration(ctx: Any, gross_wage: Decimal, rows: Optional[Sequence[Mapping[str, Any]]] = None,
                         reference_annual_wage: Optional[Decimal] = None) -> NlWithholdingResult:
    """Special-remuneration table (NL-010): the percentage is selected by the
    REFERENCE ANNUAL WAGE, then applied to the special payment. Without a
    reference annual wage the lookup falls back to the payment itself only in
    direct calls (unit tests); the payroll engine always supplies it."""
    table_key = select_table_key(ctx, special_remuneration=True)
    basis = reference_annual_wage if reference_annual_wage is not None else gross_wage
    row = _lookup_in_rows(basis, _rows_for(table_key, rows, ctx, "nl_special_tax_rows"))
    if row is None:
        raise NLBlock(f"No matching row in NL special-remuneration table for reference wage {basis} "
                      f"with key {table_key.as_dict()}")
    pct = Decimal(str(row["percentage"]))
    return NlWithholdingResult(
        table_key=table_key, gross_wage=gross_wage,
        withholding_amount=(gross_wage * pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        percentage_applied=pct, method="SPECIAL_REMUNERATION", row=dict(row),
        warnings=() if reference_annual_wage is not None else ("reference annual wage not supplied",))


_special_remuneration_lookup = special_remuneration


def anonymous_rate(gross_wage: Decimal, rate_pct: Decimal, *, tax_year: int = 0) -> NlWithholdingResult:
    """Anonymous-person withholding (NL-008): the pack's flat rate (52% in
    2026) with an explicit remediation warning — never a silent zero."""
    withholding = (gross_wage * Decimal(str(rate_pct)) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return NlWithholdingResult(
        table_key=NlTableKey(tax_year=tax_year, table_color=TableColor.WHITE, table_kind=TableKind.PERIOD,
                             period=None, residence_variant="ANONYMOUS", aow_cohort=AowCohort.BELOW_AOW,
                             with_tax_credit=False),
        gross_wage=gross_wage, withholding_amount=withholding, percentage_applied=Decimal(str(rate_pct)),
        method="ANONYMOUS_RATE",
        warnings=(f"Anonymous rate ({rate_pct}%) applied — no tax credits, no deductions",),
        remediation_hints=("Obtain employee BSN and residence status to use standard tables",),
    )


def voluntary_extra(withholding: Decimal, extra: Decimal) -> Decimal:
    """Voluntary extra withholding can only ADD tax, never reduce it (spec §3)."""
    if extra < 0:
        raise NLError("Voluntary extra withholding cannot be negative")
    return withholding + extra


def calculate_wage_tax(ctx: Any, gross_wage: Decimal, *,
                       special_remuneration: bool = False,
                       anonymous: bool = False,
                       anonymous_rate_pct: Optional[Decimal] = None,
                       voluntary_extra_amount: Optional[Decimal] = None,
                       rows: Optional[Sequence[Mapping[str, Any]]] = None,
                       reference_annual_wage: Optional[Decimal] = None) -> NlWithholdingResult:
    """Single entry point used by engine/countries/netherlands.py."""
    if anonymous:
        if anonymous_rate_pct is None:
            raise NLBlock("anonymous-person rate not configured in the active pack (nl_anonymous_rate_pct)")
        result = anonymous_rate(gross_wage, anonymous_rate_pct, tax_year=ctx.pay_date.year)
    elif special_remuneration:
        result = _special_remuneration_lookup(ctx, gross_wage, rows=rows, reference_annual_wage=reference_annual_wage)
    else:
        result = lookup_period_withholding(ctx, gross_wage, rows=rows)

    if voluntary_extra_amount:
        result = NlWithholdingResult(
            table_key=result.table_key, gross_wage=result.gross_wage,
            withholding_amount=voluntary_extra(result.withholding_amount, Decimal(str(voluntary_extra_amount))),
            percentage_applied=result.percentage_applied, method=result.method,
            warnings=result.warnings + (f"voluntary extra withholding {voluntary_extra_amount} included",),
            remediation_hints=result.remediation_hints, row=result.row,
        )
    return result
