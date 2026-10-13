"""
engine/jurisdictions/netherlands/wage_tax.py
---------------------------------------------
Pure NL wage-tax withholding engine (ZP-NL-ENG-001 NL-005..NL-010).

Doctrine (spec §0 "Critical doctrine", NL-005):
  * Ordinary withholding MUST reproduce the official 2026 Belastingdienst
    wage-tax tables exactly. No formula approximations.
  * Tables are authoritative; the engine only looks up.
  * Every result carries the full table key for audit (NL-007).

Inputs the engine needs (all supplied by netherlands_tables_service once G1
tables are imported):
  * Tax year
  * Table colour (WHITE / GREEN) — current vs former employment
  * Residence variant (NL / derivation code)
  * AOW cohort (BELOW_AOW / AOW_AGE) — from date of birth + statutory AOW age
  * Payroll period (DAY / WEEK / FOUR_WEEK / MONTH / QUARTER / YEAR)
  * Tax-credit flag (with/without general + employment tax credit)
  * Special-remuneration flag

BLOCKED until G1: the official 2026 table files (white, green, derivation,
special-remuneration for all periods) must be imported into
payroll_nl_tax_table_files / payroll_nl_tax_table_rows. Without them,
select_table_key() will raise NLBlock.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import date
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from app.modules.payroll.engine.base import PayrollContext


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


class AowCohort(str, Enum):
    BELOW_AOW = "BELOW_AOW"
    AOW_AGE = "AOW_AGE"


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
        return d


# In-memory table cache populated by netherlands_tables_service from DB.
# Structure: (tax_year, table_color, table_kind, period, residence_variant, aow_cohort, with_tax_credit) -> list of row dicts
_TABLE_CACHE: Dict[Tuple, Any] = {}
_CACHE_LOADED: Dict[Tuple, bool] = {}


def _cache_key(table_key: NlTableKey) -> Tuple:
    return (
        table_key.tax_year,
        table_key.table_color,
        table_key.table_kind,
        table_key.period,
        table_key.residence_variant,
        table_key.aow_cohort,
        table_key.with_tax_credit,
    )


def register_table_rows(table_key: NlTableKey, rows: list[Mapping[str, Any]]) -> None:
    """Called by netherlands_tables_service after importing/activating a table file.
    `rows` must be a list of dicts with keys:
      - wage_from, wage_to (Decimal or str/None), aow_cohort, with_tax_credit,
        withholding_amount (Decimal/str) or percentage (Decimal/str).
    """
    _TABLE_CACHE[_cache_key(table_key)] = rows
    _CACHE_LOADED[_cache_key(table_key)] = True


def is_table_loaded(table_key: NlTableKey) -> bool:
    return _CACHE_LOADED.get(_cache_key(table_key), False)


def _get_cached_rows(table_key: NlTableKey) -> list[Mapping[str, Any]]:
    key = _cache_key(table_key)
    if key not in _TABLE_CACHE:
        raise NLBlock(
            f"NL wage-tax table not loaded: {table_key.as_dict()} — "
            f"import official Belastingdienst 2026 file via netherlands_tables_service (gate G1)"
        )
    return _TABLE_CACHE[key]


def _aow_cohort_from_dob(dob: date, pay_date: date) -> AowCohort:
    """Determine AOW cohort from date of birth and statutory AOW age.
    Statutory AOW age in 2026 is 67. This should use the official table once available.
    """
    # TODO: use official AOW age table per year (Belastingdienst publishes this)
    # For 2026, AOW age = 67
    aow_age = 67
    age = pay_date.year - dob.year - ((pay_date.month, pay_date.day) < (dob.month, dob.day))
    return AowCohort.AOW_AGE if age >= aow_age else AowCohort.BELOW_AOW


def _resolve_residence_variant(ctx: PayrollContext) -> str:
    """Resolve residence variant from context. Default 'NL'.
    Derivation codes for non-residents etc. come from employee data.
    """
    # TODO: read from ctx.employee_tax_residency / derivation code
    return getattr(ctx, "nl_residence_variant", "NL") or "NL"


def select_table_key(ctx: PayrollContext, *, special_remuneration: bool = False) -> NlTableKey:
    """Pick the correct table key from context (NL-005, NL-007).
    Raises NLBlock if any required context field is missing.
    """
    if ctx.pay_date is None:
        raise NLBlock("ctx.pay_date required for NL wage-tax table selection")
    if ctx.payroll_period_code is None:
        raise NLBlock("ctx.payroll_period_code required for NL wage-tax table selection")

    tax_year = ctx.pay_date.year
    table_color = TableColor(getattr(ctx, "nl_table_color", "WHITE") or "WHITE")
    residence_variant = _resolve_residence_variant(ctx)

    dob = getattr(ctx, "employee_date_of_birth", None) or getattr(ctx, "date_of_birth", None)
    if dob is None:
        raise NLBlock("employee_date_of_birth required to determine AOW cohort")
    aow_cohort = _aow_cohort_from_dob(dob, ctx.pay_date)

    with_tax_credit = getattr(ctx, "nl_with_tax_credit", True)

    if special_remuneration:
        return NlTableKey(
            tax_year=tax_year,
            table_color=table_color,
            table_kind=TableKind.SPECIAL_REMUNERATION,
            period=None,
            residence_variant=residence_variant,
            aow_cohort=aow_cohort,
            with_tax_credit=with_tax_credit,
        )

    period = PeriodCode(ctx.payroll_period_code.upper())
    return NlTableKey(
        tax_year=tax_year,
        table_color=table_color,
        table_kind=TableKind.PERIOD,
        period=period,
        residence_variant=residence_variant,
        aow_cohort=aow_cohort,
        with_tax_credit=with_tax_credit,
    )


def _lookup_in_rows(wage: Decimal, rows: list[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """Find the row where wage_from <= wage < wage_to (or wage_to is NULL)."""
    for row in rows:
        w_from = Decimal(str(row["wage_from"]))
        w_to = row.get("wage_to")
        if w_to is not None:
            w_to = Decimal(str(w_to))
            if w_from <= wage < w_to:
                return row
        else:
            if w_from <= wage:
                return row
    return None


def lookup_period_withholding(ctx: PayrollContext, gross_wage: Decimal) -> NlWithholdingResult:
    """Period-table withholding lookup (NL-006, NL-007, NL-008).
    Returns NlWithholdingResult with full table_key for audit.
    """
    table_key = select_table_key(ctx, special_remuneration=False)
    rows = _get_cached_rows(table_key)

    row = _lookup_in_rows(gross_wage, rows)
    if row is None:
        raise NLBlock(
            f"No matching row in NL wage-tax table for wage {gross_wage} "
            f"with key {table_key.as_dict()}"
        )

    withholding = Decimal(str(row["withholding_amount"]))
    warnings = ()
    remediation = ()

    # Anonymous rate check (52%) — if the table returns a result that would
    # imply >52% effective rate, flag it (NL-009 anonymous rate is separate path)
    # but the period table itself should already incorporate this.

    return NlWithholdingResult(
        table_key=table_key,
        gross_wage=gross_wage,
        withholding_amount=withholding,
        method="TABLE_LOOKUP",
        warnings=warnings,
        remediation_hints=remediation,
    )


def special_remuneration(ctx: PayrollContext, gross_wage: Decimal) -> NlWithholdingResult:
    """Special-remuneration table lookup (NL-010).
    Returns percentage and computed amount; keeps reference annual wage + method.
    """
    table_key = select_table_key(ctx, special_remuneration=True)
    rows = _get_cached_rows(table_key)

    row = _lookup_in_rows(gross_wage, rows)
    if row is None:
        raise NLBlock(
            f"No matching row in NL special-remuneration table for wage {gross_wage} "
            f"with key {table_key.as_dict()}"
        )

    pct = Decimal(str(row["percentage"]))
    withholding = (gross_wage * pct / Decimal("100")).quantize(Decimal("0.01"))

    return NlWithholdingResult(
        table_key=table_key,
        gross_wage=gross_wage,
        withholding_amount=withholding,
        percentage_applied=pct,
        method="SPECIAL_REMUNERATION",
        warnings=(),
        remediation_hints=(),
    )


def anonymous_rate(gross_wage: Decimal) -> NlWithholdingResult:
    """Anonymous person withholding: 52% flat (NL-009).
    Adds remediation warning per spec.
    """
    withholding = (gross_wage * Decimal("52.00") / Decimal("100")).quantize(Decimal("0.01"))
    return NlWithholdingResult(
        table_key=NlTableKey(
            tax_year=0,  # not tied to a specific year table
            table_color=TableColor.WHITE,
            table_kind=TableKind.PERIOD,
            period=None,
            residence_variant="ANONYMOUS",
            aow_cohort=AowCohort.BELOW_AOW,
            with_tax_credit=False,
        ),
        gross_wage=gross_wage,
        withholding_amount=withholding,
        method="ANONYMOUS_RATE",
        warnings=("Anonymous rate (52%) applied — no tax credits, no deductions",),
        remediation_hints=("Obtain employee BSN and residence status to use standard tables",),
    )


def voluntary_extra(withholding: Decimal, extra: Decimal) -> Decimal:
    """Voluntary extra withholding can only ADD tax, never reduce (NL-008).
    Returns the final withholding amount.
    """
    if extra < 0:
        raise NLError("Voluntary extra withholding cannot be negative")
    return withholding + extra


# --- Integration helper for netherlands.py calculator ---

def calculate_wage_tax(ctx: PayrollContext, gross_wage: Decimal, *,
                       special_remuneration: bool = False,
                       anonymous: bool = False,
                       voluntary_extra_amount: Optional[Decimal] = None) -> NlWithholdingResult:
    """Single entry point used by engine/countries/netherlands.py.
    Dispatches to the correct lookup based on flags.
    """
    if anonymous:
        result = anonymous_rate(gross_wage)
    elif special_remuneration:
        result = special_remuneration(ctx, gross_wage)
    else:
        result = lookup_period_withholding(ctx, gross_wage)

    if voluntary_extra_amount:
        result = NlWithholdingResult(
            table_key=result.table_key,
            gross_wage=result.gross_wage,
            withholding_amount=voluntary_extra(result.withholding_amount, voluntary_extra_amount),
            percentage_applied=result.percentage_applied,
            method=result.method,
            warnings=result.warnings,
            remediation_hints=result.remediation_hints,
        )

    return result