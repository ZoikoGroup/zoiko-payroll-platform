# New Zealand P3: calculation engine (detailed build plan)

Companion to `docs/new_zealand/IMPLEMENTATION_HANDOFF_P3_P10.md`. Read that document's §0 ground rules first; they all apply here. This document describes **every file, function, data shape, rule and test** for Phase 3.

**Scope:** a pure, deterministic, fail-closed `calculate(ctx)` for a REGULAR payday (spec §3–§7). It covers:
- PAYE, including the ACC earner levy;
- student loan;
- KiwiSaver (employee and employer) and ESCT;
- child support;
- deduction precedence;
- the minimum-wage check;
- the full calculation trace.

**Out of scope for P3:**

| Item | Phase |
|---|---|
| Database reads, the hooks and the routes | P4 |
| Lump sums, holiday pay, final pay and corrections | P6 |
| Filing | P8 |

**No migration** in P3.

---

## 1. Inputs available to the engine

### 1.1 Existing `PayrollContext` fields used (`engine/base.py`)
| Field | Line | Notes |
|---|---|---|
| `gross: Decimal` | 39 | total gross for the payslip |
| `basic: Decimal` | 40 | the SALARY component when `nz_components` has none |
| `overtime: Decimal` | 43 | the OVERTIME component when `nz_components` has none |
| `country: str` | 58 | "NZ" |
| `rate_map: dict` | 59 | `component_key -> ContributionRate` row (object or dict) of the **resolved pack** |
| `slabs: list` | 60 | `TaxSlab` rows of the resolved pack |
| `pay_frequency: str` | 202 | platform values `"Weekly" \| "Fortnightly" \| "FourWeekly" \| "Monthly"` (see §2.2 mapping) |
| `period_start`, `period_end` | 537–538 | trace only; **never used for rule selection** |
| `date_of_birth` | 741 | fallback when `nz_date_of_birth` is None |
| `pay_date: date` | 756 | **the payday: the only selection date** (NZ-008) |
| `trace_id` | 1131 | copied into the trace |

### 1.2 New `PayrollContext` fields

Add these right after the `jp_*` block (around line 983). Each needs a comment naming ZP-NZ-ENG-001.

```python
    # New Zealand (ZP-NZ-ENG-001 Phase 3). Supplied by new_zealand_service.calc_inputs
    # (Phase 4); the engine never reads the database.
    nz_employer_profile: object = None        # dict of PayrollNzEmployerProfile columns
    nz_tax_profile: object = None             # dict of PayrollNzEmployeeTaxProfile columns
    nz_kiwisaver: object = None               # dict of PayrollNzKiwiSaverElection columns
    nz_authority_deductions: list = None      # list[dict] of APPROVED PayrollNzAuthorityDeduction rows
    nz_work_pattern: object = None            # dict of PayrollNzWorkPatternVersion columns
    nz_accumulators: dict = None              # {obligation: Decimal} YTD BEFORE this payday
    nz_hours: Decimal = None                  # paid hours this period (minimum-wage test)
    nz_hours_source: str = None               # ATTENDANCE / WORK_PATTERN
    nz_payment_kind: str = None               # None = REGULAR
    nz_date_of_birth: date = None
    nz_components: dict = None                # {"SALARY": Decimal, "OVERTIME": ..., ...}
    nz_organization_id: int = None
    nz_legal_entity_id: int = None
    nz_employee_id: int = None
```

Add to `PayrollResult` next to `jp_result` (around line 1752):
```python
    # New Zealand (ZP-NZ-ENG-001): the whole NZ dict (separate bases, every
    # obligation, accumulator deltas, exceptions and trace). None elsewhere.
    nz_result: dict = None
```

### 1.3 Pack rows the engine reads

**Scalar rows (`rate_map`).** All come from `new_zealand_content.NZ_PARAMETER_KEYS`:

| Key | Kind | Used in |
|---|---|---|
| `nz_supported_pay_frequencies` | text | guards |
| `nz_paye_rounding`, `nz_acc_rounding`, `nz_sl_rounding`, `nz_ks_rounding`, `nz_esct_rounding`, `nz_cs_rounding` | text | each module's rounder |
| `nz_acc_earner_levy_rate`, `nz_acc_max_liable_earnings` | pct_total, amount | ACC |
| `nz_ks_employee_rates`, `nz_ks_temporary_reduction_rate`, `nz_ks_default_rate`, `nz_ks_employer_min_rate`, `nz_ks_employer_min_age`, `nz_ks_employer_max_age`, `nz_ks_rate_selection_basis` | | KiwiSaver |
| `nz_sl_rate`, `nz_sl_threshold_{weekly,fortnightly,four_weekly,monthly}`, `nz_sl_secondary_basis` | | student loan |
| `nz_cs_protected_net_pct`, `nz_cs_max_deduction_pct` | | child support |
| `nz_min_wage_adult`, `nz_min_wage_starting_out`, `nz_min_wage_training` | | minimum wage |
| `nz_deduction_precedence` | text | precedence |

**Table rows (`slabs`, filtered by `rule_type`):**

| rule_type | Shape | Used in |
|---|---|---|
| `NZ_EARNING_CLASS` | `tax_regime`=obligation, `filing_status`=component, `assessment_basis`=treatment | bases |
| `NZ_TAX_CODE` | `filing_status`=code, `tax_regime`=MAIN/SECONDARY/SPECIAL, `assessment_basis`=SUPPORTED/REFUSED, `tax_column`="SL"\|None, `tax_table_number`="IETC"\|None | code routing |
| `NZ_PAYE_BAND` | `min_amount`, `max_amount` (None = open), `rate_pct` | main PAYE |
| `NZ_ESCT_BAND` | same | ESCT |
| `NZ_PAYE_METHOD` | one per frequency: `filing_status`=frequency, `flat_amount`=periods per year, `tax_formula`=`ANNUALISE_BANDS` | main PAYE |
| `NZ_SECONDARY_RATE` | `filing_status`=SB/S/SH/ST/SA, `rate_pct` | secondary PAYE |
| `NZ_ND_RATE` | one row, `rate_pct` | ND |
| `NZ_IETC` | `min_amount`, `max_amount`, `flat_amount`=annual credit, `rate_pct`=abatement % above `min_amount` | ME codes |
| `NZ_CS_VARIATION` | `filing_status`=code, `rate_label`=meaning, `tax_formula`=trigger (`INSUFFICIENT_NET`) | child support |

The `NZ_PAYE_METHOD`, `NZ_SECONDARY_RATE`, `NZ_ND_RATE`, `NZ_IETC` and `NZ_CS_VARIATION` tables are **empty in the shipped pack**. Every path that needs one blocks with `NZ_TABLE_EMPTY:<table>`. Record these row formats in the `new_zealand_content.py` module docstring (documentation only; no value changes).

---

## 2. File-by-file build

### 2.1 `engine/jurisdictions/new_zealand/errors.py`: add the reason-code constants
Keep the existing class. Add module constants. They are the `key` argument of `NZCalculationBlockedError`, and tests assert on them:

```python
PACK_UNSIGNED = "NZ_PACK_UNSIGNED"
TABLE_EMPTY = "NZ_TABLE_EMPTY"               # + ":<table name>"
ROW_MISSING = "NZ_ROW_MISSING"               # + ":<component_key>"
PAY_DATE_MISSING = "NZ_PAY_DATE_MISSING"
FREQUENCY_UNSUPPORTED = "NZ_FREQUENCY_UNSUPPORTED"
CURRENCY_UNSUPPORTED = "NZ_CURRENCY_UNSUPPORTED"
EMPLOYER_PROFILE_MISSING = "NZ_EMPLOYER_PROFILE_MISSING"
TAX_PROFILE_MISSING = "NZ_TAX_PROFILE_MISSING"
PROFILE_NOT_ACTIVE = "NZ_PROFILE_NOT_ACTIVE"            # + ":<record>"
NON_RESIDENT_UNSUPPORTED = "NZ_NON_RESIDENT_UNSUPPORTED"
TAX_CODE_UNSUPPORTED = "NZ_TAX_CODE_UNSUPPORTED"
TAX_CODE_REFUSED = "NZ_TAX_CODE_REFUSED"                # + ":<code>"
STC_OUT_OF_WINDOW = "NZ_STC_OUT_OF_WINDOW"
PAYMENT_KIND_UNSUPPORTED = "NZ_PAYMENT_KIND_UNSUPPORTED"
COMPONENTS_INVALID = "NZ_COMPONENTS_INVALID"
EARNING_CLASS_REVIEW = "NZ_EARNING_CLASS_REVIEW"        # + ":<obligation>:<component>"
EARNING_CLASS_MISSING = "NZ_EARNING_CLASS_MISSING"      # + ":<obligation>:<component>"
LUMP_SUM_UNSUPPORTED = "NZ_LUMP_SUM_UNSUPPORTED"        # P6 lifts this
ACC_ACCUMULATOR_MISSING = "NZ_ACC_ACCUMULATOR_MISSING"
KS_RATE_UNSUPPORTED = "NZ_KS_RATE_UNSUPPORTED"
KS_EMPLOYER_RATE_BELOW_MINIMUM = "NZ_KS_EMPLOYER_RATE_BELOW_MINIMUM"
KS_SUSPENSION_UNEVIDENCED = "NZ_KS_SUSPENSION_UNEVIDENCED"
KS_PAYE_ALTERNATIVE_UNSUPPORTED = "NZ_KS_PAYE_ALTERNATIVE_UNSUPPORTED"
KS_AGE_UNKNOWN = "NZ_KS_AGE_UNKNOWN"
ESCT_RATE_UNRESOLVED = "NZ_ESCT_RATE_UNRESOLVED"
SL_CERTIFICATE_INVALID = "NZ_SL_CERTIFICATE_INVALID"
CS_VARIATION_CODE_MISSING = "NZ_CS_VARIATION_CODE_MISSING"
CS_NOTICE_INVALID = "NZ_CS_NOTICE_INVALID"
PRECEDENCE_PENDING = "NZ_PRECEDENCE_PENDING"
ROUNDING_PENDING = "NZ_ROUNDING_PENDING"                # + ":<key>"
NEGATIVE_NET = "NZ_NEGATIVE_NET"

# Exceptions are NOT blocks: they ride on nz_result["exceptions"] and stop run
# APPROVAL in Phase 4 (NZ-015 / NZ-012).
EXC_MIN_WAGE_FAIL = "NZ_MIN_WAGE_FAIL"
EXC_MIN_WAGE_UNDETERMINABLE = "NZ_MIN_WAGE_UNDETERMINABLE"
EXC_CS_SHORTFALL = "NZ_CS_SHORTFALL"
```

Messages must never contain an IRD number, a notice body or a free-text HR note (R13).

### 2.2 `engine/jurisdictions/new_zealand/pack.py` (new): the content accessor
Mirror `japan.py:_Pack` (lines 79–162), as its own module so every sub-module can use it.

```python
ZERO, HUNDRED = Decimal("0"), Decimal("100")
PENDING = "PENDING_G1"
PENDING_MARK = "[PENDING G1]"
FREQUENCY_ALIASES = {"WEEKLY": "WEEKLY", "FORTNIGHTLY": "FORTNIGHTLY",
                     "FOURWEEKLY": "FOUR_WEEKLY", "FOUR_WEEKLY": "FOUR_WEEKLY",
                     "MONTHLY": "MONTHLY"}          # platform "FourWeekly" -> content "FOUR_WEEKLY"

def dec(value) -> Decimal            # None -> ZERO; str/int/float/Decimal -> Decimal(str(value))
def field(row, name)                  # dict or attribute access (rows may be ORM objects or dicts)
def upper(value) -> str               # "" for None
def as_date(value) -> date | None     # accepts date or ISO string
def normalise_frequency(value) -> str # FREQUENCY_ALIASES[upper(value).replace(" ", "").replace("-", "")] else ""

class NzPack:
    def __init__(self, rate_map, slabs, organization_id, as_of): ...
    def block(self, key, reason) -> NoReturn            # raise NZCalculationBlockedError(key, reason, org_id)
    def in_force(self, row, as_of=None) -> bool          # effective_from/to vs payday
    def row(self, key, required=True)                     # missing/out of force -> ROW_MISSING:<key>
                                                          # label contains "[PENDING G1]" -> PACK_UNSIGNED
    def amount(self, key) -> Decimal                      # flat_amount; None -> ROW_MISSING:<key>
    def pct(self, key) -> Decimal                         # flat_amount as a percent number (1.75 = 1.75%)
    def text(self, key, allowed=None) -> str              # text_value upper; PENDING -> ROW_MISSING
    def text_list(self, key) -> list[str]                 # comma list, stripped
    def rounder(self, key) -> Callable[[Decimal], Decimal]
    def table(self, rule_type, table_name, required=True) -> list
        # rows of that rule_type in force on the payday; [] + required -> TABLE_EMPTY:<table_name>;
        # any row whose rate_label contains "[PENDING G1]" -> PACK_UNSIGNED
    def used(self) -> list[dict]                          # every row read (key/rule_type/id/effective_from/label)
                                                          # -> packHash input
```

**Rounding vocabulary.** `rounder(key)` reads the row's text and supports:
- `NEAREST_CENT_HALF_UP`, `DOWN_CENT`, `UP_CENT`;
- `NEAREST_DOLLAR_HALF_UP`, `DOWN_DOLLAR`;
- `HALF_EVEN_CENT`.

`PENDING_G1`, empty or unknown values block `ROUNDING_PENDING:<key>`. Each call appends `{"key", "before", "after", "rule"}` to a shared `rounding_events` list (pass it into `NzPack` or return it). **No module may call `quantize` directly**; only the rounder does (spec §3: "not generic currency rounding").

`row()` treats a pending label as unsigned **even if the pack status is Active**. This defends against an Active pack that was signed incorrectly (JP has no such guard; NZ adds it).

### 2.3 `engine/jurisdictions/new_zealand/components.py` (new): components and bases
```python
def pay_components(ctx, pack) -> list[tuple[str, Decimal]]
```
- `named = {upper(k): dec(v) for k, v in (ctx.nz_components or {}).items()}`.
- An unknown name (not in `content.NZ_COMPONENTS`) blocks `COMPONENTS_INVALID`.
- SALARY = `named.get("SALARY", dec(ctx.basic))`; OVERTIME = `named.get("OVERTIME", dec(ctx.overtime))`; the remaining named components come from `named`, default 0.
- OTHER_EARNINGS = `named.get(...)` or `dec(ctx.gross) - sum(named)`. A negative value blocks `COMPONENTS_INVALID` ("components exceed gross"). Any negative component blocks.
- Returns only the components above zero (order: content `NZ_COMPONENTS`).

```python
def earning_classes(pack) -> dict[(obligation, component), treatment]   # from table NZ_EARNING_CLASS (required)
def obligation_base(obligation, components, classes, pack) -> {"base": Decimal, "lines": [...]}
```
| Treatment | Effect |
|---|---|
| (missing) | `EARNING_CLASS_MISSING:<o>:<c>` |
| `REVIEW` with a non-zero amount | `EARNING_CLASS_REVIEW:<o>:<c>` |
| `LUMP_SUM_PATH` with a non-zero amount | `LUMP_SUM_UNSUPPORTED` (P6 replaces this branch) |
| `INCLUDED` | counted |
| `EXCLUDED` | 0 |

Each line in `lines` is `{"component", "amount", "treatment", "counted"}`.

The bases are computed separately for PAYE, ACC, KIWISAVER, STUDENT_LOAN and MIN_WAGE. **There is no shared "taxable gross"** (spec, "Critical refinements").

### 2.4 `engine/jurisdictions/new_zealand/paye.py` (new)
```python
@dataclass(frozen=True)
class TaxCode:
    code: str; income_class: str          # MAIN / SECONDARY / SPECIAL
    student_loan: bool; independent_earner: bool

def resolve_tax_code(profile, pack) -> TaxCode
```
- Read `NZ_TAX_CODE` (required).
- `code = upper(profile["tax_code"])`.
- Not in the catalogue → `TAX_CODE_UNSUPPORTED`.
- `assessment_basis == REFUSED` → `TAX_CODE_REFUSED:<code>`.
- **Never** map an unknown code to another code.

```python
@dataclass
class PayeResult:
    paye: Decimal; branch: str            # MAIN / SECONDARY / ND / STC
    steps: list; table_version: str | None; period_factor: Decimal | None

def calculate_paye(gross_paye, code, profile, frequency, pay_date, pack) -> PayeResult
```

| Branch | When | Calculation |
|---|---|---|
| MAIN | M, ME, M SL, ME SL | 1. `method = table(NZ_PAYE_METHOD, "paye_main_method")` filtered by `filing_status == frequency`; zero rows blocks `TABLE_EMPTY:paye_main_method`; more than one blocks `ROW_MISSING:paye_main_method:<frequency>` (ambiguous). `tax_formula` must be `ANNUALISE_BANDS`, else block. 2. `annual = gross_paye * method.flat_amount` (`period_factor = flat_amount`). 3. `annual_tax = Σ_band (min(annual, max) - min) * rate/100` over bands with `annual > min` (table `NZ_PAYE_BAND`, `"paye_bands"`). 4. ME codes: `ietc = credit(annual, NZ_IETC rows)` (table required → `TABLE_EMPTY:ietc_parameters`); `annual_tax = max(annual_tax - ietc, 0)`. 5. `paye = rounder("nz_paye_rounding")(annual_tax / period_factor)`. Steps record every intermediate value. |
| SECONDARY | SB, S, SH, ST, SA (+ SL) | Rate row from `NZ_SECONDARY_RATE` where `filing_status == code without " SL"` (table `"paye_secondary_rates"`). `paye = rounder(gross_paye * rate/100)`. |
| ND | ND | One row from `NZ_ND_RATE` (table `"paye_nd_rate"`). The ND path also applies when `ird_number_state` is `MISSING` or `INVALID` **and** `tax_code_source == "NO_NOTIFICATION"`. If the state is MISSING/INVALID but the code is not ND, block `TAX_CODE_UNSUPPORTED` ("IRD number state requires ND"). |
| STC | STC | `profile.tailored_valid_from <= pay_date <= (tailored_valid_to or ∞)`, else `STC_OUT_OF_WINDOW`. `paye = rounder(gross_paye * tailored_rate_pct/100)`. |

The IETC credit is a pure function, `ietc_credit(annual, rows)`:
- Find the band with `min < annual <= max`.
- `credit = flat_amount - (annual - min) * rate_pct/100`, clamped at 0.
- No matching band → credit 0. This is only valid because the rows define the full range; assert there is no gap between consecutive bands, else block `TABLE_EMPTY:ietc_parameters`.

`table_version` = the pack's `pack_id@version`, passed in by `calculate()` from `ctx` (when present) and otherwise `None`.

### 2.5 `engine/jurisdictions/new_zealand/acc_earner_levy.py` (new)
```python
@dataclass
class AccResult:
    liable: Decimal; levy: Decimal; cap: Decimal; ytd_before: Decimal; ytd_after: Decimal
    cap_crossed: bool; cap_reached_before: bool; steps: list

def calculate_levy(acc_base, accumulators, pack) -> AccResult
```
1. `ytd_before`: `accumulators` must contain `"ACC_LIABLE_EARNINGS"`, else block `ACC_ACCUMULATOR_MISSING`. P4 always supplies an explicit 0 for a first payday; the engine never assumes 0 (NZ-013).
2. `cap = pack.amount("nz_acc_max_liable_earnings")`.
3. `liable = min(acc_base, max(cap - ytd_before, 0))`.
4. `levy = rounder("nz_acc_rounding")(liable * pack.pct("nz_acc_earner_levy_rate") / 100)`.
5. `cap_crossed = ytd_before < cap < ytd_before + acc_base`; `cap_reached_before = ytd_before >= cap`.

The levy is **part of the PAYE deduction** (it goes to `tds`) but is reported separately in `nz_result` (§6).

### 2.6 `engine/jurisdictions/new_zealand/student_loan.py` (new)
```python
@dataclass
class SlResult:
    deduction: Decimal; standard: Decimal; extra: Decimal; basis: str   # MAIN_THRESHOLD / WHOLE_PAYMENT / CERTIFICATE / NIL / NONE
    threshold: Decimal | None; steps: list

def calculate_student_loan(sl_base, code, profile, frequency, pay_date, notices, pack) -> SlResult
```
1. Find an in-window certificate: `sl_certificate_type` is set and `sl_certificate_valid_from <= pay_date <= (valid_to or ∞)`.
   - `NIL_DEDUCTION` → standard = 0, basis NIL.
   - `SPECIAL_DEDUCTION_RATE` → `standard = rounder(sl_base * sl_certificate_rate_pct/100)`, basis CERTIFICATE.
   - The type is set but the window is not satisfied → ignore the certificate. The type is set without a ref or valid_from → `SL_CERTIFICATE_INVALID` (the DB CHECK already prevents this; this is defence in depth).
2. Otherwise, if `code.student_loan` is false → standard = 0, basis NONE.
3. MAIN code:
   - `threshold = pack.amount(f"nz_sl_threshold_{freq}")`, where freq is weekly / fortnightly / four_weekly / monthly;
   - `standard = rounder(max(sl_base - threshold, 0) * rate/100)`, basis MAIN_THRESHOLD.
4. SECONDARY code: `pack.text("nz_sl_secondary_basis")` must be `WHOLE_PAYMENT`; `standard = rounder(sl_base * rate/100)`.
5. `extra`: sum `amount_per_payday` (or `sl_base * rate_pct/100`) of APPROVED `STUDENT_LOAN_EXTRA` notices in force on the payday.
6. `deduction = standard + extra`.

The rate comes from `pack.pct("nz_sl_rate")` and the rounder from `nz_sl_rounding`.

### 2.7 `engine/jurisdictions/new_zealand/esct.py` (new)
```python
def band_rate(amount, bands) -> Decimal                  # the rate of the band containing `amount` (min < amount <= max; amount 0 -> first band)
def resolve_esct_rate(election, pack) -> {"rate": Decimal, "basis": str, "basis_amount": Decimal, "tax_year": str}
```
- `bands = pack.table(NZ_ESCT_BAND, "esct_bands")`.
- `basis_amount = election["esct_basis_amount"]` and `rate = election["esct_rate_pct"]`; either missing → `ESCT_RATE_UNRESOLVED`.
- `band_rate(basis_amount) != rate` → `ESCT_RATE_UNRESOLVED` (the stored rate disagrees with its basis).
- `esct_basis` must be in `content.ESCT_BASES`.

```python
def calculate_esct(employer_gross, rate, pack) -> Decimal   # rounder("nz_esct_rounding")(employer_gross * rate/100)
```

### 2.8 `engine/jurisdictions/new_zealand/kiwisaver.py` (new)
```python
@dataclass
class KsResult:
    status: str                    # CONTRIBUTING / NOT_MEMBER / OPTED_OUT / SUSPENDED / NOT_ELIGIBLE
    employee_rate: Decimal | None; employee: Decimal
    employer_rate: Decimal | None; employer_gross: Decimal; esct_rate: Decimal | None
    esct: Decimal; employer_net: Decimal; destination: str | None; complying_fund_ref: str | None
    compulsory_employer: bool; reduction_applied: bool; steps: list

def age_on(dob, on) -> int
def calculate_kiwisaver(ks_base, election, dob, pay_date, pack) -> KsResult
```

1. **No election.** `election is None` → status NOT_MEMBER, everything 0. P4 preflight flags a missing election separately, so the engine does not block.
2. **Election validity.** It must be ACTIVE and in force on the payday, else `PROFILE_NOT_ACTIVE:kiwisaver`. `employer_contribution_treatment == PAYE_ALTERNATIVE` → `KS_PAYE_ALTERNATIVE_UNSUPPORTED`.
3. **Membership states.**
   - `NOT_MEMBER`, `OPTED_OUT`, `NOT_ELIGIBLE` → zeros with that status.
   - `SAVINGS_SUSPENSION`: suspended only if `suspension_ref` is set and `suspension_from <= pay_date <= (suspension_to or ∞)`, giving status SUSPENDED and zeros. If the dates don't cover the payday, it is treated as CONTRIBUTING. A missing `suspension_ref` blocks `KS_SUSPENSION_UNEVIDENCED`. **Never infer suspension from a zero rate** (NZ-009).
4. **Employee rate** (CONTRIBUTING):
   - `rates = [Decimal(x) for x in pack.text_list("nz_ks_employee_rates")]`;
   - `reduction_applied = reduction_ref and reduction_from <= pay_date <= (reduction_to or ∞)`;
   - with a reduction applied: `rate = pack.pct("nz_ks_temporary_reduction_rate")`;
   - otherwise, if `employee_rate_pct` is None: `rate = pack.pct("nz_ks_default_rate")`;
   - otherwise: `rate = employee_rate_pct`, which must be in `rates`, else `KS_RATE_UNSUPPORTED`;
   - `employee = rounder("nz_ks_rounding")(ks_base * rate/100)`.
5. **Compulsory employer contribution:**
   - `dob` missing → `KS_AGE_UNKNOWN`;
   - `age = age_on(dob, pay_date)`; `min_age = pack.amount("nz_ks_employer_min_age")`;
   - `max_age = pack.amount("nz_ks_employer_max_age")` blocks `ROW_MISSING` in the shipped pack, which is intended (D-2);
   - `compulsory = min_age <= age < max_age` (exact boundary semantics from the G1 sign-off; document the choice in the trace).
6. **Employer rate:**
   - `minimum = pack.pct("nz_ks_employer_min_rate")`;
   - with a reduction applied and `employer_matches_reduction`: `minimum = reduction rate` ("employer may match an active temporary reduction where permitted");
   - `employer_rate = election.employer_rate_pct or minimum`;
   - `employer_rate < minimum` while compulsory → `KS_EMPLOYER_RATE_BELOW_MINIMUM`;
   - not compulsory → employer contribution = 0 unless `employer_rate_pct` is set explicitly (a voluntary contribution).
7. **Amounts:**
   - `employer_gross = rounder(ks_base * employer_rate/100)`;
   - `esct_rate = resolve_esct_rate(election, pack)["rate"]` (only when `employer_gross > 0`);
   - `esct = calculate_esct(employer_gross, esct_rate, pack)`;
   - `employer_net = employer_gross - esct`.
8. **Destination:** `settlement_destination` (+ `complying_fund_ref`), returned separately (NZ-007).

**Payday rule (NZ-008).** Every pack lookup uses `pack.as_of = ctx.pay_date`, so a period from 25 March to 7 April with payday 8 April uses the 1 April rows. A payday of 31 March 2026 finds no row (`content_rows_in_force`) and blocks `ROW_MISSING:nz_ks_default_rate`; this is correct, because pre-April rates are not in the spec.

### 2.9 `engine/jurisdictions/new_zealand/child_support.py` (new)
```python
@dataclass
class CsResult:
    deduction: Decimal; required: Decimal; max_allowed: Decimal; protected_net: Decimal
    shortfall: Decimal; variation_code: str | None; notices: list; steps: list

def calculate_child_support(net_before, notices, pack) -> CsResult
```
1. `cs = [n for n in notices if n.deduction_type == "CHILD_SUPPORT" and status == "APPROVED" and in force on payday]`.
2. Each needs `amount_per_payday` (a `rate_pct` notice uses `net_before * rate_pct/100`), else `CS_NOTICE_INVALID`.
3. `required = Σ amounts`.
4. `max_allowed = net_before * pack.pct("nz_cs_max_deduction_pct")/100`; `protected_net = net_before * pack.pct("nz_cs_protected_net_pct")/100`.
5. If the two do not sum to `net_before`, block `ROW_MISSING:nz_cs_protected_net_pct` (inconsistent content).
6. `deduction = rounder("nz_cs_rounding")(min(required, max_allowed))`; `shortfall = required - deduction`.
7. If `shortfall > 0`:
   - `rows = pack.table(NZ_CS_VARIATION, "cs_variation_codes")` (required → blocks when empty, `CS_VARIATION_CODE_MISSING`);
   - pick the row with `tax_formula == "INSUFFICIENT_NET"`; none → `CS_VARIATION_CODE_MISSING`;
   - set `variation_code`;
   - add an exception `{code: EXC_CS_SHORTFALL, shortfall, variation_code}`.
8. Notices carry only `{"noticeId", "version", "amount"}` into the result, never other notice content (NZ-025).

`COURT_ATTACHMENT` and `IRD_DEDUCTION_NOTICE` types are **not** handled in P3. If one is APPROVED and in force on the payday, block `CS_NOTICE_INVALID` ("deduction type not supported yet"). A notice is never silently skipped.

### 2.10 `engine/jurisdictions/new_zealand/deduction_precedence.py` (new)
```python
STATUTORY = ("PAYE", "ACC_LEVY", "STUDENT_LOAN", "KS_EMPLOYEE", "CHILD_SUPPORT")
def precedence(pack) -> list[str]
```
- `order = pack.text_list("nz_deduction_precedence")`; `PENDING_G1` → `PRECEDENCE_PENDING`.
- It must be a permutation of `STATUTORY`, else `PRECEDENCE_PENDING` ("precedence must name every statutory deduction once").
- The pipeline applies the deductions in this order to compute `net_before` for child support. P3 requires that CHILD_SUPPORT comes **after** every tax-like item; otherwise block. In this way, configurable deduction order can never override protected earnings (NZ-011).
- Voluntary deductions are outside the engine and always come after.

### 2.11 `engine/jurisdictions/new_zealand/minimum_wage.py` (new)
```python
@dataclass
class MinWageResult:
    status: str               # PASS / FAIL / UNDETERMINABLE / NOT_APPLICABLE
    effective_rate: Decimal | None; floor: Decimal | None; shortfall: Decimal | None; category: str | None
    hours: Decimal | None; hours_source: str | None; steps: list

def check_minimum_wage(min_wage_base, hours, hours_source, category, pack) -> MinWageResult
```

| Situation | Status |
|---|---|
| `category is None` | UNDETERMINABLE ("no minimum-wage category recorded"); never inferred from age (§7) |
| `category == EXEMPTION_PERMIT` | UNDETERMINABLE ("exemption permit needs signed rule") |
| `hours is None or hours <= 0` | UNDETERMINABLE |
| `effective = min_wage_base / hours` (no rounding: comparison only) is ≥ the floor | PASS |
| below the floor | FAIL, `shortfall = floor*hours - min_wage_base` |

The floor is the row for the category (ADULT, STARTING_OUT or TRAINING; `nz_min_wage_*`).

FAIL and UNDETERMINABLE add `{code, ...}` to the exceptions. **They never block the calculation and never adjust pay** (NZ-015: "does not silently rewrite agreed remuneration").

### 2.12 `engine/countries/new_zealand.py`: replace the stub
```python
ENGINE_VERSION = "nz-engine-1"
PAYMENT_REGULAR = "REGULAR"

def resolve_applicability(ctx, pack) -> dict
def calculate(ctx: PayrollContext) -> dict
```

**`resolve_applicability`** (each failure is a block):
1. `ctx.pay_date` → `PAY_DATE_MISSING`.
2. `freq = normalise_frequency(ctx.pay_frequency)` must be in `pack.text_list("nz_supported_pay_frequencies")` → `FREQUENCY_UNSUPPORTED`.
3. `getattr(ctx, "currency", None)` is set and not NZD → `CURRENCY_UNSUPPORTED`.
4. `nz_employer_profile` → `EMPLOYER_PROFILE_MISSING`; it must be ACTIVE and in force on the payday → `PROFILE_NOT_ACTIVE:employer`. (VERIFIED is checked at approval in P4, not here, so previews still work.)
5. `nz_tax_profile` → `TAX_PROFILE_MISSING`; ACTIVE and in force → `PROFILE_NOT_ACTIVE:tax_profile`.
6. `residency_status != RESIDENT` → `NON_RESIDENT_UNSUPPORTED`.
7. `code = paye.resolve_tax_code(profile, pack)`.
8. `payment_kind = upper(ctx.nz_payment_kind) or REGULAR`; not REGULAR → `PAYMENT_KIND_UNSUPPORTED` (P6 widens this).

It returns `{"frequency", "taxCode", "employer", "profile", "paymentKind"}`.

**`calculate` pipeline**

1. `org = ctx.nz_organization_id or getattr(ctx, "organization_id", None)`; `pack = NzPack(ctx.rate_map, ctx.slabs, org, ctx.pay_date)`.
2. `app = resolve_applicability(ctx, pack)`.
3. `components = pay_components(ctx, pack)`; `classes = earning_classes(pack)`.
4. `bases = {o: obligation_base(o, components, classes, pack) for o in ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "MIN_WAGE")}`.
5. `paye = paye.calculate_paye(bases["PAYE"]["base"], app["taxCode"], app["profile"], app["frequency"], ctx.pay_date, pack)`.
6. `acc = acc_earner_levy.calculate_levy(bases["ACC"]["base"], ctx.nz_accumulators or {}, pack)`.
   - `nz_accumulators=None` means missing and blocks; `{}` is also missing.
7. `sl = student_loan.calculate_student_loan(bases["STUDENT_LOAN"]["base"], app["taxCode"], app["profile"], app["frequency"], ctx.pay_date, ctx.nz_authority_deductions or [], pack)`.
8. `ks = kiwisaver.calculate_kiwisaver(bases["KIWISAVER"]["base"], ctx.nz_kiwisaver, ctx.nz_date_of_birth or ctx.date_of_birth, ctx.pay_date, pack)`.
9. `order = deduction_precedence.precedence(pack)`.
10. `amounts = {"PAYE": paye.paye, "ACC_LEVY": acc.levy, "STUDENT_LOAN": sl.deduction, "KS_EMPLOYEE": ks.employee}`.
11. `net_before_cs = gross - Σ amounts in `order` before CHILD_SUPPORT`.
    - `net_before_cs < 0` → block `NEGATIVE_NET`. This means statutory deductions exceed gross; the specialist must review.
12. `cs = child_support.calculate_child_support(net_before_cs, ctx.nz_authority_deductions or [], pack)`.
13. `mw = minimum_wage.check_minimum_wage(bases["MIN_WAGE"]["base"], ctx.nz_hours, ctx.nz_hours_source, app["profile"].get("min_wage_category"), pack)`.
14. Assemble the result (§3), compute the hashes (§4) and return the **deductions dict** (§2.13).

### 2.13 `engine/standard.py` integration

**Return value from `calculate`** (the "deductions" dict `StandardStrategy.calculate` consumes):
```python
{
  "tds": paye.paye + acc.levy,              # PAYE incl. ACC earner levy -> total_taxes
  "nz_employee_total": sl.deduction + ks.employee + cs.deduction,
  "employer_pension": ks.employer_gross,   # summed into run.total_employer_contribution
                                           # (service.py ~26635 sums i.employer_pension); ESCT is
                                           # INSIDE the gross - never added again
  "nz_result": {...},                      # §3
}
```

**Edits in `standard.py`:**
- In `total_employee_deductions` (after the `jp_employee_total` line, around 358), add `+ deductions.get("nz_employee_total", Decimal("0"))` with an NZ comment. `tds` is already summed above it, so PAYE + ACC is counted once.
- In the `PayrollResult(...)` construction (around line 644), add `nz_result=deductions.get("nz_result"),`.
- Check that `employer_pension=deductions.get("employer_pension", ...)` already exists (line 423); it does, so KiwiSaver employer gross flows to the payslip `employer_pension` column and the run total with **no service change**.
- Net pay is computed by the platform as `gross - total_employee_deductions`. The engine's own `nz_result["netPay"]` must equal it; a test asserts this.

---

## 3. `nz_result` schema (all money as `str` of a 2-dp Decimal; camelCase keys like JP/ZA)

```json
{
  "paymentKind": "REGULAR",
  "taxCode": "M SL", "incomeClass": "MAIN", "frequency": "FORTNIGHTLY",
  "payDate": "2026-04-08",
  "bases": {"PAYE": "...", "ACC": "...", "KIWISAVER": "...", "STUDENT_LOAN": "...", "MIN_WAGE": "..."},
  "baseLines": {"PAYE": [{"component": "SALARY", "amount": "...", "treatment": "INCLUDED", "counted": "..."}], "...": []},
  "obligations": {
    "paye": "...", "accLevy": "...", "payeTotal": "...",
    "studentLoan": "...", "studentLoanStandard": "...", "studentLoanExtra": "...",
    "ksEmployee": "...", "ksEmployerGross": "...", "esct": "...", "ksEmployerNet": "...",
    "childSupport": "..."
  },
  "employeeTotal": "...", "netPay": "...",
  "kiwisaver": {"status": "CONTRIBUTING", "employeeRate": "3.5", "employerRate": "3.5",
                "esctRate": "17.5", "compulsoryEmployer": true, "reductionApplied": false,
                "destination": "INLAND_REVENUE", "complyingFundRef": null},
  "acc": {"liable": "...", "cap": "...", "ytdBefore": "...", "ytdAfter": "...",
          "capCrossed": false, "capReachedBefore": false},
  "studentLoan": {"basis": "MAIN_THRESHOLD", "threshold": "..."},
  "childSupport": {"required": "...", "maxAllowed": "...", "protectedNet": "...",
                   "shortfall": "0.00", "variationCode": null,
                   "notices": [{"noticeId": "CS-001", "version": 1, "amount": "..."}]},
  "minimumWage": {"status": "PASS", "effectiveRate": "...", "floor": "...", "category": "ADULT",
                  "hours": "...", "hoursSource": "WORK_PATTERN"},
  "precedence": ["PAYE", "ACC_LEVY", "STUDENT_LOAN", "KS_EMPLOYEE", "CHILD_SUPPORT"],
  "accumulatorDeltas": {"ACC_LIABLE_EARNINGS": "...", "PAYE_GROSS": "...", "PAYE": "...",
                        "ACC_LEVY": "...", "KS_GROSS": "...", "KS_EMPLOYEE": "...",
                        "KS_EMPLOYER_GROSS": "...", "ESCT": "...", "STUDENT_LOAN": "...",
                        "CHILD_SUPPORT": "..."},
  "exceptions": [],
  "trace": {"traceId": "...", "engineVersion": "nz-engine-1", "tableVersion": "NZ-PAYROLL-2026-27@1.0",
            "periodFactor": "26", "paye": [], "acc": [], "studentLoan": [], "kiwisaver": [],
            "childSupport": [], "minimumWage": [], "roundingEvents": [],
            "rowsUsed": [{"key": "nz_sl_rate", "effectiveFrom": "2026-04-01"}]},
  "hashes": {"inputHash": "...", "packHash": "...", "resultHash": "..."}
}
```

- **Accumulator deltas.** `ACC_LIABLE_EARNINGS` = `acc.liable` (the capped amount, **not** the ACC base). `PAYE_GROSS` = PAYE base. `KS_GROSS` = KiwiSaver base. Everything else is the obligation amount. These are what P4 posts at PAID.
- **No personal data in `nz_result`.** Exclude IRD-number state, dates of birth (age bands only, if needed), notice content and names.

## 4. Determinism and hashes (NZ-005, NZ-022)

- `canonical(obj)`: JSON with `sort_keys=True`, `separators=(",", ":")`, Decimal → `str(d.normalize())` (quantised values as 2-dp strings), date → ISO.
- `inputHash = sha256(canonical({gross, basic, overtime, components, frequency, payDate, taxProfile (whitelisted fields), kiwisaver (whitelisted), notices (id, version, amount, rate), workPattern id, accumulators, hours, paymentKind}))`.
- `packHash = sha256(canonical(pack.used()))`: only the rows actually read.
- `resultHash = sha256(canonical(nz_result without "hashes"))`.
- **Forbidden inside the engine:** `datetime.now`, `date.today`, the `random` module, environment or settings reads, database or session imports, `requests`/`httpx`. A test greps the NZ engine package for these names.

---

## 5. Tests

All tests are pure: build a `PayrollContext` directly; no database.

### 5.1 Fixture helper (`tests/_nz_engine_helpers.py`)
- `test_pack(overrides=None, tables=None)` turns `new_zealand_content` into `rate_map` and `slabs` the way `seed_nz_pack` writes them, but in memory (simple dicts or SimpleNamespace objects):
  - labels have **no** `[PENDING G1]`;
  - rounding rows are filled with `NEAREST_CENT_HALF_UP`;
  - `nz_deduction_precedence` = `"PAYE,ACC_LEVY,STUDENT_LOAN,KS_EMPLOYEE,CHILD_SUPPORT"`;
  - `nz_ks_employer_max_age` = a TEST value;
  - the empty authority tables are filled with clearly labelled **TEST** rows:
    - `NZ_PAYE_METHOD`: 52/26/13/12, `ANNUALISE_BANDS`;
    - `NZ_SECONDARY_RATE`: the band rates;
    - `NZ_ND_RATE`: a TEST rate;
    - `NZ_IETC`: one TEST band set;
    - `NZ_CS_VARIATION`: one `INSUFFICIENT_NET` row.
  - **TEST values are fixtures, not statutory content.** Keep them in the test helper, never in `new_zealand_content.py`.
- `ctx(**overrides)` returns a `PayrollContext` with:
  - `country="NZ"`, `pay_frequency="Fortnightly"`, `pay_date=2026-04-08`, `gross=basic=3000`;
  - an ACTIVE employer profile;
  - an ACTIVE M tax profile (RESIDENT, PENDING IRD state, `IR330_DECLARATION`, ADULT);
  - a CONTRIBUTING KiwiSaver election (ESCT 17.5 with a basis amount in that band);
  - `nz_accumulators={"ACC_LIABLE_EARNINGS": Decimal("0")}`, `nz_hours=80`, `nz_hours_source="WORK_PATTERN"`;
  - the test pack.

### 5.2 `tests/test_nz_engine.py`: required cases
| Area | Cases |
|---|---|
| Guards | no payday; unknown frequency; `"FourWeekly"` normalises; non-NZD currency; missing / inactive / out-of-window employer profile; same for the tax profile; NON_RESIDENT; payment kind LUMP_SUM refused |
| Tax codes | every supported code calculates; CAE/EDW/NSW/WT refused with their code; `"XYZ"` unsupported; ND only with NO_NOTIFICATION; MISSING IRD state with an M code refused |
| Main PAYE | annual income exactly at, 1 below and 1 above each band boundary (15600, 53500, 78100, 180000) for all 4 frequencies; ME applies IETC; ME with an empty IETC table blocks; an empty `NZ_PAYE_METHOD` blocks (shipped behaviour) |
| Secondary/STC | each secondary rate; STC inside, before and after its window |
| ACC | ytd 0; ytd just below the cap (crossing → liable = remainder); ytd ≥ cap → levy 0; missing accumulator blocks; two consecutive paydays using the first's delta as the second's ytd reach exactly the cap |
| Student loan | M SL below, at and above the fortnightly threshold; each frequency's threshold row is the one used; S SL charges the whole payment; certificate rate inside and outside its window; NIL certificate; an extra notice adds; a non-SL code with no certificate gives 0 |
| KiwiSaver | payday 2026-04-08 with a period starting 2026-03-26 uses the 3.5 rows (NZ-008); payday 2026-03-31 blocks `ROW_MISSING`; employee rate 6 OK; 5 → `KS_RATE_UNSUPPORTED`; None → default; reduction window → 3% and an employer match only when flagged; suspension in window → zeros, suspension without a ref is refused by the schema (DB test) and by the engine (dict test); 16-year-old gets the employer contribution; a dob above max_age gets none; dob missing → `KS_AGE_UNKNOWN`; employer rate below the minimum blocks; PAYE_ALTERNATIVE refused; complying-fund destination carried |
| ESCT | each band edge of the basis amount; a stored rate disagreeing with its band blocks; ESCT = employer gross × rate; net = gross − ESCT |
| Child support | normal deduction; required > 40% → capped, shortfall, variation code, exception; empty variation table + shortfall blocks; no shortfall + empty variation table OK; two notices sum; an out-of-window notice ignored; a COURT_ATTACHMENT in force blocks |
| Precedence | PENDING blocks; a non-permutation blocks; CHILD_SUPPORT before PAYE blocks |
| Minimum wage | adult exactly at, above and below the floor; starting-out; no category / EXEMPTION_PERMIT / no hours → UNDETERMINABLE; the result never changes pay |
| Earning classes | a non-zero ALLOWANCE (REVIEW) blocks with the obligation in the key; a zero ALLOWANCE is fine; BONUS → `LUMP_SUM_UNSUPPORTED`; components exceeding gross block |
| Rounding | a PENDING rounding row blocks `ROUNDING_PENDING:<key>`; `DOWN_DOLLAR` vs `NEAREST_CENT_HALF_UP` change only the targeted amount |
| Standard integration | `calculate_payroll(ctx, "standard")` net pay == `nz_result["netPay"]`; `result.tds == paye + acc`; `result.employer_pension == ks_employer_gross`; `result.nz_result` is set; simple mode is still refused |
| Shipped content | building the pack from the content **with** pending labels → `NZ_PACK_UNSIGNED`; removing pending but keeping the empty authority tables → `NZ_TABLE_EMPTY:paye_main_method` |
| Determinism | same ctx twice gives identical `nz_result` and hashes; changing one input changes `inputHash`; the trace lists every row read |
| Privacy | no IRD-like digits, DOB or notice fields in `nz_result` (serialise and regex-check) |
| Purity | grep the NZ engine package for `date.today`, `datetime.now`, `import random`, `settings`, `SessionLocal`, `requests`, `httpx`: none |

### 5.3 `tests/test_nz_golden.py`
- Load `NZ_IRD_EXAMPLE` rows from the **seeded content** (`new_zealand_content.NZ_EMPTY_TABLES["ird_official_examples"]["rows"]`). While it is empty: `pytest.skip("G1: Inland Revenue official examples are not loaded (AC-NZ-01)")`.
- When loaded, each example's `formula_expression` JSON gives the ctx inputs and the expected `paye`, `accLevy`, `studentLoan`, `ksEmployee`, `ksEmployerGross`, `esct` and `childSupport`, asserted **exactly** (no tolerance).

### 5.4 Existing tests to keep green
- `tests/test_nz_scaffold.py`: replace `test_nz_calculation_is_blocked` and `test_every_calculation_mode_is_blocked`. The engine is no longer a stub; the new expectation is that an **empty ctx** blocks (e.g. `NZ_PAY_DATE_MISSING` / `NZ_ROW_MISSING`) and simple mode still blocks. Keep the "never generic calculator" test.
- `tests/test_nz_content.py::test_nz_engine_code_holds_no_statutory_literal` must pass. Use named constants for non-statutory numbers only (`HUNDRED`, `ZERO`).
- The Japan engine tests and `test_mexico_seed.py` are unchanged.

---

## 6. Build order (each step green before the next)
1. `errors.py` constants, then `pack.py` with a unit test of the rounder and the pending guard.
2. `components.py` and its tests.
3. `paye.py` + `acc_earner_levy.py` and their tests.
4. `student_loan.py`, then `esct.py` + `kiwisaver.py`, with tests.
5. `child_support.py`, `deduction_precedence.py`, `minimum_wage.py`, with tests.
6. `base.py` fields, then `new_zealand.py` `calculate`, then `standard.py`; then the integration, determinism, privacy and purity tests.
7. Update `test_nz_scaffold.py`; run all NZ, JP and engine-wide suites; then the full suite (about 20 minutes).
8. Commit:

```
New Zealand P3: pure calculation engine (PAYE/ACC, KiwiSaver/ESCT, student loan, child support, minimum wage)

Co-Authored-By: <agent attribution>
```

**Do not push** (R3).

## 7. Done criteria
- Every test in §5 passes, and so does the full backend suite.
- `grep -rn "Decimal(\"[0-9]" engine/countries/new_zealand.py engine/jurisdictions/new_zealand/` shows only `0`, `1` and `100` (named constants).
- With the shipped content, NZ still cannot calculate a single payslip: it blocks on unsigned rows and empty authority tables. That is the intended state until gate G1.
- No change to any non-NZ calculator's output: run the engine-wide suites (`tests/test_*engine*.py`, `tests/test_standard*.py`).
