# New Zealand P5: Holidays Act I (employments, entitlements, gross-earnings ledger, public holidays): detailed plan and code architecture

**Read first:** `IMPLEMENTATION_HANDOFF_P3_P10.md` §0 (R1–R13). P3 and P4 must be merged.

**Spec coverage:**

| Spec item | P5 coverage |
|---|---|
| §8 | annual holidays entitlement, sick, bereavement, family violence, public holidays (the entitlement side) |
| §11 | `WorkPatternVersion` (exists since P2), `LeaveEntitlement`, `GrossEarningsLedger`, `PublicHolidayDecision` |
| NZ-016 | no generic hours accrual is the legal source of truth |
| NZ-023 | family-violence data segregated |
| NZ-021 | entitlements are never zeroed |
| Gate | G2 |

**Out of scope (P6):** how much leave is *paid* (OWP/AWE/RDP/ADP), pay-as-you-go 8%, cash-up, final pay, lump sums.

**Why this is its own phase:** the spec calls the Holidays Act "the highest-risk New Zealand payroll domain", and no other country on the platform has an entitlement engine of this shape. Hong Kong's `engine/jurisdictions/hong_kong/entitlements.py` is the closest reference for structure only.

---

## 1. Facts about the existing platform that shape this design

| Fact (verified) | Consequence for NZ |
|---|---|
| `PayrollLeaveRequest` (`models.py:3773`) has `leave_type String(20)`, `days Integer`, **`reason Text`** | A family-violence request must **never** keep reason text. NZ refuses or blanks it (§5.3). Fractional days come from NZ leave events, not `days`. |
| `review_payroll_leave_request` (`service.py:39303`) approves a request, then calls `_sync_leave_to_attendance`, `_maybe_compute_uk_statutory_leave_pay` and `_maybe_assess_ie_statutory_sick_leave` | NZ adds `_maybe_record_nz_leave_event` right after the IE call. It is the single hook point. |
| `PayrollLeaveAllocation.leave_balances` is a JSON hours/days balance | For NZ it is **display only** and labelled "planning view" (NZ-016). The NZ entitlement table is the legal record. |
| `PayrollHoliday` (`models.py:2636`) has `country` but **no region** | `_nz_pack_holidays` seeds **national** holidays only (P4). Regional anniversary days are resolved inside NZ decisions from the pack table `NZ_PUBLIC_HOLIDAY` rows with `jurisdiction_state = region`. |
| `PayrollAttendanceRecord` (`models.py:2112`) has `date`, `check_in`, `check_out` (strings), `hours` (string) | Public-holiday hours-worked uses NZ decision rows that carry real timezone-aware `shift_start` / `shift_end`, not the attendance strings. |
| `PayrollUserPermission` (`models.py:7753`) plus Hong Kong's grant/revoke pattern (`hong_kong_service.py:5288–5370`, `MPF_ACCOUNT_REVEAL`) | The family-violence view permission `NZ_FAMILY_VIOLENCE_VIEW` reuses this table. **No new permission table.** |
| `PayrollEmployee.legal_entity_id` exists, but there is no employment-instance concept | P5 adds `payroll_nz_employments` (rehire = new instance, §10). |

---

## 2. File tree after P5

```
backend/alembic/versions/<hex12>_nz_holidays_act.py         (NEW)  5 tables, down_revision = 0e697c2388bf
backend/alembic/MIGRATIONS_MANIFEST.txt                       (EDIT) +1 line
backend/app/modules/payroll/
├── models.py                                                (EDIT) 5 PayrollNz* models (reuse _NzCommon)
├── engine/jurisdictions/new_zealand/holidays_act.py         (NEW)  pure entitlement + public-holiday rules
├── engine/countries/new_zealand_content.py                  (EDIT) docstring: NZ_PUBLIC_HOLIDAY row format; NZ_LEAVE_TYPES enum
├── nz_leave_service.py                                      (NEW)  employments, vesting, decisions, leave events, ledger, FV permission
├── new_zealand_service.py                                   (EDIT) before_run_transition PAID -> write_gross_earnings; _nz_pack_holidays unchanged
├── nz_org_router.py                                         (EDIT) +14 routes
├── service.py                                               (EDIT) review_payroll_leave_request hook; create_payroll_leave_request FV guard
backend/app/core/authz/route_registry.json, docs/privacy/route_policy_inventory.csv   (REGENERATED)
backend/tests/
├── test_nz_holidays_act_engine.py       (NEW)  pure rules
├── test_nz_holidays_act_migration.py    (NEW)  RLS / contract / constraints
├── test_nz_leave_service.py             (NEW)  vesting, decisions, events, ledger
├── test_nz_family_violence_privacy.py   (NEW)  restricted visibility + no reason text
└── head-pin suites (R9)                 (EDIT)
```

---

## 3. Database: migration `<hex12>_nz_holidays_act.py`

Copy the structure of `0e697c2388bf_nz_foundation.py`: `_common()`, `_effective()`, `_employee()`, `_index()`, literal names, lock timeout, idempotency, `_rls_for_new_tables`. **Every table is WORKER RLS ("org")**, because each has `employee_id`.

### 3.1 `payroll_nz_employments`: one row per employment instance
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | id, organization_id, legal_entity_id, evidence_ref, previous_version_id, created_by_id, approved_by_id, approved_at, created_at, updated_at |
| employee_id | FK payroll_employees CASCADE | no | |
| start_date | Date | no | anniversary anchor (spec §8) |
| end_date | Date | yes | set by P6 final pay |
| continuity_rule | String(16) | no | `NEW_INSTANCE` \| `CONTINUOUS`; CONTINUOUS requires `evidence_ref` (CHECK) |
| prior_employment_id | FK self SET NULL | yes | the instance continued from (CONTINUOUS) |
| termination_reason | String(30) | yes | |
| payg_eligible | Boolean | no, default false | pay-as-you-go 8% eligibility (used in P6) |
| payg_basis | String(28) | yes | `FIXED_TERM_UNDER_12_MONTHS` \| `IRREGULAR_INTERMITTENT` |
| payg_agreement_ref | String(300) | yes | |
| status | String(10) | no, default `DRAFT` | `DRAFT` \| `ACTIVE` \| `ENDED` |

**CHECKs**
- `end_date IS NULL OR end_date >= start_date`
- `continuity_rule IN (...)` and `continuity_rule <> 'CONTINUOUS' OR evidence_ref IS NOT NULL`
- `payg_eligible = false OR (payg_basis IS NOT NULL AND payg_agreement_ref IS NOT NULL)`; never a default for a "casual" label (§8)
- `status IN (...)`

**Indexes:** standard ones plus `(employee_id, start_date)`. Unique partial `uq_nz_employment_one_active` on `(organization_id, employee_id)` WHERE `status = 'ACTIVE'`.

### 3.2 `payroll_nz_leave_entitlements`: legal entitlement source of truth (NZ-016)
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | |
| employee_id, employment_id | FKs (employment CASCADE) | no | |
| leave_type | String(20) | no | `ANNUAL` \| `SICK` \| `BEREAVEMENT_CLOSE` \| `BEREAVEMENT_OTHER` \| `FAMILY_VIOLENCE` \| `ALTERNATIVE` |
| qualifying_date | Date | no | when the qualifying period was met |
| entitlement_date | Date | no | the anniversary or vesting date |
| unit | String(6) | no | `WEEKS` \| `DAYS` |
| quantity | Numeric(8,4) | no | vested this year |
| carried_in | Numeric(8,4) | no, default 0 | carried from the previous year (sick cap from content) |
| taken | Numeric(8,4) | no, default 0 | updated only by leave events (P5) and payments (P6) |
| paid_out | Numeric(8,4) | no, default 0 | cash-up / final pay (P6) |
| source | String(24) | no | `HOLIDAYS_ACT_2003` \| `EMPLOYMENT_AGREEMENT` \| `PUBLIC_HOLIDAY_WORKED` |
| source_decision_id | FK payroll_nz_public_holiday_decisions SET NULL | yes | for ALTERNATIVE (added after that table exists, or `use_alter=True`) |
| pack_hash | String(64) | no | content rows used to vest |
| expires_on | Date | yes | |
| status | String(12) | no, default `ACTIVE` | `ACTIVE` \| `EXHAUSTED` \| `PAID_OUT` \| `SUPERSEDED` |

**CHECKs**
- `quantity >= 0`, `carried_in >= 0`, `taken >= 0`, `paid_out >= 0`
- `taken + paid_out <= quantity + carried_in`
- `leave_type IN`, `unit IN`, `source IN`, `status IN`
- `leave_type <> 'ALTERNATIVE' OR source_decision_id IS NOT NULL`

**Indexes:** standard ones plus `(employee_id, leave_type, entitlement_date)`. Unique `uq_nz_entitlement_vest` on `(employment_id, leave_type, entitlement_date, source_decision_id)`; source_decision_id is NULL except for ALTERNATIVE, so use **two partial uniques**: one WHERE `leave_type <> 'ALTERNATIVE'` on `(employment_id, leave_type, entitlement_date)`, and one WHERE `leave_type = 'ALTERNATIVE'` on `(source_decision_id)`.

### 3.3 `payroll_nz_gross_earnings_ledger`: statutory gross earnings by pay run (append-only, no updated_at)
| column | type | null | notes |
|---|---|---|---|
| *(_common, with_updated=False)* | | | |
| employee_id, employment_id | FKs | no | |
| run_id | FK payroll_runs SET NULL | yes | |
| payslip_item_id | FK payslip_items SET NULL | no | |
| pay_date | Date | no | |
| period_start, period_end | Date | no | |
| component | String(24) | no | content `NZ_COMPONENTS` |
| amount | Numeric(14,2) | no | |
| included | Boolean | no | whether it counts as Holidays Act gross earnings (`HOLIDAY_GROSS` class) |
| treatment | String(14) | no | the `NZ_EARNING_CLASS` treatment used |
| reason | String(120) | no | e.g. `"HOLIDAY_GROSS:SALARY INCLUDED"`; **never free text** |
| days_worked | Numeric(6,2) | yes | for ADP (P6), from the work pattern or attendance |
| pack_hash | String(64) | no | |

**CHECK:** `treatment IN ('INCLUDED','EXCLUDED','LUMP_SUM_PATH','REVIEW')`.
**Unique:** `(payslip_item_id, component)`.
**Index:** `(employee_id, employment_id, pay_date)`.

### 3.4 `payroll_nz_public_holiday_decisions`
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | |
| employee_id, employment_id | FKs | no | |
| holiday_date | Date | no | |
| holiday_name | String(80) | no | from the pack row |
| region | String(3) | yes | ISO 3166-2 code (content `NZ_REGIONS`); NULL = national |
| otherwise_working_day | String(12) | no | `YES` \| `NO` \| `UNDETERMINED` |
| owd_basis | String(24) | no | `FIXED_PATTERN` \| `ROSTER` \| `HISTORY` \| `AGREEMENT` \| `OPERATOR_DECISION` |
| owd_evidence_ref | String(300) | yes | required when the basis is `OPERATOR_DECISION` or `AGREEMENT` (CHECK) |
| worked | Boolean | no | |
| shift_start, shift_end | DateTime(tz) | yes | required when `worked` (CHECK) |
| timezone | String(40) | no, default `Pacific/Auckland` | `Pacific/Auckland` \| `Pacific/Chatham` |
| hours_on_holiday | Numeric(6,2) | yes | computed by the engine (midnight crossing) |
| alternative_holiday_due | Boolean | no, default false | computed: worked AND owd = YES |
| status | String(12) | no, default `DRAFT` | `DRAFT` \| `APPROVED` \| `SUPERSEDED` |

**Unique** partial on `(employee_id, holiday_date)` WHERE `status = 'APPROVED'`. **Approval of UNDETERMINED is refused** in the service (it needs a YES/NO operator decision with evidence).

### 3.5 `payroll_nz_leave_events`: leave taken against entitlements
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | |
| employee_id, employment_id, entitlement_id | FKs | no / no / yes | entitlement resolved on approval |
| leave_type | String(20) | no | same enum as entitlements, minus ALTERNATIVE (P6 consumes ALTERNATIVE via `ALTERNATIVE_TAKEN` → use `leave_type='ALTERNATIVE'`) |
| start_date, end_date | Date | no | |
| quantity | Numeric(8,4) | no | |
| unit | String(6) | no | |
| source_request_id | FK payroll_leave_requests SET NULL | yes | the generic request |
| restricted | Boolean | no | must be **true** when `leave_type = 'FAMILY_VIOLENCE'` (CHECK) |
| status | String(12) | no, default `REQUESTED` | `REQUESTED` \| `APPROVED` \| `PAID` \| `CANCELLED` |

**There is deliberately no reason, narrative, notes or relationship column (NZ-023, §8).** The bereavement category (close or other) is encoded only in `leave_type`.

**CHECKs**
- `quantity > 0`
- `end_date >= start_date`
- `leave_type <> 'FAMILY_VIOLENCE' OR restricted = true`

### 3.6 Migration bookkeeping
- `_TABLES` drop order is the reverse of creation: events, decisions, ledger, entitlements, employments.
- Manifest line via `python -I scripts/update_migration_manifest.py`.
- Head-pin updates (R9): add the 5 tables to `nz_tables` in the deploy and South Africa tests, bump the revision count, and update the heads.

---

## 4. Pure engine: `engine/jurisdictions/new_zealand/holidays_act.py`

No database and no clock. Every value comes from the pack (`NzPack` from P3). It returns dataclasses with `steps` for the trace.

```python
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from .pack import NzPack, ZERO, dec, field, upper, as_date, in_window

LEAVE_TYPES = ("ANNUAL", "SICK", "BEREAVEMENT_CLOSE", "BEREAVEMENT_OTHER", "FAMILY_VIOLENCE", "ALTERNATIVE")
OWD_YES, OWD_NO, OWD_UNDETERMINED = "YES", "NO", "UNDETERMINED"
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

@dataclass
class Vest:  leave_type: str; qualifying_date: date; entitlement_date: date; unit: str
             quantity: Decimal; carried_in: Decimal; expires_on: date | None; steps: list

def add_months(d: date, months: int) -> date          # calendar-safe (29 Feb -> 28 Feb)
def anniversaries(start: date, as_of: date) -> list[date]     # start+12m, +24m ... <= as_of

def annual_vests(employment, as_of, already: set[date], pack) -> list[Vest]
    # weeks = pack.amount("nz_hol_annual_weeks"); months = int(pack.amount("nz_hol_annual_qualifying_months"))
    # for each anniversary a = start + k*months (k>=1) with a <= as_of and a not in already:
    #     Vest("ANNUAL", qualifying_date=a, entitlement_date=a, unit="WEEKS", quantity=weeks, carried_in=0, expires_on=None)
    # NOTE (NZ-016): expressed in WEEKS tied to the current working week; never converted to hours here

def sick_vests(employment, as_of, prior: dict | None, pack) -> list[Vest]
    # qualify = start + nz_hol_sick_qualifying_months; first vest on qualify; then every 12 months after qualify
    # quantity = nz_hol_sick_days (NOT pro-rated - spec §8)
    # carried_in = min(prior_remaining, nz_hol_sick_carry_max - quantity) clamped >= 0
    #   where prior_remaining = prior.quantity + prior.carried_in - prior.taken - prior.paid_out
    #   (the carried total plus the new entitlement never exceeds nz_hol_sick_carry_max)

def family_violence_vests(employment, as_of, already, pack) -> list[Vest]
    # same qualifying period and cadence as sick (the spec says "after qualifying period"; the period comes from
    # nz_hol_sick_qualifying_months unless a dedicated content key is signed - record the key used in steps)
    # quantity = nz_hol_family_violence_days; NO carry-over

def bereavement_quantity(kind: str, employment, on: date, pack) -> Decimal
    # qualifying: employment.start + nz_hol_sick_qualifying_months <= on, else ZERO (with step "not yet eligible")
    # kind CLOSE -> nz_hol_bereavement_close_days; OTHER -> nz_hol_bereavement_other_days
    # bereavement is per event: it vests at the event, not by anniversary

def holidays_for(pack, year: int, region: str | None) -> list[dict]
    # NZ_PUBLIC_HOLIDAY rows (table "public_holidays" - blocks TABLE_EMPTY until G2) with
    # effective_from.year == year and (jurisdiction_state is None or == region)
    # -> [{"date", "name", "region"}] sorted

def otherwise_working_day(holiday: date, work_pattern, history: list[date] | None) -> tuple[str, str, list]
    # FIXED: weekly_schedule[WEEKDAYS[holiday.weekday()]] > 0 -> YES ("FIXED_PATTERN"), == 0 -> NO
    # ROSTERED: roster week index = ((holiday - pattern.effective_from).days // 7) % roster_cycle_weeks;
    #           roster_schedule[str(index)][weekday] > 0 -> YES/NO ("ROSTER")
    # VARIABLE or no pattern: history = dates worked on the same weekday in the lookback the caller supplies;
    #   all worked -> YES, none worked -> NO, mixed -> UNDETERMINED ("HISTORY")
    #   (the statutory factors need operator judgement; UNDETERMINED blocks approval)
    # returns (decision, basis, steps)

def hours_on_holiday(shift_start: datetime, shift_end: datetime, holiday: date, tz: str) -> Decimal
    # convert both to ZoneInfo(tz); window = [holiday 00:00, holiday+1 00:00) in tz (DST-correct)
    # overlap = max(0, min(end, window_end) - max(start, window_start)); return hours (Decimal, 2dp)
    # handles a shift starting the evening before and crossing midnight into the holiday, and vice versa

def alternative_holiday_due(worked: bool, owd: str) -> bool     # worked and owd == YES (spec §8)

def balance(ent) -> Decimal                       # quantity + carried_in - taken - paid_out
```

**Rules encoded and not configurable:** the 4-week entitlement is in weeks (no hours accrual), sick leave is not pro-rated, and the family-violence identity is never in steps. Every number (weeks, days, months, caps) is read from content keys `nz_hol_*`.

---

## 5. Service: `nz_leave_service.py` (new)

### 5.1 Employments
```python
def record_nz_employment(db, org_id, employee_id, payload, actor_id, reason) -> row
    # fields: start_date, continuity_rule, prior_employment_id, payg_eligible, payg_basis, payg_agreement_ref,
    #         legal_entity_id, evidence_ref  (status DRAFT)
def approve_nz_employment(db, org_id, row_id, actor_id) -> row      # four-eyes; DRAFT -> ACTIVE (one ACTIVE per employee)
def active_employment(db, org_id, employee_id, on: date) -> row | None
```
**Rehire (§10):** a new instance with `continuity_rule = NEW_INSTANCE` resets anniversaries. `CONTINUOUS` needs evidence and keeps the prior start date as the anchor: `anchor_date()` follows `prior_employment_id` while CONTINUOUS.

### 5.2 Vesting
```python
def vest_entitlements(db, org_id, as_of: date, *, employee_id=None, actor_id=None) -> dict
    # pack = in-force NZ pack at as_of (tax_resolver.resolve_tax_configuration) -> NzPack
    # for each ACTIVE employment (optionally one employee):
    #   already = {(type, entitlement_date)} existing
    #   for v in annual_vests + sick_vests + family_violence_vests: insert PayrollNzLeaveEntitlement(..., pack_hash=sha256(pack.used()),
    #       status ACTIVE) unless already present (idempotent via the unique keys)
    #   when a new SICK year vests, set the previous SICK row's status EXHAUSTED (its remainder moved to carried_in)
    # returns {"vested": n, "employees": m}; any NZCalculationBlockedError -> 409 with the key (content not signed)
```
`vest_entitlements` is called by the route `POST /leave/vest` and is safe to re-run. **It is never run automatically on a schedule in P5** (no scheduler infrastructure for NZ yet; noted for P9 operations).

### 5.3 Leave requests and events (the generic flow plus NZ)
```python
NZ_REQUEST_TYPES = {"annual": "ANNUAL", "sick": "SICK", "nz_bereavement_close": "BEREAVEMENT_CLOSE",
                    "nz_bereavement_other": "BEREAVEMENT_OTHER", "nz_family_violence": "FAMILY_VIOLENCE",
                    "nz_alternative": "ALTERNATIVE"}       # generic leave_type (String(20)) -> NZ type

def guard_generic_request(db, data, organization_id) -> None
    # called at the start of service.create_payroll_leave_request for an NZ employee:
    # leave_type maps to FAMILY_VIOLENCE -> refuse if data.reason is non-empty
    #   ("Family violence leave never records a reason") - do NOT store-then-blank
    # unknown NZ leave_type -> 400 listing NZ_REQUEST_TYPES

def record_leave_event_from_request(db, request, organization_id, actor_id) -> event | None
    # called from service.review_payroll_leave_request when status becomes "approved" (after the IE call)
    # employee not NZ -> None
    # nz_type = NZ_REQUEST_TYPES[request.leave_type]; employment = active_employment(..., request.start_date)
    #   none -> 409 "No active New Zealand employment"
    # quantity/unit: ANNUAL -> WEEKS = days_of_leave / working_days_per_week(work pattern) (Decimal 4dp);
    #                others -> DAYS = working days in [start, end] per the work pattern
    # entitlement = the oldest ACTIVE entitlement of that type with balance >= quantity (FIFO);
    #   BEREAVEMENT_*: create-on-demand from bereavement_quantity() (event-based)
    #   insufficient -> 409 "Insufficient New Zealand <type> entitlement" (the generic approval is rolled back)
    # event = PayrollNzLeaveEvent(..., restricted = nz_type == FAMILY_VIOLENCE, status APPROVED)
    # entitlement.taken += quantity (status EXHAUSTED when the balance hits 0); audit (no reason text)

def cancel_leave_event(db, org_id, event_id, actor_id, reason) -> event    # restores taken; P6 refuses once PAID
```

### 5.4 Public-holiday decisions
```python
def propose_public_holiday_decisions(db, org_id, year, *, employee_id=None, actor_id=None) -> list
    # for each ACTIVE employment: region = employee's region (employee.state or address region mapped to an
    #   ISO code via content.NZ_REGIONS names; unknown -> region None and a step noting "regional day not applied")
    # for h in holidays_for(pack, year, region): if no decision exists for (employee, date):
    #   owd, basis, steps = otherwise_working_day(h.date, work pattern in force on h.date, history)
    #   history = dates with attendance status 'present' on the same weekday in the 13 weeks before
    #   create DRAFT decision(worked=False, owd, basis)
def update_public_holiday_decision(db, org_id, decision_id, payload, actor_id, reason) -> row
    # operator may set otherwise_working_day YES/NO (basis OPERATOR_DECISION + evidence), worked, shift_start/end, timezone
    # recompute hours_on_holiday and alternative_holiday_due via the engine
def approve_public_holiday_decision(db, org_id, decision_id, actor_id) -> row
    # four-eyes; UNDETERMINED -> 400; DRAFT -> APPROVED
    # alternative_holiday_due -> create an ALTERNATIVE entitlement (1 DAY, source PUBLIC_HOLIDAY_WORKED,
    #   source_decision_id) - idempotent via the partial unique index
```
**Pay** for public holidays (time-and-a-half, RDP/ADP) is **P6**. P5 only records the decision, hours and alternative holiday.

### 5.5 Gross-earnings ledger
```python
def write_gross_earnings(db, run, actor_id) -> int
    # called from new_zealand_service.before_run_transition at PAID (after post_accumulators)
    # for each NZ payslip: snap = item.nz_calculation_snapshot
    #   lines = snap["baseLines"]["HOLIDAY_GROSS"]  -> P3 must also compute the HOLIDAY_GROSS base
    #           (add "HOLIDAY_GROSS" to components.BASES in P5; it does not change pay)
    #   for each line: insert a ledger row (included = treatment INCLUDED; reason f"HOLIDAY_GROSS:{component} {treatment}")
    #   days_worked: attendance present days in the period, else the work pattern's contracted days × weeks
    # idempotent by (payslip_item_id, component)
```
The P3 change needed is small and in scope for P5: `components.BASES += ("HOLIDAY_GROSS",)`. **Do not** let a REVIEW component block the payslip for HOLIDAY_GROSS. A REVIEW treatment for HOLIDAY_GROSS is recorded as `included=False, treatment=REVIEW`, and P6 leave pay blocks if it meets an unreviewed row (NZ-017). Implement this as `obligation_base(..., block_on_review=False)` for HOLIDAY_GROSS only.

### 5.6 Family-violence restricted access (NZ-023)
```python
NZ_FAMILY_VIOLENCE_VIEW = "NZ_FAMILY_VIOLENCE_VIEW"
def grant_family_violence_view(db, org_id, actor_id, user_id, reason)     # copy hong_kong_service grant_mpf_account_reveal:
    # org admin only; never self; reason required; one active grant per user
def revoke_family_violence_view(db, org_id, actor_id, user_id, reason)
def can_view_family_violence(db, org_id, user_id) -> bool
def visible_events(db, org_id, viewer_id, employee_id) -> list
    # restricted rows are dropped unless can_view_family_violence; each restricted read writes a
    # PersonalDataAccessEvent (models.py:7642) with purpose "NZ_FAMILY_VIOLENCE_LEAVE"
def balances(db, org_id, viewer_id, employee_id) -> dict
    # {"annual": {...weeks...}, "sick": {...}, "bereavement": [...], "alternative": [...],
    #  "familyViolence": {...} only with permission, "planningView": allocation JSON labelled "not the legal entitlement"}
```
Exports and manager screens use `visible_events` / `balances` only. Add a test that the generic leave list endpoint (`GET /leave-requests`) hides NZ family-violence requests from a viewer without the permission. That needs a filter in `service.list_leave_requests` for NZ employees: an `nz_leave_service.hide_restricted_requests(db, org_id, viewer_id, rows)` call.

---

## 6. Routes added to `nz_org_router.py`

| Method / path | Handler | Auth |
|---|---|---|
| GET / POST `/employees/{eid}/employments` | `nz_list_employments`, `nz_create_employment` | operator / admin |
| POST `/employments/{row_id}/approve` | `nz_approve_employment` | admin |
| POST `/leave/vest` (`{asOf, employeeId?}`) | `nz_vest_entitlements` | admin |
| GET `/employees/{eid}/leave-entitlements` | `nz_list_entitlements` (via `balances`) | operator |
| GET `/employees/{eid}/leave-events` | `nz_list_leave_events` (via `visible_events`) | operator |
| POST `/leave-events/{event_id}/cancel` | `nz_cancel_leave_event` | admin |
| POST `/public-holidays/propose` (`{year, employeeId?}`) | `nz_propose_public_holidays` | admin |
| GET `/employees/{eid}/public-holiday-decisions` | `nz_list_public_holiday_decisions` | operator |
| PUT `/public-holiday-decisions/{id}` | `nz_update_public_holiday_decision` | admin |
| POST `/public-holiday-decisions/{id}/approve` | `nz_approve_public_holiday_decision` | admin |
| GET `/employees/{eid}/gross-earnings` | `nz_list_gross_earnings` | operator |
| GET / POST / DELETE `/permissions/family-violence[/{user_id}]` | `nz_list_fv_holders`, `nz_grant_fv_view`, `nz_revoke_fv_view` | admin |

Regenerate the route registry (R10).

---

## 7. Edits to existing files (anchors)

| File | Anchor | Edit |
|---|---|---|
| `service.py` `create_payroll_leave_request` (line 38919) | the top, after the employee is loaded | `if _normalize_country(employee country) == "NZ": nz_leave_service.guard_generic_request(db, data, organization_id)` |
| `service.py` `review_payroll_leave_request` (line 39303) | after `_maybe_assess_ie_statutory_sick_leave(db, record, organization_id)` | `_maybe_record_nz_leave_event(db, record, organization_id, reviewer_id)`, a tiny wrapper that calls `nz_leave_service.record_leave_event_from_request` for NZ employees |
| `service.py` leave-request list function | before returning rows | `nz_leave_service.hide_restricted_requests(...)` for NZ employees |
| `new_zealand_service.before_run_transition` | the PAID branch, after `post_accumulators` | `nz_leave_service.write_gross_earnings(db, run, actor_id)` |
| `engine/jurisdictions/new_zealand/components.py` | `BASES` and `obligation_base` | add `HOLIDAY_GROSS` with `block_on_review=False` (§5.5) |
| `new_zealand_content.py` | docstring | `NZ_PUBLIC_HOLIDAY` rows: `effective_from` = date, `jurisdiction_state` = ISO region or NULL, `rate_label` = name. Add `NZ_LEAVE_TYPES` = `holidays_act.LEAVE_TYPES` as the enum source |

---

## 8. Worked examples (put them in `test_nz_holidays_act_engine.py`; content values from the spec, dates illustrative)

1. **Annual anniversary.** Start 2025-05-12. On 2026-05-12, 4 WEEKS vest (`nz_hol_annual_weeks`). On 2026-05-11, nothing vests. A 29-Feb start vests on 28 Feb in non-leap years.
2. **Sick qualification and carry.**
   - Start 2026-01-05 → 10 days vest 2026-07-05.
   - 4 days are taken by 2027-07-05, leaving 6.
   - The new year vests 10 with `carried_in = min(6, 20 − 10) = 6`, total 16.
   - The next year, with 16 untaken: `carried_in = min(16, 10) = 10`, total 20 (the cap).
3. **Otherwise working day, FIXED.** The pattern is Mon–Fri 8 h. A public holiday on Monday → YES. On Saturday → NO.
4. **Midnight crossing.** A night shift 2026-12-24 22:00 to 2026-12-25 06:00 Pacific/Auckland → 6.00 h on the 25 December holiday and 2.00 h before it.
5. **Worked on an otherwise working day** → alternative holiday due → on approval, an ALTERNATIVE 1-DAY entitlement is created once (re-approval does not duplicate it).

---

## 9. Tests

| File | Tests |
|---|---|
| `test_nz_holidays_act_migration.py` | `test_rls_policies_derived`, `test_tables_match_models`, `test_replay_noop`, `test_downgrade_only_own_tables`, `test_drift_filter_explains`, `test_single_child_of_foundation`, `test_manifest_line`, `test_payg_needs_basis_and_agreement`, `test_continuous_needs_evidence`, `test_one_active_employment`, `test_entitlement_balance_cannot_go_negative`, `test_alternative_needs_decision_and_is_unique`, `test_family_violence_event_must_be_restricted`, `test_no_reason_column_on_events`, `test_ledger_unique_per_payslip_component` |
| `test_nz_holidays_act_engine.py` | the 5 worked examples; `test_annual_in_weeks_never_hours`, `test_sick_not_prorated`, `test_sick_carry_cap`, `test_family_violence_no_carry`, `test_bereavement_close_other_and_not_yet_eligible`, `test_roster_week_index`, `test_variable_history_mixed_is_undetermined`, `test_dst_day_hours`, `test_chatham_timezone`, `test_regional_holiday_filtered_by_region`, `test_public_holidays_empty_blocks_until_g2`, `test_every_number_from_content` (monkeypatch a content key and observe the change) |
| `test_nz_leave_service.py` | `test_vest_idempotent`, `test_vest_blocks_on_unsigned_pack`, `test_rehire_new_instance_resets_anchor`, `test_continuous_keeps_anchor`, `test_approved_request_creates_event_and_consumes_fifo`, `test_insufficient_entitlement_rolls_back_generic_approval`, `test_bereavement_vests_per_event`, `test_cancel_restores_balance`, `test_propose_decisions_once_per_holiday`, `test_undetermined_cannot_be_approved`, `test_operator_decision_needs_evidence`, `test_alternative_created_once`, `test_paid_run_writes_gross_ledger_once`, `test_holiday_gross_review_recorded_not_blocking_pay` |
| `test_nz_family_violence_privacy.py` | `test_reason_refused_on_create`, `test_events_hidden_without_permission`, `test_events_visible_with_permission_and_access_logged`, `test_grant_not_to_self_and_needs_reason`, `test_generic_leave_list_hides_nz_fv_requests`, `test_balances_omit_fv_without_permission`, `test_logs_and_exports_have_no_fv_detail` (caplog plus a payload scan) |

## 10. Definition of done
- [ ] The migration has a single head, the manifest is updated, all head pins are updated, and the drift filter is green.
- [ ] Entitlements are in weeks or days only. The allocation JSON is labelled a planning view everywhere it is shown for NZ.
- [ ] Family-violence data: no reason text exists anywhere; restricted visibility is proven; access is logged.
- [ ] Gross-earnings ledger rows are written once per PAID payslip.
- [ ] The NZ, Japan and leave-related suites (`tests/test_*leave*`) are green, and so is the full suite. One local commit, not pushed.
