# New Zealand P3: code architecture (file-level blueprint)

This is the third document for Phase 3. Read them in this order:
1. `IMPLEMENTATION_HANDOFF_P3_P10.md` §0: ground rules R1–R13.
2. `P3_CALCULATION_ENGINE_PLAN.md`: the rules and the test list.
3. **This file**: the structure of every file and function, as skeletons with step-by-step pseudocode. Implement by turning each skeleton into code.

Everything here is design; nothing in it is shipped code. Paths are relative to `backend/app/modules/payroll/` unless they start with `backend/`.

---

## 1. File tree after P3

```
backend/app/modules/payroll/
├── engine/
│   ├── base.py                                   (EDIT)  + 14 nz_* PayrollContext fields, + PayrollResult.nz_result
│   ├── standard.py                               (EDIT)  + nz_employee_total in deductions, + nz_result passthrough
│   ├── resolver.py                               (no change in P3; the simple-mode block already exists)
│   ├── countries/
│   │   ├── new_zealand.py                        (REWRITE) orchestrator: resolve_applicability(), calculate()
│   │   └── new_zealand_content.py                (EDIT, docstring only) authority-table row formats
│   └── jurisdictions/new_zealand/
│       ├── __init__.py                           (exists, empty)
│       ├── errors.py                             (EDIT)  reason-code constants
│       ├── pack.py                               (NEW)   NzPack: the only way to read pack rows; rounding
│       ├── hashing.py                            (NEW)   canonical JSON + sha256 helpers
│       ├── components.py                         (NEW)   pay components → per-obligation bases
│       ├── paye.py                               (NEW)   tax-code routing + MAIN/SECONDARY/ND/STC PAYE + IETC
│       ├── acc_earner_levy.py                    (NEW)   ACC levy with the accumulator-based cap
│       ├── student_loan.py                       (NEW)   main threshold / whole payment / certificates / extras
│       ├── esct.py                               (NEW)   ESCT band check + amount
│       ├── kiwisaver.py                          (NEW)   eligibility, employee + employer, ESCT, destination
│       ├── child_support.py                      (NEW)   protected net, shortfall, variation code
│       ├── deduction_precedence.py               (NEW)   approved statutory order
│       └── minimum_wage.py                       (NEW)   PASS / FAIL / UNDETERMINABLE (exception, not a block)
backend/tests/
├── _nz_engine_helpers.py                         (NEW)   test pack + ctx builders (TEST values only)
├── test_nz_engine_pack.py                        (NEW)   NzPack, rounding, pending guard
├── test_nz_engine_components.py                  (NEW)
├── test_nz_engine_paye.py                        (NEW)   PAYE + ACC
├── test_nz_engine_deductions.py                  (NEW)   student loan, KiwiSaver, ESCT, child support, precedence
├── test_nz_engine_min_wage.py                    (NEW)
├── test_nz_engine.py                             (NEW)   end-to-end calculate(), standard integration, determinism,
│                                                          privacy, purity, shipped-content block
├── test_nz_golden.py                             (NEW)   IRD official examples (skipped until G1)
└── test_nz_scaffold.py                           (EDIT)  the stub-era "always blocks" tests → "empty ctx blocks"
```

New code is roughly 1,100 lines and new tests roughly 1,000 lines. P3 has **no migration and no route**.

---

## 2. Module dependency graph (arrows = "imports")

```
                    engine/standard.py
                           │  _COUNTRY_CALC["NZ"]
                           ▼
              engine/countries/new_zealand.py  ──────────────► engine/base.py (PayrollContext)
                           │
     ┌──────────┬──────────┼───────────┬─────────────┬──────────────┬──────────────┐
     ▼          ▼          ▼           ▼             ▼              ▼              ▼
 components   paye   acc_earner_levy student_loan kiwisaver  child_support   minimum_wage
     │          │          │           │           │   │          │              │
     │          │          │           │           │   └──► esct  │              │
     │          │          │           │           │              │   deduction_precedence
     └──────────┴──────────┴─────┬─────┴───────────┴──────────────┴──────────────┘
                                 ▼
                              pack.py ────► errors.py ────► engine/countries/shared.py
                                 │                         (MissingComplianceConfigurationError)
                                 ▼
                 engine/countries/new_zealand_content.py   (constants only: rule types, enums)
              hashing.py  ◄── new_zealand.py only
```

**Rules for the graph:**
- **No module under `jurisdictions/new_zealand/` imports `new_zealand.py`.** The dependency is one way.
- **Nothing imports `app.database`, `app.config`, `sqlalchemy`, `service.py` or the models.** The engine is pure (NZ-022).
- `new_zealand_content.py` is imported only for **constants**: rule-type names, enum tuples, `PENDING`. The engine never reads a statutory *value* from the content module. Values come only from `ctx.rate_map` / `ctx.slabs`.

---

## 3. Call sequence for one payslip

```
StandardStrategy.calculate(ctx)                         engine/standard.py:266
  └─ deductions = _COUNTRY_CALC["NZ"](ctx)              → new_zealand.calculate(ctx)
       ├─ pack = NzPack(ctx.rate_map, ctx.slabs, org_id, as_of=ctx.pay_date)
       ├─ app  = resolve_applicability(ctx, pack)        guards → frequency, TaxCode, profiles
       ├─ comps   = components.pay_components(ctx, pack)
       ├─ classes = components.earning_classes(pack)
       ├─ bases   = {o: components.obligation_base(o, comps, classes, pack) for o in BASES}
       ├─ paye_r  = paye.calculate_paye(bases.PAYE, app.code, app.profile, app.freq, payday, pack)
       ├─ acc_r   = acc_earner_levy.calculate_levy(bases.ACC, ctx.nz_accumulators, pack)
       ├─ sl_r    = student_loan.calculate_student_loan(bases.STUDENT_LOAN, app.code, app.profile,
       │                                                 app.freq, payday, notices, pack)
       ├─ ks_r    = kiwisaver.calculate_kiwisaver(bases.KIWISAVER, ctx.nz_kiwisaver, dob, payday, pack)
       │              └─ esct.resolve_esct_rate / esct.calculate_esct
       ├─ order   = deduction_precedence.precedence(pack)
       ├─ net_before_cs = gross − Σ(order before CHILD_SUPPORT)
       ├─ cs_r    = child_support.calculate_child_support(net_before_cs, notices, pack)
       ├─ mw_r    = minimum_wage.check_minimum_wage(bases.MIN_WAGE, ctx.nz_hours, src, category, pack)
       ├─ nz_result = _assemble(...)                     §5.13
       ├─ nz_result["hashes"] = hashing.hashes(inputs, pack.used(), nz_result)
       └─ return {"tds", "nz_employee_total", "employer_pension", "nz_result"}
  └─ total_employee_deductions += tds + nz_employee_total    (standard.py)
  └─ PayrollResult(..., employer_pension=..., nz_result=...)
```

Any step may raise `NZCalculationBlockedError(key, reason, org_id)`. The platform already turns a `MissingComplianceConfigurationError` into a 4xx response or a per-employee preview block; there is no extra handling to add.

---

## 4. Shared data shapes

Rows arrive either as ORM objects (a real run) or as dicts (a thaw in P4, and tests). **Every access goes through `pack.field(row, name)`**, which handles both.

```python
# jurisdictions/new_zealand/paye.py
@dataclass(frozen=True)
class TaxCode:
    code: str                  # "M SL"
    income_class: str          # MAIN | SECONDARY | SPECIAL
    student_loan: bool         # tax_column == "SL"
    independent_earner: bool   # tax_table_number == "IETC"

@dataclass
class PayeResult:   paye: Decimal; branch: str; period_factor: Decimal | None; steps: list

# acc_earner_levy.py
@dataclass
class AccResult:    liable: Decimal; levy: Decimal; cap: Decimal; ytd_before: Decimal
                    ytd_after: Decimal; cap_crossed: bool; cap_reached_before: bool; steps: list
# student_loan.py
@dataclass
class SlResult:     deduction: Decimal; standard: Decimal; extra: Decimal; basis: str
                    threshold: Decimal | None; steps: list
# kiwisaver.py
@dataclass
class KsResult:     status: str; employee_rate: Decimal | None; employee: Decimal
                    employer_rate: Decimal | None; employer_gross: Decimal
                    esct_rate: Decimal | None; esct: Decimal; employer_net: Decimal
                    destination: str | None; complying_fund_ref: str | None
                    compulsory_employer: bool; reduction_applied: bool; steps: list
# child_support.py
@dataclass
class CsResult:     deduction: Decimal; required: Decimal; max_allowed: Decimal
                    protected_net: Decimal; shortfall: Decimal; variation_code: str | None
                    notices: list; steps: list
# minimum_wage.py
@dataclass
class MinWageResult: status: str; effective_rate: Decimal | None; floor: Decimal | None
                     shortfall: Decimal | None; category: str | None
                     hours: Decimal | None; hours_source: str | None; steps: list
```

A **step** (trace entry) is always `{"step": str, "value": str, "note": str | None}`, for example `{"step": "annualised", "value": "78000.00", "note": "3000.00 × 26"}`.

---

## 5. File skeletons

### 5.1 `jurisdictions/new_zealand/errors.py` (EDIT)
```python
"""New Zealand calculation errors and reason codes (ZP-NZ-ENG-001)."""
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "NZ"

class NZCalculationBlockedError(MissingComplianceConfigurationError):   # unchanged
    ...

# ── block codes (the `key` of NZCalculationBlockedError) ──
PACK_UNSIGNED = "NZ_PACK_UNSIGNED"
TABLE_EMPTY = "NZ_TABLE_EMPTY"                 # f"{TABLE_EMPTY}:{table_name}"
ROW_MISSING = "NZ_ROW_MISSING"                 # f"{ROW_MISSING}:{component_key}"
ROUNDING_PENDING = "NZ_ROUNDING_PENDING"       # f"{ROUNDING_PENDING}:{component_key}"
... (the full list in P3_CALCULATION_ENGINE_PLAN.md §2.1)

# ── exception codes (nz_result["exceptions"]; block APPROVAL in P4, not calculation) ──
EXC_MIN_WAGE_FAIL = "NZ_MIN_WAGE_FAIL"
EXC_MIN_WAGE_UNDETERMINABLE = "NZ_MIN_WAGE_UNDETERMINABLE"
EXC_CS_SHORTFALL = "NZ_CS_SHORTFALL"

def keyed(code: str, *parts) -> str:
    """'NZ_TABLE_EMPTY' + ('paye_main_method',) -> 'NZ_TABLE_EMPTY:paye_main_method'."""
```

### 5.2 `jurisdictions/new_zealand/pack.py` (NEW)
```python
"""The only reader of New Zealand pack rows inside the engine (pure)."""
from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from typing import Callable

from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import errors as E

ZERO = Decimal("0"); ONE = Decimal("1"); HUNDRED = Decimal("100")
CENT = Decimal("0.01")
PENDING_MARK = "[PENDING G1]"
FREQUENCY_ALIASES = {"WEEKLY": "WEEKLY", "FORTNIGHTLY": "FORTNIGHTLY", "FOURWEEKLY": "FOUR_WEEKLY",
                     "FOUR_WEEKLY": "FOUR_WEEKLY", "MONTHLY": "MONTHLY"}
SL_THRESHOLD_KEY = {"WEEKLY": "nz_sl_threshold_weekly", "FORTNIGHTLY": "nz_sl_threshold_fortnightly",
                    "FOUR_WEEKLY": "nz_sl_threshold_four_weekly", "MONTHLY": "nz_sl_threshold_monthly"}

# rounding vocabulary: rule -> (unit, mode). The rule TEXT comes from the pack; only the
# vocabulary lives here (it is a parser, not statutory content).
ROUNDING_RULES = {
    "NEAREST_CENT_HALF_UP": (CENT, ROUND_HALF_UP),  "HALF_EVEN_CENT": (CENT, ROUND_HALF_EVEN),
    "DOWN_CENT": (CENT, ROUND_DOWN),                "UP_CENT": (CENT, ROUND_UP),
    "NEAREST_DOLLAR_HALF_UP": (ONE, ROUND_HALF_UP), "DOWN_DOLLAR": (ONE, ROUND_DOWN),
}

def dec(value) -> Decimal:              # None/"" -> ZERO; else Decimal(str(value))
def field(row, name):                   # row.get(name) if dict else getattr(row, name, None)
def upper(value) -> str:                # str(value).strip().upper() or ""
def as_date(value) -> date | None:      # date passthrough; ISO string[:10] -> date; else None
def normalise_frequency(value) -> str:  # FREQUENCY_ALIASES.get(upper(value).replace(" ","").replace("-",""), "")
def money(value: Decimal) -> str:       # format(value.quantize(CENT), "f") - for nz_result only
def in_window(start, end, on) -> bool:  # (start is None or start <= on) and (end is None or end >= on)


class NzPack:
    def __init__(self, rate_map, slabs, organization_id, as_of: date | None):
        self.rate_map = rate_map or {}; self.slabs = list(slabs or [])
        self.organization_id = organization_id; self.as_of = as_of
        self.rounding_events: list = []; self._used: dict = {}

    def block(self, key, reason): raise E.NZCalculationBlockedError(key, reason, self.organization_id)

    def _note(self, kind, ident, row):
        # record each row once: {"kind","id","effectiveFrom","effectiveTo"} keyed by (kind, ident)

    def _signed(self, ident, label):
        # if PENDING_MARK in (label or ""): self.block(E.PACK_UNSIGNED, f"{ident} is not signed (gate G1)")

    def row(self, key, required=True):
        # row = self.rate_map.get(key)
        # if row is None or not in_window(as_date(field(row,"effective_from")), as_date(field(row,"effective_to")), self.as_of):
        #     if required: self.block(E.keyed(E.ROW_MISSING, key), "no parameter row in force on the payday")
        #     return None
        # self._signed(key, field(row, "label")); self._note("rate", key, row); return row

    def amount(self, key) -> Decimal:
        # v = field(self.row(key), "flat_amount"); None -> block ROW_MISSING:key ("no amount"); return dec(v)

    def pct(self, key) -> Decimal:      # same as amount(): percentages are stored as percent numbers

    def text(self, key, allowed=None) -> str:
        # v = upper(field(self.row(key), "text_value"))
        # if not v or v == content.PENDING: block ROW_MISSING:key ("value is PENDING_G1")
        # if allowed and v not in allowed: block ROW_MISSING:key (f"{v!r} not one of {allowed}")

    def text_list(self, key) -> list[str]:
        # [part.strip().upper() for part in self.text(key).split(",") if part.strip()]

    def rounder(self, key) -> Callable[[Decimal], Decimal]:
        # rule = upper(field(self.row(key), "text_value"))
        # if rule not in ROUNDING_RULES: block keyed(ROUNDING_PENDING, key)
        # unit, mode = ROUNDING_RULES[rule]
        # def _round(value):
        #     after = (value / unit).quantize(ONE, rounding=mode) * unit
        #     self.rounding_events.append({"key": key, "rule": rule, "before": str(value), "after": str(after)})
        #     return after
        # return _round

    def table(self, rule_type, table_name, required=True) -> list:
        # rows = [r for r in self.slabs if upper(field(r,"rule_type")) == rule_type
        #         and in_window(as_date(field(r,"effective_from")), as_date(field(r,"effective_to")), self.as_of)]
        # if not rows and required: block keyed(TABLE_EMPTY, table_name), f"{table_name} has no rows (gate ...)"
        # for r in rows: self._signed(f"{rule_type}:{field(r,'id')}", field(r, "rate_label")); self._note("slab", ..., r)
        # return sorted(rows, key=lambda r: (dec(field(r,"min_amount")), field(r,"sort_order") or 0))

    def used(self) -> list:             # sorted list of noted rows (for packHash and trace.rowsUsed)
```

### 5.3 `jurisdictions/new_zealand/hashing.py` (NEW)
```python
"""Canonical JSON + SHA-256 for New Zealand snapshots (NZ-005, NZ-022)."""
import hashlib, json
from datetime import date, datetime
from decimal import Decimal

def _default(o):        # Decimal -> format(o.normalize(), "f"); date/datetime -> isoformat(); set -> sorted list
def canonical(obj) -> str:  json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default)
def sha256(obj) -> str:     hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()

INPUT_PROFILE_FIELDS = ("id", "tax_code", "tax_code_source", "ird_number_state", "residency_status",
                        "tailored_rate_pct", "tailored_valid_from", "tailored_valid_to",
                        "sl_certificate_type", "sl_certificate_rate_pct", "sl_certificate_valid_from",
                        "sl_certificate_valid_to", "min_wage_category", "effective_from", "status")
INPUT_KS_FIELDS = ("id", "membership_state", "employee_rate_pct", "employer_rate_pct", "reduction_from",
                   "reduction_to", "employer_matches_reduction", "suspension_from", "suspension_to",
                   "esct_rate_pct", "esct_basis", "esct_basis_amount", "employer_contribution_treatment",
                   "settlement_destination", "effective_from", "status")
INPUT_NOTICE_FIELDS = ("id", "deduction_type", "notice_id", "version", "amount_per_payday", "rate_pct",
                       "effective_from", "effective_to", "status")
# NOTE: ird_vault_id, declaration_ref, evidence refs, complying_fund_ref and DOB are NOT hashed inputs
# that could leak; DOB enters only as the computed age in the KiwiSaver trace.

def pick(row, fields) -> dict | None
def input_document(ctx, frequency, components) -> dict
    # {"gross","basic","overtime","components","frequency","payDate","paymentKind",
    #  "employer": pick(... ("id","status","effective_from")),
    #  "taxProfile": pick(..., INPUT_PROFILE_FIELDS), "kiwisaver": pick(..., INPUT_KS_FIELDS),
    #  "notices": [pick(n, INPUT_NOTICE_FIELDS) for n in sorted(notices, key=id)],
    #  "workPatternId", "accumulators", "hours", "hoursSource", "ageAtPayday"}
def hashes(input_doc, used_rows, result_without_hashes) -> dict
    # {"inputHash": sha256(input_doc), "packHash": sha256(used_rows), "resultHash": sha256(result_without_hashes)}
```

### 5.4 `jurisdictions/new_zealand/components.py` (NEW)
```python
"""Pay components and per-obligation bases (no universal taxable gross)."""
from ...countries import new_zealand_content as content
from .pack import NzPack, ZERO, dec, field, upper
from . import errors as E

BASES = ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "MIN_WAGE")
INCLUDED, EXCLUDED, LUMP_SUM_PATH, REVIEW = content.TREATMENTS

def pay_components(ctx, pack: NzPack) -> list[tuple[str, Decimal]]:
    # named = {upper(k): dec(v) for k, v in (ctx.nz_components or {}).items()}
    # unknown = set(named) - set(content.NZ_COMPONENTS) -> block COMPONENTS_INVALID
    # amounts = {"SALARY": named.get("SALARY", dec(ctx.basic)), "OVERTIME": named.get("OVERTIME", dec(ctx.overtime))}
    # for name in NZ_COMPONENTS minus {SALARY, OVERTIME, OTHER_EARNINGS}: amounts[name] = named.get(name, ZERO)
    # other = named.get("OTHER_EARNINGS", dec(ctx.gross) - sum(amounts.values()))
    # any amount < 0 or other < 0 -> block COMPONENTS_INVALID ("components exceed gross" / "negative")
    # return [(n, a) for n in NZ_COMPONENTS if (a := {**amounts, "OTHER_EARNINGS": other}[n]) > ZERO]

def earning_classes(pack) -> dict:
    # rows = pack.table(content.NZ_EARNING_CLASS_RULE, "earning_classes")
    # return {(upper(tax_regime), upper(filing_status)): upper(assessment_basis) for row in rows}

def obligation_base(obligation, components, classes, pack) -> dict:
    # base, lines = ZERO, []
    # for component, amount in components:
    #     t = classes.get((obligation, component))
    #     t is None                      -> block keyed(EARNING_CLASS_MISSING, obligation, component)
    #     t == REVIEW                    -> block keyed(EARNING_CLASS_REVIEW, obligation, component)   (amount > 0 here)
    #     t == LUMP_SUM_PATH             -> block LUMP_SUM_UNSUPPORTED (P6 changes this branch)
    #     counted = amount if t == INCLUDED else ZERO
    #     base += counted; lines.append({"component", "amount", "treatment": t, "counted"})
    # return {"base": base, "lines": lines}
```

### 5.5 `jurisdictions/new_zealand/paye.py` (NEW)
```python
"""PAYE (spec §3): tax-code routing and the MAIN / SECONDARY / ND / STC branches."""
from ...countries import new_zealand_content as content
from .pack import NzPack, ZERO, HUNDRED, dec, field, upper, as_date, in_window
from . import errors as E

ANNUALISE_BANDS = "ANNUALISE_BANDS"
MAIN, SECONDARY, SPECIAL = "MAIN", "SECONDARY", "SPECIAL"

def resolve_tax_code(profile, pack) -> TaxCode:
    # rows = {upper(field(r,"filing_status")): r for r in pack.table(content.NZ_TAX_CODE_RULE, "tax_codes")}
    # code = upper(field(profile, "tax_code")); row = rows.get(code)
    # row None -> block TAX_CODE_UNSUPPORTED (f"tax code {code!r} is not in the catalogue")
    # assessment_basis == "REFUSED" -> block keyed(TAX_CODE_REFUSED, code) with content.NZ_DEFERRED text
    # state = upper(field(profile,"ird_number_state"))
    # if state in ("MISSING","INVALID") and code != "ND": block TAX_CODE_UNSUPPORTED ("IRD number state requires ND")
    # if code == "ND" and upper(field(profile,"tax_code_source")) != "NO_NOTIFICATION": block TAX_CODE_UNSUPPORTED
    # return TaxCode(code, upper(tax_regime), upper(tax_column) == "SL", upper(tax_table_number) == "IETC")

def band_tax(annual: Decimal, bands: list) -> tuple[Decimal, list]:
    # total, steps = ZERO, []
    # for b in bands (sorted by min): lo, hi, rate = dec(min), (dec(max) if max is not None else None), dec(rate_pct)
    #     if annual <= lo: break
    #     part = (min(annual, hi) if hi is not None else annual) - lo
    #     total += part * rate / HUNDRED; steps.append({"step": f"band {lo}-{hi or '∞'} @ {rate}%", "value": str(part*rate/HUNDRED)})
    # return total, steps

def ietc_credit(annual, rows, pack) -> Decimal:
    # sorted rows must be contiguous (row[i].max == row[i+1].min) else block keyed(TABLE_EMPTY, "ietc_parameters")
    # band = first row with lo < annual <= hi (hi None = ∞); none -> ZERO
    # return max(dec(flat_amount) - (annual - lo) * dec(rate_pct) / HUNDRED, ZERO)

def calculate_paye(gross, code: TaxCode, profile, frequency, pay_date, pack) -> PayeResult:
    # rnd = pack.rounder("nz_paye_rounding"); steps = [{"step": "taxCode", "value": code.code}]
    # if code.code == "STC":
    #     window = in_window(as_date(tailored_valid_from), as_date(tailored_valid_to), pay_date) else block STC_OUT_OF_WINDOW
    #     return PayeResult(rnd(gross * dec(tailored_rate_pct) / HUNDRED), "STC", None, steps)
    # if code.code == "ND":
    #     row = single(pack.table(content.NZ_ND_RATE_RULE, "paye_nd_rate"))
    #     return PayeResult(rnd(gross * dec(rate_pct) / HUNDRED), "ND", None, steps)
    # if code.income_class == SECONDARY:
    #     base_code = code.code.removesuffix(" SL")
    #     row = match filing_status == base_code in pack.table(content.NZ_SECONDARY_RATE_RULE, "paye_secondary_rates")
    #           (none -> block keyed(TABLE_EMPTY, "paye_secondary_rates"))
    #     return PayeResult(rnd(gross * dec(rate_pct) / HUNDRED), "SECONDARY", None, steps)
    # # MAIN
    # methods = [r for r in pack.table(content.NZ_PAYE_METHOD_RULE, "paye_main_method") if upper(filing_status) == frequency]
    # len != 1 -> block keyed(ROW_MISSING, "paye_main_method", frequency)
    # upper(tax_formula) != ANNUALISE_BANDS -> block keyed(ROW_MISSING, "paye_main_method", frequency) ("unknown method")
    # factor = dec(flat_amount); annual = gross * factor
    # tax, band_steps = band_tax(annual, pack.table(content.NZ_PAYE_BAND_RULE, "paye_bands"))
    # if code.independent_earner: tax = max(tax - ietc_credit(annual, pack.table(content.NZ_IETC_RULE, "ietc_parameters"), pack), ZERO)
    # return PayeResult(rnd(tax / factor), "MAIN", factor, steps + band_steps)
```

### 5.6 `jurisdictions/new_zealand/acc_earner_levy.py` (NEW)
```python
"""ACC earner levy (spec §6, NZ-013): capped by a replayable year-to-date accumulator."""
OBLIGATION = "ACC_LIABLE_EARNINGS"

def calculate_levy(acc_base, accumulators, pack) -> AccResult:
    # if not accumulators or OBLIGATION not in accumulators: block ACC_ACCUMULATOR_MISSING
    # ytd = dec(accumulators[OBLIGATION]); cap = pack.amount("nz_acc_max_liable_earnings")
    # liable = min(acc_base, max(cap - ytd, ZERO))
    # levy = pack.rounder("nz_acc_rounding")(liable * pack.pct("nz_acc_earner_levy_rate") / HUNDRED)
    # return AccResult(liable, levy, cap, ytd, ytd + liable, ytd < cap < ytd + acc_base, ytd >= cap, steps)
```

### 5.7 `jurisdictions/new_zealand/student_loan.py` (NEW)
```python
"""Student-loan deductions (spec §5)."""
NIL, RATE = "NIL_DEDUCTION", "SPECIAL_DEDUCTION_RATE"

def _certificate(profile, pay_date):
    # t = upper(sl_certificate_type); if not t: return None
    # if not sl_certificate_ref or not sl_certificate_valid_from: raise later as SL_CERTIFICATE_INVALID
    # return t if in_window(valid_from, valid_to, pay_date) else None

def _extras(base, notices, pay_date, rnd):
    # Σ for n in notices if deduction_type == "STUDENT_LOAN_EXTRA" and status == "APPROVED"
    #     and in_window(effective_from, effective_to, pay_date):
    #     rnd(dec(amount_per_payday)) if amount_per_payday is not None else rnd(base * dec(rate_pct) / HUNDRED)

def calculate_student_loan(base, code, profile, frequency, pay_date, notices, pack) -> SlResult:
    # rnd = pack.rounder("nz_sl_rounding"); rate = pack.pct("nz_sl_rate")
    # cert = _certificate(profile, pay_date)
    # if cert == NIL:  standard, basis, threshold = ZERO, "NIL", None
    # elif cert == RATE: standard, basis = rnd(base * dec(sl_certificate_rate_pct) / HUNDRED), "CERTIFICATE"
    # elif not code.student_loan: standard, basis = ZERO, "NONE"
    # elif code.income_class == "MAIN":
    #     threshold = pack.amount(SL_THRESHOLD_KEY[frequency])
    #     standard, basis = rnd(max(base - threshold, ZERO) * rate / HUNDRED), "MAIN_THRESHOLD"
    # else:  # SECONDARY
    #     pack.text("nz_sl_secondary_basis", allowed=("WHOLE_PAYMENT",))
    #     standard, basis = rnd(base * rate / HUNDRED), "WHOLE_PAYMENT"
    # extra = _extras(base, notices, pay_date, rnd)
    # return SlResult(standard + extra, standard, extra, basis, threshold, steps)
```

### 5.8 `jurisdictions/new_zealand/esct.py` (NEW)
```python
"""Employer superannuation contribution tax (spec §4)."""
def band_rate(amount, bands) -> Decimal:
    # first band with lo < amount <= hi (hi None = ∞); amount <= 0 -> first band's rate
def resolve_esct_rate(election, pack) -> dict:
    # bands = pack.table(content.NZ_ESCT_BAND_RULE, "esct_bands")
    # rate, basis_amount = esct_rate_pct, esct_basis_amount; either None -> block ESCT_RATE_UNRESOLVED
    # upper(esct_basis) not in content.ESCT_BASES -> block ESCT_RATE_UNRESOLVED
    # band_rate(dec(basis_amount), bands) != dec(rate) -> block ESCT_RATE_UNRESOLVED ("stored rate disagrees with basis")
    # return {"rate": dec(rate), "basis": upper(esct_basis), "basisAmount": dec(basis_amount), "taxYear": esct_tax_year}
def calculate_esct(employer_gross, rate, pack) -> Decimal:
    # pack.rounder("nz_esct_rounding")(employer_gross * rate / HUNDRED)
```

### 5.9 `jurisdictions/new_zealand/kiwisaver.py` (NEW)
```python
"""KiwiSaver employee deduction and employer contribution (spec §4, NZ-007/008/009)."""
from . import esct as _esct

def age_on(dob, on) -> int:   # on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))

def _zero(status, election=None) -> KsResult

def calculate_kiwisaver(base, election, dob, pay_date, pack) -> KsResult:
    # if election is None: return _zero("NOT_MEMBER")
    # if upper(status) != "ACTIVE" or not in_window(effective_from, effective_to, pay_date): block keyed(PROFILE_NOT_ACTIVE, "kiwisaver")
    # if upper(employer_contribution_treatment) == "PAYE_ALTERNATIVE": block KS_PAYE_ALTERNATIVE_UNSUPPORTED
    # state = upper(membership_state)
    # if state in ("NOT_MEMBER","OPTED_OUT","NOT_ELIGIBLE"): return _zero(state, election)
    # if state == "SAVINGS_SUSPENSION":
    #     if not suspension_ref: block KS_SUSPENSION_UNEVIDENCED
    #     if in_window(suspension_from, suspension_to, pay_date): return _zero("SUSPENDED", election)
    # rnd = pack.rounder("nz_ks_rounding")
    # reduction = bool(reduction_ref) and in_window(reduction_from, reduction_to, pay_date)
    # allowed = [dec(x) for x in pack.text_list("nz_ks_employee_rates")]
    # if reduction: ee_rate = pack.pct("nz_ks_temporary_reduction_rate")
    # elif employee_rate_pct is None: ee_rate = pack.pct("nz_ks_default_rate")
    # else: ee_rate = dec(employee_rate_pct); ee_rate not in allowed -> block KS_RATE_UNSUPPORTED
    # employee = rnd(base * ee_rate / HUNDRED)
    # if dob is None: block KS_AGE_UNKNOWN
    # age = age_on(dob, pay_date)
    # compulsory = pack.amount("nz_ks_employer_min_age") <= age < pack.amount("nz_ks_employer_max_age")
    # minimum = pack.pct("nz_ks_temporary_reduction_rate") if (reduction and employer_matches_reduction) \
    #           else pack.pct("nz_ks_employer_min_rate")
    # if compulsory: er_rate = dec(employer_rate_pct) if employer_rate_pct is not None else minimum
    #               er_rate < minimum -> block KS_EMPLOYER_RATE_BELOW_MINIMUM
    # else:         er_rate = dec(employer_rate_pct) if employer_rate_pct is not None else ZERO   (voluntary only)
    # employer_gross = rnd(base * er_rate / HUNDRED)
    # if employer_gross > 0: esct_info = _esct.resolve_esct_rate(election, pack); esct = _esct.calculate_esct(employer_gross, esct_info["rate"], pack)
    # else: esct_info, esct = None, ZERO
    # return KsResult("CONTRIBUTING", ee_rate, employee, er_rate, employer_gross, esct_info and esct_info["rate"],
    #                 esct, employer_gross - esct, upper(settlement_destination), complying_fund_ref,
    #                 compulsory, reduction, steps)   # steps record age band, not the DOB
```

### 5.10 `jurisdictions/new_zealand/child_support.py` (NEW)
```python
"""Child support (spec §5, NZ-010/011/012): protected net earnings and variation codes."""
SUPPORTED = ("CHILD_SUPPORT",)
OUT_OF_SCOPE = ("COURT_ATTACHMENT", "IRD_DEDUCTION_NOTICE")
TRIGGER_INSUFFICIENT_NET = "INSUFFICIENT_NET"

def _in_force(notices, types, pay_date):   # status APPROVED and in_window(effective_from, effective_to, pay_date)

def calculate_child_support(net_before, notices, pack) -> CsResult:
    # if _in_force(notices, OUT_OF_SCOPE, pack.as_of): block CS_NOTICE_INVALID ("deduction type not supported yet")
    # cs = _in_force(notices, SUPPORTED, pack.as_of)
    # if not cs: return CsResult(ZERO, ZERO, ZERO, net_before, ZERO, None, [], steps)
    # amounts = [dec(amount_per_payday) if not None else net_before * dec(rate_pct) / HUNDRED  (both None -> block CS_NOTICE_INVALID)]
    # required = Σ amounts
    # max_pct, protected_pct = pack.pct("nz_cs_max_deduction_pct"), pack.pct("nz_cs_protected_net_pct")
    # if max_pct + protected_pct != HUNDRED: block keyed(ROW_MISSING, "nz_cs_protected_net_pct") ("inconsistent content")
    # max_allowed = net_before * max_pct / HUNDRED
    # deduction = pack.rounder("nz_cs_rounding")(min(required, max_allowed)); shortfall = required - deduction
    # variation = None
    # if shortfall > ZERO:
    #     rows = pack.table(content.NZ_CS_VARIATION_RULE, "cs_variation_codes")  -> blocks when empty
    #     match = [r for r in rows if upper(tax_formula) == TRIGGER_INSUFFICIENT_NET]; none -> block CS_VARIATION_CODE_MISSING
    #     variation = upper(field(match[0], "filing_status"))
    # return CsResult(deduction, required, max_allowed, net_before - deduction, shortfall, variation,
    #                 [{"noticeId": n.notice_id, "version": n.version, "amount": str(a)} ...], steps)
```

### 5.11 `jurisdictions/new_zealand/deduction_precedence.py` (NEW)
```python
"""Statutory deduction order (NZ-011): an approved country policy, never tenant config."""
STATUTORY = ("PAYE", "ACC_LEVY", "STUDENT_LOAN", "KS_EMPLOYEE", "CHILD_SUPPORT")
TAX_LIKE = ("PAYE", "ACC_LEVY")

def precedence(pack) -> list[str]:
    # order = pack.text_list("nz_deduction_precedence")       (PENDING -> ROW_MISSING raised by text())
    #   -> re-raise as PRECEDENCE_PENDING for a clearer key: wrap in try/except NZCalculationBlockedError
    # sorted(order) != sorted(STATUTORY) -> block PRECEDENCE_PENDING ("must name every statutory deduction once")
    # any(order.index("CHILD_SUPPORT") < order.index(t) for t in TAX_LIKE) -> block PRECEDENCE_PENDING
    # return order

def before(order, item) -> list[str]:   # order[:order.index(item)]
```

### 5.12 `jurisdictions/new_zealand/minimum_wage.py` (NEW)
```python
"""Minimum-wage test (spec §7, NZ-015): reports, never adjusts pay, never blocks the calculation."""
FLOOR_KEY = {"ADULT": "nz_min_wage_adult", "STARTING_OUT": "nz_min_wage_starting_out",
             "TRAINING": "nz_min_wage_training"}

def check_minimum_wage(base, hours, hours_source, category, pack) -> MinWageResult:
    # cat = upper(category)
    # if not cat:                     return UNDETERMINABLE ("no minimum-wage category recorded")
    # if cat == "EXEMPTION_PERMIT":   return UNDETERMINABLE ("exemption permit rule not signed")
    # if hours is None or dec(hours) <= ZERO: return UNDETERMINABLE ("paid hours unknown")
    # floor = pack.amount(FLOOR_KEY[cat]); effective = base / dec(hours)
    # if effective >= floor: return PASS
    # return FAIL(shortfall = floor * dec(hours) - base)
def exception_for(result) -> dict | None:
    # FAIL -> {"code": EXC_MIN_WAGE_FAIL, "shortfall", "floor", "category"}
    # UNDETERMINABLE -> {"code": EXC_MIN_WAGE_UNDETERMINABLE, "reason"}; PASS -> None
```

### 5.13 `engine/countries/new_zealand.py` (REWRITE)
```python
"""New Zealand (ZP-NZ-ENG-001) payday engine — pure, deterministic and fail-closed.

Pipeline (spec §3–§7): guards → components → separate bases → PAYE → ACC levy →
student loan → KiwiSaver/ESCT → precedence → child support → minimum-wage check →
result + trace + hashes. No database, clock, network or settings (NZ-022).
"""
from __future__ import annotations

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import (
    acc_earner_levy as _acc, child_support as _cs, components as _comp, deduction_precedence as _prec,
    hashing as _hash, kiwisaver as _ks, minimum_wage as _mw, paye as _paye, student_loan as _sl)
from app.modules.payroll.engine.jurisdictions.new_zealand import errors as E
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.new_zealand.pack import (
    NzPack, ZERO, as_date, dec, field, in_window, money, normalise_frequency, upper)

__all__ = ["NZCalculationBlockedError", "calculate", "resolve_applicability", "ENGINE_VERSION"]
ENGINE_VERSION = "nz-engine-1"
REGULAR = "REGULAR"

def _active(pack, record, name, pay_date):
    # record None -> block (EMPLOYER_PROFILE_MISSING | TAX_PROFILE_MISSING)
    # upper(status) != "ACTIVE" or not in_window(...) -> block keyed(PROFILE_NOT_ACTIVE, name)

def resolve_applicability(ctx, pack) -> dict:
    # ctx.pay_date None -> block PAY_DATE_MISSING
    # freq = normalise_frequency(ctx.pay_frequency); freq not in pack.text_list("nz_supported_pay_frequencies") -> FREQUENCY_UNSUPPORTED
    # currency = upper(getattr(ctx, "currency", None)); currency and currency != content.CURRENCY -> CURRENCY_UNSUPPORTED
    # _active(pack, ctx.nz_employer_profile, "employer", ctx.pay_date)
    # _active(pack, ctx.nz_tax_profile, "tax_profile", ctx.pay_date)
    # upper(residency_status) != "RESIDENT" -> NON_RESIDENT_UNSUPPORTED
    # code = _paye.resolve_tax_code(ctx.nz_tax_profile, pack)
    # kind = upper(ctx.nz_payment_kind) or REGULAR; kind != REGULAR -> PAYMENT_KIND_UNSUPPORTED
    # return {"frequency": freq, "taxCode": code, "employer": ..., "profile": ..., "paymentKind": kind}

def calculate(ctx: PayrollContext) -> dict:
    # org = ctx.nz_organization_id or getattr(ctx, "organization_id", None)
    # pack = NzPack(ctx.rate_map, ctx.slabs, org, ctx.pay_date)
    # app = resolve_applicability(ctx, pack)
    # comps = _comp.pay_components(ctx, pack); classes = _comp.earning_classes(pack)
    # bases = {o: _comp.obligation_base(o, comps, classes, pack) for o in _comp.BASES}
    # notices = list(ctx.nz_authority_deductions or [])
    # paye = _paye.calculate_paye(bases["PAYE"]["base"], app["taxCode"], app["profile"], app["frequency"], ctx.pay_date, pack)
    # acc  = _acc.calculate_levy(bases["ACC"]["base"], ctx.nz_accumulators, pack)
    # sl   = _sl.calculate_student_loan(bases["STUDENT_LOAN"]["base"], app["taxCode"], app["profile"], app["frequency"], ctx.pay_date, notices, pack)
    # dob  = ctx.nz_date_of_birth or ctx.date_of_birth
    # ks   = _ks.calculate_kiwisaver(bases["KIWISAVER"]["base"], ctx.nz_kiwisaver, dob, ctx.pay_date, pack)
    # order = _prec.precedence(pack)
    # amounts = {"PAYE": paye.paye, "ACC_LEVY": acc.levy, "STUDENT_LOAN": sl.deduction, "KS_EMPLOYEE": ks.employee}
    # gross = dec(ctx.gross)
    # net_before_cs = gross - sum(amounts[i] for i in _prec.before(order, "CHILD_SUPPORT"))
    # net_before_cs < ZERO -> block NEGATIVE_NET
    # cs = _cs.calculate_child_support(net_before_cs, notices, pack)
    # mw = _mw.check_minimum_wage(bases["MIN_WAGE"]["base"], ctx.nz_hours, ctx.nz_hours_source,
    #                             field(app["profile"], "min_wage_category"), pack)
    # exceptions = [e for e in (_mw.exception_for(mw), _cs_exception(cs)) if e]
    # employee_total = sl.deduction + ks.employee + cs.deduction
    # tds = paye.paye + acc.levy
    # net_pay = gross - tds - employee_total
    # result = _assemble(ctx, app, bases, paye, acc, sl, ks, cs, mw, order, exceptions, net_pay, pack)
    # result["hashes"] = _hash.hashes(_hash.input_document(ctx, app["frequency"], comps), pack.used(), result)
    # return {"tds": tds, "nz_employee_total": employee_total, "employer_pension": ks.employer_gross, "nz_result": result}

def _assemble(...) -> dict:   # builds exactly the schema in P3_CALCULATION_ENGINE_PLAN.md §3 using money()
def _cs_exception(cs) -> dict | None:   # shortfall > 0 -> {"code": EXC_CS_SHORTFALL, "shortfall", "variationCode"}
```

### 5.14 Edits to existing files (exact anchors)
| File | Anchor | Edit |
|---|---|---|
| `engine/base.py` | after the last `jp_*` field in `PayrollContext` (~983–1010) | add the 14 `nz_*` fields (P3 plan §1.2) |
| `engine/base.py` | after `jp_result: dict = None` (~1752) | add `nz_result: dict = None` + comment |
| `engine/standard.py` | after `+ deductions.get("jp_employee_total", Decimal("0"))` (~358) | `+ deductions.get("nz_employee_total", Decimal("0"))` with an NZ comment |
| `engine/standard.py` | after `jp_result=deductions.get("jp_result"),` (~644) | `nz_result=deductions.get("nz_result"),` |
| `engine/countries/new_zealand_content.py` | module docstring | document the authority-table row formats (P3 plan §1.3); **no value changes** |
| `tests/test_nz_scaffold.py` | `test_nz_calculation_is_blocked`, `test_every_calculation_mode_is_blocked` | expect an empty ctx to block with a `NZ_*` key and simple mode to still block `NZ_SIMPLE_MODE_UNSUPPORTED` |

`standard.py` already passes `employer_pension` through (line ~423), and the run total already sums `employer_pension` (`service.py` ~26635). **No service change is needed in P3.**

---

## 6. Worked example (illustrative: TEST method and rounding rows, spec bands and rates)

**Inputs**
- Fortnightly payday 2026-04-08, gross = SALARY = 3,000.00, tax code **M SL**.
- KiwiSaver CONTRIBUTING at the default rate; employer at the minimum; ESCT basis 80,730 → 30% band; employee aged 30.
- One child-support notice of 900.00 per payday.
- ACC YTD 0.
- 80 hours, ADULT.

**TEST rows used**
- `NZ_PAYE_METHOD` FORTNIGHTLY = 26 (`ANNUALISE_BANDS`).
- Every rounding rule = `NEAREST_CENT_HALF_UP`.
- Precedence = PAYE, ACC_LEVY, STUDENT_LOAN, KS_EMPLOYEE, CHILD_SUPPORT.
- One `NZ_CS_VARIATION` row (`INSUFFICIENT_NET`, code `TESTV`).

**Calculation**

| Step | Calculation | Result |
|---|---|---|
| Bases | PAYE = ACC = KS = SL = MIN_WAGE = 3,000.00 | |
| Annualised | 3,000 × 26 | 78,000.00 |
| Band tax | 15,600×10.5% = 1,638.00; 37,900×17.5% = 6,632.50; 24,500×30% = 7,350.00 | 15,620.50 |
| PAYE | 15,620.50 / 26 = 600.7884… → round | **600.79** |
| ACC levy | liable 3,000.00 (YTD 0 < cap) × 1.75% | **52.50** |
| Student loan | (3,000 − 928) × 12% | **248.64** |
| KiwiSaver employee | 3,000 × 3.5% | **105.00** |
| KiwiSaver employer gross | 3,000 × 3.5% | **105.00** |
| ESCT | 105.00 × 30% | **31.50**, net employer **73.50** |
| Net before child support | 3,000 − 600.79 − 52.50 − 248.64 − 105.00 | 1,993.07 |
| Child support | required 900.00; max 40% = 797.228; rounding to 797.23 would reach into the protected 60%, so the deduction is floored to **797.22**; shortfall 102.78, variation `TESTV`, exception `NZ_CS_SHORTFALL` | |
| Minimum wage | 3,000 / 80 = 37.50 ≥ 23.95 | PASS |

**Returned to `standard.py`**
- `tds` = 653.29
- `nz_employee_total` = 248.64 + 105.00 + 797.22 = 1,150.86
- `employer_pension` = 105.00
- net pay = 3,000 − 653.29 − 1,150.86 = **1,195.85** (at least the 60% protected net of 1,195.842 ✓; NZ-012)

**Accumulator deltas:** ACC_LIABLE_EARNINGS 3,000.00 · PAYE_GROSS 3,000.00 · PAYE 600.79 · ACC_LEVY 52.50 · KS_GROSS 3,000.00 · KS_EMPLOYEE 105.00 · KS_EMPLOYER_GROSS 105.00 · ESCT 31.50 · STUDENT_LOAN 248.64 · CHILD_SUPPORT 797.22.

Put this example into `test_nz_engine.py` as `test_worked_example_fortnightly_m_sl`, with every figure asserted. It is a design check of the pipeline, **not** an IRD-certified figure (that is the G1 golden test).

---

## 7. Test file skeletons

### `tests/_nz_engine_helpers.py`
```python
TEST_ROUNDING = "NEAREST_CENT_HALF_UP"
TEST_TABLES = {   # clearly fixtures — never copied into new_zealand_content.py
  "NZ_PAYE_METHOD": [("WEEKLY", 52), ("FORTNIGHTLY", 26), ("FOUR_WEEKLY", 13), ("MONTHLY", 12)],
  "NZ_SECONDARY_RATE": [("SB", "10.5"), ("S", "17.5"), ("SH", "30"), ("ST", "33"), ("SA", "39")],
  "NZ_ND_RATE": ["45"],                       # TEST value
  "NZ_IETC": [("0", "24000", "0", "0"), ("24000", "44000", "520", "0"), ("44000", "48000", "520", "13"),
              ("48000", None, "0", "0")],     # TEST band set, contiguous
  "NZ_CS_VARIATION": [("TESTV", "INSUFFICIENT_NET")],
}
def _rate(key, row) -> SimpleNamespace     # from NZ_SCALAR_CONTENT row, label WITHOUT "[PENDING G1]"
def _slab(**kw) -> SimpleNamespace
def test_pack(overrides: dict | None = None, drop_tables=(), pending=False) -> tuple[dict, list]
    # rate_map from content (pending -> keep "[PENDING G1]" labels); rounding rows -> TEST_ROUNDING;
    # nz_deduction_precedence -> "PAYE,ACC_LEVY,STUDENT_LOAN,KS_EMPLOYEE,CHILD_SUPPORT";
    # nz_ks_employer_max_age -> TEST 65; overrides replace flat_amount/text_value per key
    # slabs: bands, tax codes, earning classes from content + TEST_TABLES minus drop_tables
def employer(**kw) -> dict; tax_profile(**kw) -> dict; kiwisaver(**kw) -> dict; notice(**kw) -> dict
def ctx(**overrides) -> PayrollContext      # defaults per P3 plan §5.1
```

### Test modules and function names
| File | Tests |
|---|---|
| `test_nz_engine_pack.py` | `test_row_blocks_when_missing`, `test_row_blocks_when_out_of_window`, `test_pending_label_blocks_even_in_an_active_pack`, `test_text_pending_blocks`, `test_rounder_vocabulary`, `test_rounder_records_events`, `test_unknown_rounding_blocks`, `test_table_empty_blocks_with_table_name`, `test_used_lists_each_row_once`, `test_frequency_aliases` |
| `test_nz_engine_components.py` | `test_default_components_from_basic_overtime_gross`, `test_named_components_override`, `test_unknown_component_blocks`, `test_components_exceeding_gross_block`, `test_each_obligation_has_its_own_base`, `test_review_component_blocks_with_obligation_key`, `test_zero_review_component_is_fine`, `test_lump_sum_path_blocks_until_p6`, `test_missing_classification_blocks` |
| `test_nz_engine_paye.py` | `test_every_supported_code_routes`, `test_refused_codes`, `test_unknown_code_never_maps`, `test_nd_requires_no_notification`, `test_missing_ird_requires_nd`, `test_band_edges[freq,boundary,offset]` (parametrised 4×4×3), `test_me_applies_ietc`, `test_me_without_ietc_blocks`, `test_secondary_rates`, `test_stc_window[before,inside,after]`, `test_paye_main_method_empty_blocks`, `test_acc_ytd_zero`, `test_acc_crossing_cap`, `test_acc_after_cap`, `test_acc_missing_accumulator_blocks`, `test_acc_two_paydays_reach_cap_exactly` |
| `test_nz_engine_deductions.py` | `test_sl_threshold_edges[freq]`, `test_sl_secondary_whole_payment`, `test_sl_certificate_rate_window`, `test_sl_nil_certificate`, `test_sl_extra_notice`, `test_ks_payday_straddle_uses_new_rate`, `test_ks_payday_before_april_blocks`, `test_ks_employee_rate_allowed`, `test_ks_employee_rate_not_allowed`, `test_ks_default_rate`, `test_ks_reduction_window`, `test_ks_employer_matches_reduction_only_when_flagged`, `test_ks_suspension_in_window`, `test_ks_suspension_without_ref_blocks`, `test_ks_sixteen_year_old_gets_employer_contribution`, `test_ks_over_max_age_no_compulsory`, `test_ks_age_unknown_blocks`, `test_ks_employer_below_minimum_blocks`, `test_ks_paye_alternative_refused`, `test_ks_complying_fund_destination`, `test_esct_band_edges`, `test_esct_rate_disagrees_with_basis`, `test_esct_net`, `test_cs_normal`, `test_cs_capped_with_variation_and_exception`, `test_cs_shortfall_without_variation_rows_blocks`, `test_cs_two_notices`, `test_cs_out_of_window_ignored`, `test_cs_court_attachment_blocks`, `test_precedence_pending_blocks`, `test_precedence_not_permutation_blocks`, `test_precedence_child_support_before_tax_blocks` |
| `test_nz_engine_min_wage.py` | `test_adult_at_floor_passes`, `test_adult_below_floor_fails_with_shortfall`, `test_starting_out_floor`, `test_no_category_undeterminable`, `test_exemption_permit_undeterminable`, `test_no_hours_undeterminable`, `test_min_wage_never_changes_pay` |
| `test_nz_engine.py` | `test_worked_example_fortnightly_m_sl`, the guard tests (payday, frequency, FourWeekly, currency, profiles, non-resident, payment kind), `test_standard_strategy_net_equals_nz_result`, `test_tds_is_paye_plus_acc`, `test_employer_pension_is_ks_employer_gross`, `test_simple_mode_still_refused`, `test_shipped_content_blocks_unsigned`, `test_shipped_content_without_pending_blocks_on_empty_tables`, `test_deterministic_result_and_hashes`, `test_input_change_changes_input_hash`, `test_trace_lists_rows_used`, `test_result_holds_no_personal_identifiers`, `test_engine_package_is_pure` (grep) |
| `test_nz_golden.py` | `test_ird_official_examples` (skipped until G1) |

---

## 8. Definition of done (checklist for the reviewer)

- [ ] Every file in §1 exists with the functions in §5. Nothing in `jurisdictions/new_zealand/` imports DB, config, service or models.
- [ ] `grep -rnE "date\.today|datetime\.now|import random|SessionLocal|from app\.config|requests|httpx" engine/countries/new_zealand.py engine/jurisdictions/new_zealand/` returns nothing.
- [ ] `tests/test_nz_content.py::test_nz_engine_code_holds_no_statutory_literal` passes.
- [ ] The worked example (§6) passes to the cent.
- [ ] The shipped pack blocks (`NZ_PACK_UNSIGNED`, then `NZ_TABLE_EMPTY:paye_main_method` once pending is removed).
- [ ] The NZ, JP and engine-wide suites pass, and so does the full backend suite.
- [ ] One local commit on `venu`, not pushed.
