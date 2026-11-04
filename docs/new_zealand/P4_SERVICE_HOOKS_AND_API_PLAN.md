# New Zealand P4: service hooks, organisation API, pay-run binding (detailed plan and code architecture)

**Read first:** `IMPLEMENTATION_HANDOFF_P3_P10.md` §0 (ground rules R1–R13). P3 must already be merged on `venu`: P4 calls `new_zealand.calculate` through the shared pipeline.

**Japan template.** Every NZ function below has a Japan twin in `backend/app/modules/payroll/japan_service.py`, with the line numbers given. Open it next to this document.

**Spec coverage:**

| Spec item | What P4 does |
|---|---|
| §10 lifecycle | Effective-dated profiles and payday-based selection |
| §11 domain model | Service layer over the P2 tables |
| §12 operator API | Organisation routes, preflight, fingerprint |
| NZ-001 | Activation per legal employer |
| NZ-005 / NZ-006 / NZ-022 | Snapshot, replay and hashes |
| NZ-010 | Authority notices as immutable versions |
| NZ-013 | Accumulator posting at PAID |
| NZ-015 | Minimum wage blocks approval |
| NZ-020 / NZ-024 | Versioning, four-eyes and reasons |
| NZ-023 / NZ-025 | IRD vault workflow, no leakage |

**No migration in P4.** Everything uses the P2 tables.

---

## 1. File tree after P4

```
backend/app/modules/payroll/
├── new_zealand_service.py        (EXTEND)  ~1,100 new lines: inputs, snapshot, hooks, writers, vault, preflight
├── nz_org_router.py              (NEW)     ~420 lines: /api/payroll/new-zealand
├── jurisdiction_hooks.py         (EDIT)    _MODULES["NZ"]
├── router.py                     (EDIT)    include nz_org_router
├── schemas.py                    (EDIT)    nzPaymentKind, nzCalculationSnapshot
├── service.py                    (EDIT)    4 call sites (+ serializer), next to every Japan block
├── employee_validation.py        (EDIT)    NZEmployeeValidation (dormant)
├── engine/resolver.py            (EDIT)    build_context_from_employee(nz_inputs=)
backend/app/core/authz/route_registry.json        (REGENERATED)
docs/privacy/route_policy_inventory.csv            (REGENERATED)
backend/tests/
├── _nz_service_helpers.py        (NEW)     org/employee/profile factories on the SQLite db fixture
├── test_nz_phase4_hooks.py       (NEW)
├── test_nz_phase4_versions.py    (NEW)
├── test_nz_phase4_vault.py       (NEW)
├── test_nz_phase4_runs.py        (NEW)
├── test_nz_phase4_api.py         (NEW)
├── test_mexico_scaffolding.py    (EDIT)    _MODULES expectation gains "NZ"
└── privacy/test_route_registry.py (unchanged, must stay green)
```

---

## 2. Architecture

### 2.1 Layering (arrows = "calls")

```
HTTP  ──► nz_org_router.py  (auth deps, 404 dormancy gate, request parsing, nz_* handlers)
              │
              ▼
          new_zealand_service.py
              ├── versioned writers / approvals  ──► models (PayrollNz*)  ──► service.require_four_eyes / record_tax_audit
              ├── IRD vault workflow              ──► nz_ird_number (crypto)  ──► PayrollNzIrdVault / AccessEvent
              ├── resolve_nz_calc_inputs          ──► models (read only)
              ├── freeze / thaw / replay / hash   ──► engine.resolver.calculate_payroll  ──► new_zealand.calculate (P3)
              ├── before_run_transition           ──► PayrollNzAccumulatorEntry (write at PAID)
              └── JURISDICTION_HOOKS (13)          ◄── jurisdiction_hooks.call("NZ", ...)  ◄── service.py / retention / super admin
```

### 2.2 Run lifecycle with NZ

```
generate / recalculate run (service.py ~25646)
   └─ nz_inputs = hooks.call("NZ","calc_inputs", db, run, employee, pack)      → resolve_nz_calc_inputs(payday = run.pay_date)
   └─ ctx = build_context_from_employee(..., nz_inputs=nz_inputs)
   └─ result = calculate_payroll(ctx, mode)                                     → P3 engine
   └─ frozen = nz_freeze_context(ctx, mode)
   └─ item.nz_calculation_snapshot = nz_payslip_snapshot(result, frozen)
transition DRAFT → APPROVED (service.py ~32445 calls before_run_transition)
   └─ every NZ payslip has a snapshot · employer VERIFIED · no open exception · preflight empty
   └─ run.nz_approval_fingerprint = nz_approval_fingerprint(db, run)
transition → AUTHORIZED / PAID
   └─ recomputed fingerprint == stored, else 409
transition → PAID
   └─ post_accumulators(db, run)   (idempotent; uq_nz_accum_payslip_obligation)
```

---

## 3. `new_zealand_service.py`: full contents to add

Group the code under the section banners shown (Japan uses the same banners).

### 3.1 Module header and imports
```python
import hashlib, json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from sqlalchemy.orm import Session
from app.core.exceptions import BadRequestException, NotFoundException

NZ = "NZ"
SPEC = "ZP-NZ-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"          # already present
STATUS_DRAFT, STATUS_ACTIVE, STATUS_SUPERSEDED = "DRAFT", "ACTIVE", "SUPERSEDED"

def _nz_models():   # lazy import like japan_service._jp_models (line 169) – avoids import cycles
    from app.modules.payroll import models as m
    return m
```

### 3.2 Shared helpers (twins of Japan lines 133–200 and 1162–1300)
```python
def _as_date(value, field) -> date             # copy japan_service._as_date
def _money(value, field) -> Decimal            # copy japan_service._money
def _nz_bool(value, field) -> bool             # strict, like _jp_bool
def _nz_audit(db, actor_id, action, entity_type, entity_id, old=None, new=None)
    # service.record_tax_audit(..., auto_commit=False)
def _nz_employee(db, organization_id, employee_id) -> PayrollEmployee
    # 404 "New Zealand employee not found." if not the org's, or country_code != "NZ"
def _nz_clean(payload: dict, fields: tuple, *, required=()) -> dict
    # like _jp_clean: unknown keys -> 400; typed coercion via the _NZ_*_FIELDS sets below
def _nz_reason(reason) -> str
    # strip; empty -> 400 "A reason is required" (NZ-024: every statutory edit needs a reason)
```

**Field whitelists** (anything not listed is rejected with 400; the server owns `status` / `approved_*`):
```python
NZ_EMPLOYER_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "legal_name", "filing_method",
    "filing_method_evidence_ref", "annual_paye_esct_basis", "annual_paye_esct_amount", "remittance_class",
    "connected_business_group_ref", "connected_business_evidence_ref", "acc_classification_unit",
    "acc_metadata", "timezone", "bank_mandate_ref", "filing_credential_ref", "source_document_id",
    "evidence_ref")
NZ_TAX_PROFILE_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "ird_number_state",
    "tax_code", "tax_code_source", "declaration_received_on", "declaration_ref", "residency_status",
    "tailored_certificate_ref", "tailored_rate_pct", "tailored_valid_from", "tailored_valid_to",
    "sl_certificate_type", "sl_certificate_ref", "sl_certificate_rate_pct", "sl_certificate_valid_from",
    "sl_certificate_valid_to", "min_wage_category", "min_wage_evidence_ref", "evidence_ref")
    # ird_vault_id is NOT client-writable: the service links the employee's ACTIVE vault row
NZ_KIWISAVER_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "membership_state",
    "enrolment_route", "opt_out_evidence_ref", "employee_rate_pct", "employer_rate_pct", "reduction_ref",
    "reduction_from", "reduction_to", "employer_matches_reduction", "suspension_ref", "suspension_from",
    "suspension_to", "esct_rate_pct", "esct_basis", "esct_basis_amount", "esct_tax_year",
    "employer_contribution_treatment", "settlement_destination", "complying_fund_ref", "evidence_ref")
NZ_WORK_PATTERN_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "pattern_type",
    "contracted_hours_per_week", "contracted_days_per_week", "weekly_schedule", "roster_cycle_weeks",
    "roster_schedule", "hours_source", "evidence_ref")
NZ_NOTICE_FIELDS = ("deduction_type", "notice_id", "issuer", "received_at", "effective_from",
    "effective_to", "amount_per_payday", "rate_pct", "protected_earnings_policy",
    "protected_earnings_amount", "reason_code", "legal_entity_id", "evidence_ref")
_NZ_DATE_FIELDS = {...all *_from/_to/_on fields...}; _NZ_DECIMAL_FIELDS = {...pct/amount fields...}
_NZ_INT_FIELDS = {"legal_entity_id", "source_document_id", "roster_cycle_weeks"}
_NZ_BOOL_FIELDS = {"employer_matches_reduction"}
_NZ_JSON_FIELDS = {"acc_metadata", "weekly_schedule", "roster_schedule"}
```

**Enum checks** that reuse content constants before the DB CHECK fires, so users get a clear 400:
```python
def _nz_enum(data, key, allowed):   # value not in allowed -> 400 f"{key} must be one of ..."
```
Use `content.TAX_CODE_SOURCES`, `IRD_NUMBER_STATES`, `MIN_WAGE_CATEGORIES`, `KS_MEMBERSHIP_STATES`, `KS_SETTLEMENT_DESTINATIONS`, `ESCT_BASES`, `FILING_METHODS`, `REMITTANCE_CLASSES` and `AUTHORITY_DEDUCTION_TYPES`.

For `tax_code`: not in `content.SUPPORTED_TAX_CODES` → 400. A code in `REFUSED_TAX_CODES` → 400 with the `content.NZ_DEFERRED` text.

### 3.3 Versioned writers and approvals (twins of `_jp_create_version` 1187 and `_jp_approve_version` 1257)
```python
def _nz_create_version(db, model, organization_id, employee_id, data, actor_id, label, reason) -> row
    # prior = latest row for (org, employee?, legal_entity_id) by (effective_from desc, id desc)
    # row = model(organization_id=..., status="DRAFT", created_by_id=actor_id,
    #             previous_version_id=prior.id if prior else None, **data)
    # flush; _nz_audit(..., "created", label, row.id, new={"effective_from": ..., "reason": reason})

def _nz_approve_version(db, model, organization_id, row_id, actor_id, label) -> row
    # copy _jp_approve_version, with the scope key (employee_id when present, plus legal_entity_id)
    # row DRAFT only; require_four_eyes(row.created_by_id, actor_id, f"Approving a New Zealand {label}", db=...,
    #                                   entity_type=label, entity_id=row.id, current_status=row.status)
    # supersede ACTIVE rows of the same scope: refuse if old.effective_from >= start; close effective_to = start-1;
    # status SUPERSEDED. row ACTIVE, approved_by/at; audit "approved"
```

**Public writers:**

| Function | Notes |
|---|---|
| `record_nz_employer_profile(db, org_id, payload, actor_id, reason)` | required `effective_from, legal_name, filing_method, remittance_class`. Checks: `remittance_class` vs `annual_paye_esct_amount` (if both given, `TWICE_MONTHLY` iff amount ≥ `nz_large_employer_threshold` read from the **in-force pack**; with no in-force pack, skip the check and record `"thresholdCheck": "PENDING_PACK"` in the audit, never a hard-coded number); `legal_entity_id` must belong to the org (`organizations.models.LegalEntity`). |
| `approve_nz_employer_profile(db, org_id, row_id, actor_id)` | |
| `verify_nz_employer_profile(db, org_id, row_id, actor_id, outcome, reason)` | `outcome` VERIFIED / REJECTED; four-eyes vs `created_by_id`; requires an ACTIVE row with `employer_ird_vault_id` set. |
| `record_nz_tax_profile(db, org_id, employee_id, payload, actor_id, reason)` | required `effective_from, ird_number_state, tax_code, tax_code_source`; links `ird_vault_id` = the employee's ACTIVE vault row; `ird_number_state == VALID` with no ACTIVE vault row → 400. |
| `approve_nz_tax_profile(...)` | |
| `record_nz_kiwisaver_election(...)` / `approve_nz_kiwisaver_election(...)` | `employee_rate_pct` (if given) must be in the in-force pack's `nz_ks_employee_rates`, else 400; with no pack in force, accept and let the engine block (record the warning in the response). |
| `record_nz_work_pattern(...)` / `approve_nz_work_pattern(...)` | `weekly_schedule` keys must be MON..SUN with Decimal hours 0–24. |
| `import_nz_authority_notice(db, org_id, employee_id, meta: dict, file_bytes: bytes, actor_id)` | see the notice workflow below |
| `approve_nz_authority_notice(db, org_id, row_id, actor_id)` | IMPORTED → APPROVED (four-eyes); the replaced row → SUPERSEDED |
| `revoke_nz_authority_notice(db, org_id, row_id, actor_id, reason)` | APPROVED → REVOKED (four-eyes) |
| `request_nz_opening_balance(db, org_id, employee_id, obligation, amount, tax_year, evidence_ref, actor_id, reason)` | stored as a DRAFT in the audit table, not the ledger: write a `TaxConfigurationAudit` row (`entity_type="nz_opening_balance_request"`) holding the payload; return a request id |
| `approve_nz_opening_balance(db, org_id, request_id, actor_id)` | four-eyes vs the requester → insert a `PayrollNzAccumulatorEntry(entry_kind="OPENING_BALANCE", evidence_ref, approved_by_id=actor_id, pay_date=<tax-year start from the pack window>)` |

**Notice workflow** (`import_nz_authority_notice`):
1. Clean `meta` with `NZ_NOTICE_FIELDS`. Required: type, notice_id, issuer, received_at, effective_from, policy, plus an amount or a rate.
2. `file_hash = sha256(file_bytes)`.
3. If the latest version with the same `(org, employee, type, notice_id)` has an identical `file_hash`, return it (idempotent re-upload).
4. Otherwise `version = latest.version + 1` and `replaces_id = latest.id`.
5. Store `evidence_ref` (the stored document path from the existing `SourceArtifact` upload flow, or the caller's ref). **The file body is never stored in the notice row** (NZ-025).
6. Create the row with status IMPORTED and audit it.

### 3.4 IRD vault workflow (twin of Japan 1547–1771, single use enforced)
```python
def _nz_vault(db, org_id, vault_id) -> PayrollNzIrdVault       # 404 outside the org
def _nz_vault_event(db, org_id, row, action, actor_id, reason=None, purpose=None) -> event
def _nz_vault_owner(row) -> str
    # ird.vault_owner(row.organization_id, row.subject_type,
    #                 row.employee_id if subject EMPLOYEE else row.legal_entity_id, row.id)

def create_nz_ird_number(db, org_id, subject_type, raw, actor_id, *, employee_id=None, legal_entity_id=None)
    # plain = ird.normalise(raw) (IrdNumberError -> 400, message never echoes the input)
    # fp = ird.fingerprint(plain); an ACTIVE row with (org, subject_type, fp) -> 400 "already on file"
    # an ACTIVE EMPLOYEE row for the employee -> 400 "delete the existing number first"
    # row = PayrollNzIrdVault(..., ciphertext="__pending__", key_version=0, fingerprint=fp, collected_at=utcnow)
    # flush -> owner = _nz_vault_owner(row); row.ciphertext, row.key_version = ird.encrypt(plain, owner)
    # _nz_vault_event(... "CREATE"); return masked view {"id", "subjectType", "onFile": True, "masked": ird.masked()}
def list_nz_ird_numbers(db, org_id, employee_id=None) -> list   # masked views only
def request_nz_ird_reveal(db, org_id, vault_id, reason, actor_id)        # REVEAL_REQUESTED (reason required)
def approve_nz_ird_reveal(db, org_id, vault_id, actor_id)
    # latest REVEAL_REQUESTED; no REVEAL_APPROVED after it; four-eyes vs request.actor_id -> REVEAL_APPROVED
    # (previous_version_id = request.id)
def reveal_nz_ird_number(db, org_id, vault_id, actor_id) -> dict
    # needs: latest REQUESTED -> APPROVED after it -> and NO REVEALED after that APPROVED (single use;
    #        Japan lacks this check - do not copy that gap)
    # actor must be the requester (the person who asked is the one who sees it)
    # number = ird.decrypt(row.ciphertext, row.key_version, _nz_vault_owner(row)) (IrdNumberError -> 400)
    # _nz_vault_event("REVEALED"); return {"irdNumber": number, "vaultId": row.id}     # the only digit-bearing response
def delete_nz_ird_number(db, org_id, vault_id, actor_id, reason)         # ciphertext=None, DELETED, event
```

### 3.5 Calculation inputs (twin of `resolve_jp_calc_inputs`, line 430)
```python
_NZ_PROFILE_STATUSES = ("ACTIVE",)

def _nz_one_active(db, model, org_id, employee_id, legal_entity_id, on: date, label, *, entity_scoped=False)
    # ACTIVE rows with effective_from <= on and (effective_to is null or >= on)
    # employee filter when employee_id is not None
    # entity_scoped (employer profile): first try legal_entity_id == the employee's; else legal_entity_id IS NULL
    # >1 row -> BadRequestException(f"Two ACTIVE New Zealand {label} versions overlap on {on}") (data error)
    # 0 rows -> None (the engine blocks with its own reason)

def _nz_tax_year(db, pay_date) -> str | None
    # the in-force NZ pack (tax_resolver.resolve_tax_configuration(db, "NZ", payroll_date=pay_date)) -> pack.tax_year;
    # none -> None (the engine blocks on the missing pack anyway)

def _nz_accumulators(db, org_id, employee_id, legal_entity_id, tax_year, pay_date) -> dict | None
    # if tax_year is None: return None
    # rows = SUM(amount) GROUP BY obligation over PayrollNzAccumulatorEntry
    #        WHERE org, employee, legal_entity_id IS NOT DISTINCT FROM the employee's, tax_year, pay_date < pay_date
    # return {obligation: Decimal(sum)} with EVERY obligation key present (explicit 0) - the engine
    #        distinguishes "known zero" from "missing" (NZ-013)

def _nz_hours(db, org_id, employee_id, period_start, period_end, work_pattern) -> (Decimal | None, str | None)
    # 1) approved attendance in [start, end]: sum(PayrollAttendanceRecord.hours parsed as Decimal) for status present
    #    -> ("ATTENDANCE") when any row exists AND every row has hours
    # 2) else work_pattern FIXED: contracted_hours_per_week × weeks in the period (period days / 7) -> "WORK_PATTERN"
    # 3) else (None, None) -> the engine marks minimum wage UNDETERMINABLE

def _nz_components(employee) -> dict | None
    # employee.compliance_fields.get("nz_components") if it is a dict, else None   (same idea as _jp_value)

def resolve_nz_calc_inputs(db, organization_id, employee, pay_date, run=None, period=None) -> dict:
    # m = _nz_models(); le = employee.legal_entity_id
    # employer = _nz_one_active(db, m.PayrollNzEmployerProfile, org, None, le, pay_date, "employer profile", entity_scoped=True)
    # profile  = _nz_one_active(db, m.PayrollNzEmployeeTaxProfile, org, employee.id, None, pay_date, "tax profile")
    # ks       = _nz_one_active(db, m.PayrollNzKiwiSaverElection, ...)
    # pattern  = _nz_one_active(db, m.PayrollNzWorkPatternVersion, ...)
    # notices  = APPROVED PayrollNzAuthorityDeduction for the employee, in force on pay_date, ordered (type, notice_id, version)
    # start, end = period or (run.period_start, run.period_end)
    # hours, source = _nz_hours(...)
    # kind = str(getattr(run, "nz_payment_kind", None) or "REGULAR").upper()  (validate in content.PAYMENT_KINDS else 400)
    # return {
    #   "nz_employer_profile": _facts(employer), "nz_tax_profile": _facts(profile), "nz_kiwisaver": _facts(ks),
    #   "nz_authority_deductions": [_facts(n) for n in notices], "nz_work_pattern": _facts(pattern),
    #   "nz_accumulators": _nz_accumulators(db, org, employee.id, le, _nz_tax_year(db, pay_date), pay_date),
    #   "nz_hours": hours, "nz_hours_source": source, "nz_payment_kind": kind,
    #   "nz_date_of_birth": employee.date_of_birth, "nz_components": _nz_components(employee),
    #   "nz_organization_id": org, "nz_legal_entity_id": le, "nz_employee_id": employee.id,
    # }
    # _facts(row) = dict of the model's columns (plain values) - the engine accepts dicts (P3 pack.field)

def calc_inputs(db, run=None, employee=None, resolved_pack=None, as_of=None, period=None) -> dict:
    # payday = getattr(run, "pay_date", None) or as_of
    # if payday is None: raise BadRequestException("New Zealand payroll needs the run's pay date (NZ-008).")
    #   - NEVER date.today() (Japan falls back to today; NZ must not)
    # return resolve_nz_calc_inputs(db, employee.organization_id, employee, payday, run=run, period=period)
```

### 3.6 Freeze, thaw, replay and fingerprint (twins of Japan 509–721)
```python
_NZ_CTX_DECIMALS = ("gross", "basic", "overtime", "hra", "special_allowance", "additional_compensation", "nz_hours")
_NZ_CTX_PLAIN = ("pay_frequency", "nz_payment_kind", "nz_hours_source", "nz_components",
                 "nz_organization_id", "nz_legal_entity_id", "nz_employee_id", "unpaid_leave_days")
_NZ_CTX_DATES = ("pay_date", "period_start", "period_end", "nz_date_of_birth", "date_of_birth")
_NZ_RECORD_KEYS = ("nz_employer_profile", "nz_tax_profile", "nz_kiwisaver", "nz_work_pattern")
_NZ_RATE_FIELDS = ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value",
                   "effective_from", "effective_to", "label")          # label: the P3 pending guard needs it
_NZ_SLAB_FIELDS = ("id", "rule_type", "filing_status", "tax_regime", "assessment_basis", "tax_column",
                   "tax_table_number", "jurisdiction_state", "rate_pct", "min_amount", "max_amount",
                   "flat_amount", "formula_expression", "tax_formula", "rate_label", "sort_order",
                   "effective_from", "effective_to")
_NZ_THAW_DATE_KEYS = {...every *_from/_to/_on, pay_date-like key...}
_NZ_THAW_DECIMAL_KEYS = {...every pct/amount/rate/hours key...}

def _json_safe(value)                     # copy Japan's
def nz_freeze_context(ctx, calculation_mode="standard") -> dict
    # {"version": 1, "calculationMode", "ctx": {...decimals/plain/dates},
    #  "records": {k: getattr(ctx, k) for k in _NZ_RECORD_KEYS}, "notices": ctx.nz_authority_deductions,
    #  "accumulators": ctx.nz_accumulators, "rateMap": {...}, "slabs": [...]} -> _json_safe
    # NOTE: the IRD number is never in ctx; ird_vault_id is an id only
def nz_thaw_context(frozen) -> PayrollContext       # version must be 1, else 400; rebuild Decimals/dates exactly
def nz_replay(frozen) -> PayrollResult               # calculate_payroll(nz_thaw_context(frozen), frozen["calculationMode"])
def nz_payslip_snapshot(result, frozen=None) -> dict | None
    # r = result.nz_result (or a dict); None -> None
    # {**r, "frozenContext": frozen} -> _json_safe
def nz_approval_fingerprint(db, run) -> str | None
    # NZ payslips of the run ordered by id: [{"employeeId", "resultHash": snap["hashes"]["resultHash"],
    #   "inputHash": ..., "packHash": ...}] -> sha256(canonical)   (hashing.canonical from P3)
```

### 3.7 Preflight and run transition
```python
PREFLIGHT_CODES = ("NZ_NO_PACK_IN_FORCE", "NZ_PACK_UNSIGNED", "NZ_EMPLOYER_PROFILE_MISSING",
    "NZ_EMPLOYER_NOT_VERIFIED", "NZ_TAX_PROFILE_MISSING", "NZ_IRD_NUMBER_NOT_ON_FILE",
    "NZ_KIWISAVER_ELECTION_MISSING", "NZ_WORK_PATTERN_MISSING", "NZ_HOURS_UNKNOWN",
    "NZ_ACCUMULATOR_GAP", "NZ_SNAPSHOT_MISSING", "NZ_CALCULATION_BLOCKED",
    "NZ_MIN_WAGE_EXCEPTION", "NZ_CS_SHORTFALL", "NZ_PAYMENT_KIND_UNSUPPORTED")

def nz_run_preflight(db, run) -> list[dict]
    # for each NZ payslip/employee of the run:
    #   inputs = resolve_nz_calc_inputs(db, run.organization_id, employee, run.pay_date, run=run)
    #   append {"code","employeeId","message"} for each missing/unhealthy item above
    #   snapshot exceptions (nz_result.exceptions) -> NZ_MIN_WAGE_EXCEPTION / NZ_CS_SHORTFALL
    #   accumulator gap: an earlier PAID NZ run in the same tax year for this employee with no RUN entries
    # pack: resolve_tax_configuration(db, "NZ", payroll_date=run.pay_date) None -> NZ_NO_PACK_IN_FORCE
    # messages never include identifiers beyond employee id

def _nz_run_items(db, run) -> list[PayslipItem]      # country_code == "NZ"

def before_run_transition(db, run, next_status, actor_id) -> None
    # items = _nz_run_items(); none -> return
    # APPROVED:
    #   missing snapshots -> 409 "New Zealand: N payslip(s) have no frozen NZ snapshot - recalculate"
    #   problems = [p for p in nz_run_preflight(db, run) if p["code"] != "NZ_SNAPSHOT_MISSING"]
    #   problems -> 409 listing codes + employee ids (P8 adds approvable run exceptions; until then refuse)
    #   run.nz_approval_fingerprint = nz_approval_fingerprint(db, run); return
    # AUTHORIZED / PAID: recomputed != stored -> 409 "approved calculation no longer matches - recalculate and approve again"
    # PAID: post_accumulators(db, run, actor_id)

def post_accumulators(db, run, actor_id) -> int
    # tax_year from each snapshot's pack; for each item, for (obligation, amount) in snap["accumulatorDeltas"]:
    #   skip if a RUN entry (payslip_item_id, obligation) exists          (idempotent)
    #   add PayrollNzAccumulatorEntry(org, legal_entity_id=item employee's, employee_id, tax_year, obligation,
    #        pay_date=run.pay_date, amount, entry_kind="RUN", run_id, payslip_item_id, result_hash, created_by_id=actor_id)
    # flush; return the count added
```

### 3.8 The 13 hooks and supporting functions
```python
def _nz_statutory_profile_errors(data) -> list
    # the shared EmployeeStatutoryProfile has no NZ columns: validate only nz_* attributes when present
    # (tax code supported, IRD state in enum, min-wage category in enum)
def _nz_profile_values(db, employee, data, previous) -> dict: return {}
def _nz_pack_activation_refusal(db, pack, actor_id) -> str | None: return nz_pack_activation_refusal(db, pack, actor_id)
def _nz_pack_holidays(db, year) -> list[dict]
    # in-force pack for date(year,12,31); NZ_PUBLIC_HOLIDAY slabs with jurisdiction_state IS NULL only
    # (national; PayrollHoliday has no region - regional anniversary days live in P5 decisions)
    # [] when no pack / no rows / NZCalculationBlockedError
def _nz_template_activation_refusal(db, template, actor_id) -> str | None   # NZ / NZ_* -> refuse
def _nz_payment_treatment(db, organization_id, run, items) -> dict: return {}
def _nz_payslip_hold_view(item) -> dict | None: return None
def _nz_statutory_editors(db, pack) -> set: return set()

NZ_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and the frozen NZ calculation snapshot"),
    ("WAGE_TIME_RECORDS", "Hours, pay rates and gross pay (Employment Relations Act; 6 years from content)"),
    ("HOLIDAY_LEAVE_RECORDS", "Holidays Act entitlement and leave records (6 years from content)"),
    ("TAX_RECORDS", "PAYE, KiwiSaver, ESCT, student loan and child-support records"),
    ("EMPLOYEE_IDENTITY", "IRD-number vault metadata and tax profiles"),
    ("ACCESS_LOGS", "IRD-number access events"),
    ("AUTHORITY_NOTICES", "Child-support and other authority notice versions (hash + evidence ref)"),
)
NZ_DECISIONS = {
    "D-1": ("Legal employer = organisation + legal entity", False),
    "D-2": ("Seed spec values as PENDING G1", False),
    "D-3": ("Payday filing JSON preview only until G3", False),
    "D-4": ("IRD numbers encrypted in the NZ vault", False),
    "D-5": ("Full Holidays Act; ELA 2028 staged only", False),
    "D-6": ("Deferred scope refused with reason codes", False),
    "D-7": ("Tax-record retention period", True),          # PENDING_DECISION - blocks launch
}
def _nz_evidence(db, tag)                    # copy _jp_evidence (SourceArtifact form_number, reviewer != creator)
def owner_decisions(db) -> list              # tag f"NZ-DECISION-{key}"
def _nz_decision_state(db, key) -> str
def _nz_retention_employee(db, employee_id, organization_id)        # 404 if not an NZ employee of the org
def _nz_retained_record_label(db, organization_id, employee_id)     # tax profiles / notices / ledger present
def _nz_has_statutory_profile(db, employee_id) -> bool
def _nz_is_report(report) -> bool                                    # country NZ or report_type NZ_*
def _nz_retention_settings()                 # NO ARGUMENTS (the platform calls it with none - Japan once broke this)
    # RetentionJurisdiction(country="NZ", label="New Zealand", categories=NZ_RETENTION_CATEGORIES,
    #   period_decision="D-7", end_decision="D-7", decision_reference="NZ-RETENTION", decision_state=_nz_decision_state,
    #   validate_employee=_nz_retention_employee, retained_record_label=..., has_statutory_profile=..., report_matches=...)
def statutory_summary(db) -> dict
    # {"jurisdiction": "NZ", "spec", "available": False, "packs": [...incl NZ-ELA-2028...],
    #  "pendingRows": count of "[PENDING G1]", "emptyTables": [names from NZ_EMPTY_TABLES with no rows],
    #  "activeEmployerProfiles", "verifiedEmployerProfiles", "activeTaxProfiles", "activeKiwiSaverElections",
    #  "approvedNotices", "decisions": owner_decisions(db), "readiness": {"gatesImplemented": False}, "note"}
def nz_unmet_requirements(db) -> list[str]   # P4 stub: ["New Zealand release gates G1–G7 are not implemented yet (Phase 9)."]
def _nz_service_registry_transition(db, target, reason, actor_id=None, as_of=None)
    # copy _jp_service_registry_transition with label "New Zealand" and readiness=lambda: (nz_unmet_requirements(db), {})

JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_nz_statutory_profile_errors",
    "statutory_profile_values": "_nz_profile_values",
    "pack_activation_refusal": "_nz_pack_activation_refusal",
    "retention_settings": "_nz_retention_settings",
    "service_registry_transition": "_nz_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_nz_statutory_editors",
    "template_activation_refusal": "_nz_template_activation_refusal",
    "pack_holidays": "_nz_pack_holidays",
    "payment_treatment": "_nz_payment_treatment",
    "payslip_hold_view": "_nz_payslip_hold_view",
}
```

### 3.9 Employee summary (for the P7 panel)
```python
def employee_summary(db, org_id, employee_id) -> dict
    # {"employeeId", "irdNumber": {"onFile", "masked"}, "taxProfiles": [...versions...],
    #  "kiwisaver": [...], "workPatterns": [...], "notices": [{id, type, noticeId, version, status, effective dates,
    #  amount}], "accumulators": {tax_year: {obligation: sum}}, "lastSnapshot": nz_result without frozenContext}
```

---

## 4. `nz_org_router.py` (new)

```python
"""New Zealand organisation API (ZP-NZ-ENG-001 §12) — dormant: 404 unless NZ onboarding is
enabled and the caller's organisation is a New Zealand employer."""
from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.core.exceptions import NotFoundException
from app.database import get_db
from app.modules.payroll import new_zealand_service as nz

def require_nz_tenant(current_user=Depends(get_current_payroll_operator), db: Session = Depends(get_db)):
    # copy require_japan_tenant (japan_org_router.py:32): nz_dormancy.onboarding_enabled() and
    # service.get_company_details(db, org).jurisdiction_country resolves to "NZ"; else NotFoundException
router = APIRouter(prefix="/new-zealand", tags=["New Zealand (Organisation)"],
                   dependencies=[Depends(require_nz_tenant)])
def _org_id(user) -> int; def _actor(user) -> int | None; def _commit(db, row)   # copy Japan's 50–75
```

| # | Method / path | Handler | Auth | Service call |
|---|---|---|---|---|
| 1 | GET `/summary` | `nz_summary` | operator | `statutory_summary(db)` (org-scoped counts) |
| 2 | GET `/readiness` | `nz_readiness` | operator | `{"unmet": nz_unmet_requirements(db)}` |
| 3 | GET `/employer-profiles` | `nz_list_employer_profiles` | operator | list versions |
| 4 | POST `/employer-profiles` | `nz_create_employer_profile` | admin | `record_nz_employer_profile` (body: fields + `reason`) |
| 5 | POST `/employer-profiles/{row_id}/approve` | `nz_approve_employer_profile` | admin | four-eyes |
| 6 | POST `/employer-profiles/{row_id}/verify` | `nz_verify_employer_profile` | admin | `{outcome, reason}` |
| 7 | GET / POST / DELETE `/employer-profiles/{row_id}/ird-number` | `nz_get_employer_ird`, `nz_set_employer_ird`, `nz_delete_employer_ird` | operator / admin | vault (EMPLOYER subject); the set call links `employer_ird_vault_id` on a **new** DRAFT version |
| 8 | GET / POST `/employees/{eid}/tax-profiles` | `nz_list_tax_profiles`, `nz_create_tax_profile` | operator / admin | |
| 9 | POST `/tax-profiles/{row_id}/approve` | `nz_approve_tax_profile` | admin | |
| 10 | GET / POST `/employees/{eid}/kiwisaver` | `nz_list_kiwisaver`, `nz_create_kiwisaver` | | |
| 11 | POST `/kiwisaver/{row_id}/approve` | `nz_approve_kiwisaver` | admin | |
| 12 | GET / POST `/employees/{eid}/work-patterns` | `nz_list_work_patterns`, `nz_create_work_pattern` | | |
| 13 | POST `/work-patterns/{row_id}/approve` | `nz_approve_work_pattern` | admin | |
| 14 | GET `/employees/{eid}/authority-deductions` | `nz_list_notices` | operator | |
| 15 | POST `/employees/{eid}/authority-deductions` (multipart: `file`, `meta` JSON) | `nz_import_notice` | admin | `import_nz_authority_notice` |
| 16 | POST `/authority-deductions/{row_id}/approve` | `nz_approve_notice` | admin | |
| 17 | POST `/authority-deductions/{row_id}/revoke` | `nz_revoke_notice` | admin | `{reason}` |
| 18 | GET / POST `/employees/{eid}/opening-balances` | `nz_list_opening_balances`, `nz_request_opening_balance` | | |
| 19 | POST `/opening-balances/{request_id}/approve` | `nz_approve_opening_balance` | admin | |
| 20 | GET / POST / DELETE `/employees/{eid}/ird-number` | `nz_get_ird`, `nz_set_ird`, `nz_delete_ird` | operator / admin / admin | GET → `{"onFile", "masked"}` only |
| 21 | POST `/ird-numbers/{vault_id}/reveal-requests` | `nz_request_ird_reveal` | admin | `{reason}` |
| 22 | POST `/ird-numbers/{vault_id}/reveal-approvals` | `nz_approve_ird_reveal` | admin | |
| 23 | POST `/ird-numbers/{vault_id}/reveal` | `nz_reveal_ird` | admin | single use |
| 24 | GET `/runs/{run_id}/preflight` | `nz_run_preflight` | operator | |
| 25 | GET `/runs/{run_id}/fingerprint` | `nz_run_fingerprint` | operator | `{"stored", "current", "matches"}` |
| 26 | GET `/employees/{eid}/summary` | `nz_employee_summary` | operator | |

**Rules every handler follows:**
- Resolve `org_id` from the user, **never** from the path.
- Every `employee_id` and `row_id` is checked against `org_id` inside the service (cross-tenant attempts get 404).
- A write needs a `reason` in the body.
- Responses use camelCase dicts built by a small `_view(row, fields)` helper.
- **No IRD digits in any response except #23.**
- **The router must not import models directly**; it goes through the service.

---

## 5. Edits to existing files (anchors)

| File | Anchor | Edit |
|---|---|---|
| `jurisdiction_hooks.py` | `_MODULES` dict (line 27) | `"NZ": "app.modules.payroll.new_zealand_service",`. **Add only in the same commit as all 13 hooks.** |
| `router.py` | the Japan include (`payroll_router.include_router(japan_org_router...)`) | add `from app.modules.payroll import nz_org_router` and `payroll_router.include_router(nz_org_router.router)` |
| `engine/resolver.py` | `japan_inputs: dict \| None = None,` (line ~281) and `**(japan_inputs or {}),` (~486) | add `nz_inputs: dict \| None = None,` and `**(nz_inputs or {}),` |
| `service.py` ~20419 (preview) | after the `japan_inputs = (...)` block | `nz_inputs = (jurisdiction_hooks.call("NZ", "calc_inputs", db, None, emp, None, as_of=<the run's pay date passed to preview>, period=(period_start, period_end) if both else None) if emp_country == "NZ" else None)`. If preview has no pay date, pass `as_of=None` and let `calc_inputs` raise the clear 400. **Never `period_end` or `date.today()`.** |
| `service.py` ~20614 | `japan_inputs=japan_inputs,` | add `nz_inputs=nz_inputs,` |
| `service.py` ~25646 (generate) | after the Japan block | `nz_inputs = (jurisdiction_hooks.call("NZ", "calc_inputs", db, run, employee, resolved_pack, period=(run.period_start, run.period_end)) if country == "NZ" else None)` |
| `service.py` ~25781 | `japan_inputs=japan_inputs,` | add `nz_inputs=nz_inputs,` |
| `service.py` ~25816 | `japan_frozen = _jp_service.jp_freeze_context(...)` | `nz_frozen = _nz_service.nz_freeze_context(ctx, calculation_mode) if country == "NZ" else None` |
| `service.py` ~25989 | the `"jp_calculation_snapshot": ...` entry | `"nz_calculation_snapshot": (_nz_service.nz_payslip_snapshot(result, frozen=nz_frozen) if country == "NZ" else None),` |
| `service.py` ~32730 (add_payslip_item) | the Japan block, plus ~32880 / ~32904 / ~32949 | the same three additions (`calc_inputs` with `run`, `nz_inputs=`, freeze + snapshot) |
| `service.py` ~33652 (`_serialize_payslip`) | after `"jpCalculationSnapshot": ...` | `"nzCalculationSnapshot": ({k: v for k, v in (item.nz_calculation_snapshot or {}).items() if k != "frozenContext"} if (item.country_code or country) == "NZ" and item.nz_calculation_snapshot else None),` |
| `service.py` run create/update | where `jp_payment_kind` is copied from the schema | copy `nz_payment_kind` from `data.nzPaymentKind` (validate it is in `content.PAYMENT_KINDS`) |
| `schemas.py` | the `jpPaymentKind` fields on run create/update/response; `jpCalculationSnapshot` on `PayslipItemResponse` | `nzPaymentKind: Optional[Literal["REGULAR","OUT_OF_CYCLE","LUMP_SUM","FINAL","HOLIDAY_PAY_ADVANCE","CORRECTION"]] = None`; `nzCalculationSnapshot: Optional[dict] = None` |
| `employee_validation.py` | `_DORMANT_STRATEGIES` (line ~1963) and `_dormant_strategy` | Add `"NZ": NZEmployeeValidation` and a branch `if code == "NZ": from app.modules.payroll import nz_dormancy; return strategy if nz_dormancy.onboarding_enabled() else None`. `NZEmployeeValidation(EmployeeValidationStrategy)` requires `pay_frequency` in Weekly/Fortnightly/FourWeekly/Monthly and `date_of_birth`, and refuses any `compliance_fields` key matching `ird`, `tax_number` or `irdNumber` ("use the IRD-number vault"). `SENSITIVE_FIELDS = ("ird_number",)`. **Check first:** JP is in neither map today. If Japan employees bypass validation another way, document why NZ differs. |

The `service.py` symbol `_nz_service` is a local import inside each function, as Japan does with `_jp_service`.

---

## 6. Tests

`tests/_nz_service_helpers.py` provides:
- `make_nz_org(db)`: `_mx_employer_helpers.make_org`, then set `NZ_TENANT_ONBOARDING_ENABLED` via monkeypatch and set the company jurisdiction to NZ;
- `make_nz_employee(db, org, **kw)`;
- `seed_test_pack(db)`: `seed_nz_pack`, then strip PENDING labels and fill the TEST tables from P3 `_nz_engine_helpers`, then set the pack Active;
- `two_users(db, org)`: a preparer and an approver;
- the keyring fixture from `test_nz_ird_number.py`.

| File | Test functions |
|---|---|
| `test_nz_phase4_hooks.py` | `test_nz_is_a_registered_module`, `test_every_hook_resolves[13 names]`, `test_retention_settings_takes_no_arguments`, `test_retention_report_works_for_all_countries_after_nz` (regression for the Japan incident), `test_pack_activation_hook_refuses_pending`, `test_pack_holidays_empty_until_g2`, `test_template_refusal`, `test_registry_transition_refuses_available`, `test_statutory_summary_shape` |
| `test_nz_phase4_versions.py` | `test_create_is_draft_with_previous_version`, `test_self_approval_refused_and_audited`, `test_approval_supersedes_and_closes_previous`, `test_backdated_version_refused`, `test_unknown_field_refused`, `test_reason_required`, `test_refused_tax_code_message`, `test_stc_requires_certificate`, `test_valid_ird_state_requires_vault`, `test_employee_rate_checked_against_pack`, `test_employer_profile_legal_entity_must_belong_to_org`, `test_remittance_class_checked_against_pack_threshold`, `test_verify_needs_second_person_and_ird`, `test_notice_import_hashes_and_versions`, `test_identical_reupload_is_idempotent`, `test_notice_body_never_stored`, `test_notice_approve_supersedes_previous`, `test_opening_balance_needs_second_person` |
| `test_nz_phase4_vault.py` | `test_create_stores_ciphertext_only`, `test_duplicate_number_refused`, `test_second_active_number_refused`, `test_reveal_requires_request_and_other_approver`, `test_reveal_is_single_use`, `test_reveal_only_by_requester`, `test_events_written_for_each_step`, `test_list_and_get_return_masked_only`, `test_delete_clears_ciphertext`, `test_errors_never_echo_digits`, `test_employer_subject_bound_to_legal_entity` |
| `test_nz_phase4_runs.py` | `test_calc_inputs_use_payday_not_period_end` (period 26 Mar–8 Apr, payday 8 Apr selects the 1-Apr profile), `test_calc_inputs_refuse_without_payday`, `test_accumulators_explicit_zero_first_payday`, `test_accumulators_sum_before_payday_only`, `test_accumulators_shared_across_pay_groups_same_entity`, `test_accumulators_separate_per_legal_entity`, `test_hours_from_attendance_then_work_pattern`, `test_generate_run_stores_snapshot`, `test_snapshot_has_no_ird_or_dob_plaintext`, `test_replay_reproduces_result_hash`, `test_approval_refused_without_snapshot`, `test_approval_refused_unverified_employer`, `test_approval_refused_on_min_wage_exception`, `test_fingerprint_stored_on_approval`, `test_changed_snapshot_breaks_fingerprint`, `test_paid_posts_accumulators_once`, `test_paid_retry_posts_nothing`, `test_payment_kind_is_per_run_not_sticky` |
| `test_nz_phase4_api.py` | `test_routes_404_when_dormant`, `test_routes_404_for_non_nz_org`, `test_cross_tenant_ids_404`, `test_reads_need_operator_writes_need_admin`, one happy-path test per route group, `test_get_ird_returns_masked`, `test_reveal_response_is_the_only_digits`, `test_serialized_payslip_strips_frozen_context`, `test_run_create_accepts_nz_payment_kind` |

Also keep green: `tests/test_mexico_scaffolding.py` (add `"NZ"` to its `_MODULES` expectation), `tests/privacy/test_route_registry.py` (after regeneration), and the full suite.

## 7. Definition of done
- [ ] The 13 hooks resolve; NZ is in `_MODULES`; the Japan and retention suites are green.
- [ ] Every NZ route returns 404 while dormant; the route registry is regenerated and its test is green.
- [ ] Payday-based selection is proven (straddle test). No `date.today()` in any NZ calculation path.
- [ ] Approval, fingerprint and PAID accumulator posting work and are idempotent.
- [ ] The vault reveal is four-eyes and single use; no digits appear anywhere else (caplog plus a response scan).
- [ ] The full backend suite is green. One local commit (`New Zealand P4: ...`), not pushed.
