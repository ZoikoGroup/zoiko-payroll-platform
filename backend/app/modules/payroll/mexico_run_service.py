"""
modules/payroll/mexico_run_service.py
-------------------------------------
Mexico payroll run integration (ZP-MX-ENG-001 Phase 6, spec §13;
docs/mexico/MEXICO_PHASE_6_PLAN.md).

- calc_inputs: the ONLY production entry to a Mexican calculation. Guarded
  (defence in depth, plan §1): refused unless Mexico onboarding is enabled on
  this platform AND the employee's organisation is Mexican; then builds every
  Phase 5 engine input from the database, read-only (MX-039), as of the run's
  pay date — never the server date (MX-004).
- generation: a blocked employee becomes a FAILED sentinel payslip (no
  fabricated figures) plus preflight exception rows; dormancy refusals abort.
- approval (MX-040): a fingerprint of every content row, input and
  classification, re-verified on read; commit writes every ledger in the same
  transaction as the APPROVED status (MX-039), idempotently.
- reset: deletes the run's ledger rows only while no downstream lifecycle has
  acted (run_downstream_actions; Phases 7, 8 and 10 register their checks).
- lifecycles stay separate (MX-041): AUTHORIZED / PAID refused until CFDI
  (Phase 7) and bank settlement (Phase 10); every MX payment item is held.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.modules.payroll import mexico_dormancy
from app.modules.payroll.engine.countries import mexico_content as _content
from app.modules.payroll.engine.countries.mexico import MXBlock

MX = "MX"
SPEC = _content.SPEC

# Codes that refuse the WHOLE operation (dormancy / scope), never a sentinel.
GUARD_CODES = ("MX_DORMANT", "MX_ORG_NOT_MEXICAN", "MX_RUN_ORG_MISMATCH", "MX_RUN_TYPE_PHASE9",
               "MX_PAY_DATE_MISSING")
RUN_TYPES = ("ORDINARY", "AGUINALDO", "PTU", "FINIQUITO", "CORRECTION")
BUILT_RUN_TYPES = ("ORDINARY", "CORRECTION", "AGUINALDO", "FINIQUITO", "PTU")   # 9a, 9b, 9c, 9d

# Platform earning codes of the lines Phase 6 builds (each needs an approved
# Mexico earning classification, MX-005 — none is assumed).
SALARY_CODE = "MX_SALARY"
OVERTIME_CODE = "MX_OVERTIME"
SUNDAY_PREMIUM_CODE = "MX_SUNDAY_PREMIUM"

_FIXED_SALARY_DAYS = {"QUINCENAL_15": Decimal("15"), "MONTHLY": Decimal("30")}   # D13 FIXED convention
_ZERO = Decimal("0")


# ── small helpers ────────────────────────────────────────────────────────────

def _plain(value):
    if isinstance(value, Decimal):
        return str(value.normalize()) if value == value.to_integral() else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(_plain(value), sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _dec(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def _overlaps(row_from, row_to, start, end) -> bool:
    return (row_from is None or row_from <= end) and (row_to is None or row_to >= start)


def _in_force(row_from, row_to, on) -> bool:
    return (row_from is None or row_from <= on) and (row_to is None or row_to >= on)


def _audit(db, **kw):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, **kw)


# ── 1. Guard (plan §1) ───────────────────────────────────────────────────────

def guard(db: Session, employee, run=None) -> None:
    from app.modules.payroll import service

    org_id = getattr(employee, "organization_id", None)
    if not mexico_dormancy.onboarding_enabled():
        raise MXBlock("MX_DORMANT", mexico_dormancy.DORMANT_MESSAGE, org_id)
    if not mexico_dormancy.is_mexico(service._resolve_org_country(db, org_id)):
        raise MXBlock("MX_ORG_NOT_MEXICAN", "the employee's organisation payroll jurisdiction is not Mexico", org_id)
    if run is not None and run.organization_id != org_id:
        raise MXBlock("MX_RUN_ORG_MISMATCH", "the run belongs to another organisation", org_id)
    if run is not None and (run.mx_run_type or "ORDINARY") not in BUILT_RUN_TYPES:
        raise MXBlock("MX_RUN_TYPE_PHASE9", f"{run.mx_run_type} runs are built in a later Phase 9 sub-phase", org_id)


# ── 1b. Read-only policy for previews (MX-039, OOS-8) ───────────────────────

def read_only_policy(db: Session, organization_id: int):
    """The org's default payroll policy if it exists — never created here
    (the shared get_active_policy get-or-creates; a Mexican preview must not
    write). None means the defaults that policy would be seeded with."""
    from app.modules.payroll.policy.models import PayrollPolicy

    if not organization_id:
        return None
    return (db.query(PayrollPolicy)
            .filter(PayrollPolicy.organization_id == organization_id, PayrollPolicy.is_default == True)  # noqa: E712
            .first())


def read_only_allowance_components(policy) -> list:
    return [{"key": c.key, "label": c.label, "pct": c.pct, "flat_amount": c.flat_amount}
            for c in (getattr(policy, "allowance_components", None) or [])]


# ── 2. Period (plan §3, D3, D13) ─────────────────────────────────────────────

def run_period_kind(start: date, end: date) -> Optional[str]:
    """The Art. 96 period a run's own dates describe — calendar arithmetic
    only; anything else (e.g. 14 days) is None → unsupported (Phase 5 Q3)."""
    days = (end - start).days + 1
    last = calendar.monthrange(start.year, start.month)[1]
    if days == 1:
        return "DAILY"
    if days == 7:
        return "WEEKLY_7"
    if days == 10:
        return "DECENAL_10"
    if start.year == end.year and start.month == end.month:
        if start.day == 1 and end.day == 15:
            return "QUINCENAL_15"
        if start.day == 16 and end.day == last:
            return "QUINCENAL_15"
        if start.day == 1 and end.day == last:
            return "MONTHLY"
    return None


def payment_period(profile, start: date, end: date) -> str:
    code = getattr(profile, "mx_pay_frequency_code", None)
    if not _content.MX_PAY_FREQUENCY_ISR_PERIOD:
        raise MXBlock("MX_PAY_FREQUENCY_MAPPING_MISSING",
                      "the S28 c_PeriodicidadPago → Art. 96 period mapping is not transcribed yet")
    mapped = _content.MX_PAY_FREQUENCY_ISR_PERIOD.get(code)
    if mapped is None:
        raise MXBlock("MX_PAY_FREQUENCY_MAPPING_MISSING", f"pay-frequency code {code!r} has no Art. 96 period")
    actual = run_period_kind(start, end)
    if actual is None:
        raise MXBlock("MX_PERIOD_UNSUPPORTED", f"a {start.isoformat()}–{end.isoformat()} period has no Art. 96 tariff")
    if actual != mapped:
        raise MXBlock("MX_PAY_FREQUENCY_MISMATCH",
                      f"the employee's pay frequency is {mapped} but the run period is {actual}")
    return mapped


def salary_days(period: str, start: date, end: date, convention: Optional[str]) -> Decimal:
    calendar_days = Decimal((end - start).days + 1)
    if period not in _FIXED_SALARY_DAYS:
        return calendar_days
    if convention == "CALENDAR":
        return calendar_days
    if convention == "FIXED":
        return _FIXED_SALARY_DAYS[period]
    raise MXBlock("MX_SALARY_DAYS_CONVENTION_UNSET",
                  "the employer labour policy has no salary-days convention (CALENDAR / FIXED) for "
                  f"{period} periods (Phase 6 D13)")


def _boundaries(rows, start: date, end: date) -> list:
    """Dates inside (start, end] where a pack row starts or stops applying."""
    out = set()
    for r in rows:
        f, t = getattr(r, "effective_from", None), getattr(r, "effective_to", None)
        if f is not None and start < f <= end:
            out.add(f)
        if t is not None and start <= t < end:
            out.add(t + timedelta(days=1))
    return sorted(out)


def segments(db: Session, pack, start: date, end: date) -> list:
    """Contribution segments with the national rows in force on each (MX-021);
    contribution days are always calendar days (D13)."""
    from app.modules.payroll import mexico_service, service

    rates, slabs = mexico_service._pack_rows(db, pack)
    cuts = [start] + _boundaries(list(rates) + list(slabs), start, end) + [end + timedelta(days=1)]
    out = []
    for a, b in zip(cuts, cuts[1:]):
        rate_map, seg_slabs = service.pack_rows_for_golden(db, pack, a)
        out.append({"start": a, "end": b - timedelta(days=1), "days": Decimal((b - a).days),
                    "rate_map": rate_map, "slabs": seg_slabs})
    return out


# ── 3. Employer / employee facts (plan §3) ───────────────────────────────────

def _profile(db: Session, employee, on: date):
    from app.modules.payroll import mexico_employee_service

    prof = mexico_employee_service._profile_on(db, employee.id, on)
    if prof is None:
        raise MXBlock("MX_PROFILE_MISSING", "the employee has no Mexico statutory profile in force on the pay date")
    return prof


def _registration(db: Session, prof, on: date):
    from app.modules.payroll.models import PayrollMxImssRegistration as R

    reg = db.get(R, prof.mx_imss_registration_id) if prof.mx_imss_registration_id else None
    if reg is None or reg.status != "ACTIVE" or not _in_force(reg.effective_from, reg.effective_to, on):
        return None
    return reg


def _risk_premium(db: Session, reg, start: date, end: date):
    from app.modules.payroll.models import PayrollMxRiskPremium as P

    if reg is None:
        return None
    return (db.query(P).filter(P.registration_id == reg.id, P.status == "ACTIVE", P.period_from <= start,
                               P.period_to >= end).order_by(P.period_from.desc()).first())


def _labor_policy(db: Session, reg, on: date):
    from app.modules.payroll.models import PayrollMxLaborPolicy as L

    if reg is None:
        return None
    return (db.query(L).filter(L.employer_profile_id == reg.employer_profile_id, L.status == "ACTIVE",
                               L.effective_from <= on, (L.effective_to.is_(None)) | (L.effective_to >= on))
            .order_by(L.effective_from.desc()).first())


def _classifications(db: Session, org_id: int, on: date) -> dict:
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    rows = (db.query(C).filter((C.organization_id == org_id) | (C.organization_id.is_(None)),
                               C.status.in_(("ACTIVE", "SUPERSEDED")), C.effective_from <= on,
                               (C.effective_to.is_(None)) | (C.effective_to >= on)).all())
    out: dict = {}
    for r in sorted(rows, key=lambda r: (r.organization_id is not None, r.effective_from)):   # org row wins
        out[r.earning_code] = {
            "id": r.id, "earning_code": r.earning_code, "version": r.version, "status": r.status,
            "effective_from": r.effective_from, "effective_to": r.effective_to, "isr_treatment": r.isr_treatment,
            "isr_exempt_rule_key": r.isr_exempt_rule_key, "sbc_treatment": r.sbc_treatment,
            "infonavit_included": r.infonavit_included, "isn_default_included": r.isn_default_included,
            "isn_state_overrides": r.isn_state_overrides, "ptu_wage_base_included": r.ptu_wage_base_included,
            "cfdi_node_type": r.cfdi_node_type, "cfdi_concept_code": r.cfdi_concept_code}
    return out


def _notices(db: Session, employee_id: int, start: date, end: date) -> list:
    from app.modules.payroll.models import PayrollMxInfonavitNotice as N

    rows = db.query(N).filter(N.employee_id == employee_id).order_by(N.id).all()
    return [{"id": n.id, "credit_number": n.credit_number, "notice_type": n.notice_type,
             "discount_method": n.discount_method, "discount_value": n.discount_value,
             "effective_from": n.effective_from, "effective_to": n.effective_to, "status": n.status,
             "authority_reference": n.authority_reference}
            for n in rows if _overlaps(n.effective_from, n.effective_to, start, end)]


def _isn_state_pack(db: Session, state: Optional[str], on: date):
    from app.modules.payroll import mexico_employer_service, service

    if not state:
        return None
    pack = mexico_employer_service._isn_pack(db, state)
    if pack is None:
        return None
    rate_map, _slabs = service.pack_rows_for_golden(db, pack, on)
    return {"state": state, "status": pack.status, "pack_id": pack.pack_id, "version": pack.version,
            "rate_map": rate_map}


def _attendance_counts(db: Session, org_id: int, employee_id: int, start: date, end: date, records=None) -> dict:
    """absence / incapacity days from the shared attendance rows (leave
    requests are synced onto them): absent or unpaid leave → absence; sick
    leave → incapacity. Both BLOCK in the engine (Phase 5 Q6)."""
    from app.modules.payroll.models import PayrollAttendanceRecord as A

    if records is None:
        records = db.query(A).filter(A.organization_id == org_id, A.employee_id == employee_id,
                                     A.date >= start, A.date <= end).all()
    absence = incapacity = _ZERO
    for r in records:
        weight = Decimal("0.5") if getattr(r, "is_half_day", False) else Decimal("1")
        st, lt = (r.status or "").lower(), (r.leave_type or "").lower()
        if st == "absent" or (st == "leave" and lt in ("", "unpaid")):
            absence += weight
        elif st == "leave" and lt == "sick":
            incapacity += weight
    return {"absence_days": absence, "incapacity_days": incapacity}


def _hours(db: Session, employee_id: int, start: date, end: date):
    from app.modules.payroll.models import PayrollMxApprovedHours as H

    rows = (db.query(H).filter(H.employee_id == employee_id, H.status == "APPROVED", H.week_start >= start,
                               H.week_start <= end).order_by(H.week_start).all())
    if not rows:
        return None, []
    overtime = sum((_dec(r.overtime_hours) for r in rows), _ZERO)
    hours = {"weeks": [{"week_start": r.week_start, "overtime_hours": _dec(r.overtime_hours)} for r in rows],
             "sundays_worked": sum(int(r.sundays_worked or 0) for r in rows),
             "holiday_days": sum(int(r.rest_days_worked or 0) for r in rows),
             "overtime_code": OVERTIME_CODE, "sunday_premium_code": SUNDAY_PREMIUM_CODE}
    if overtime > 0:
        # No transcribed rule derives an hourly rate from the daily salary.
        raise MXBlock("MX_HOURLY_RATE_RULE_MISSING",
                      "approved overtime needs an hourly-rate rule, which is not transcribed yet (S26)")
    return hours, [{"id": r.id, "week_start": r.week_start, "ordinary": r.ordinary_hours, "overtime": r.overtime_hours,
                    "sundays": r.sundays_worked, "rest_days": r.rest_days_worked} for r in rows]


def bimester_key(on: date) -> str:
    return f"{on.year}-B{(on.month - 1) // 2 + 1}"


def _previous_bimester(on: date) -> str:
    first_month = ((on.month - 1) // 2) * 2 + 1
    prev = date(on.year, first_month, 1) - timedelta(days=1)
    return bimester_key(prev)


def _accumulator(db: Session, employee_id: int, salary_type: Optional[str], on: date) -> dict:
    """Prior-bimester variable pay (MX-020) from committed rows only; D4:
    FIXED → {0, 0}; VARIABLE / MIXED without any committed or approved
    opening row for that bimester → BLOCK."""
    from app.modules.payroll.models import PayrollMxVariableAccumulator as V

    key = _previous_bimester(on)
    if (salary_type or "").upper() == "FIXED":
        return {"total": _ZERO, "days": _ZERO, "bimester": key, "rows": []}
    rows = (db.query(V).filter(V.employee_id == employee_id, V.bimester_key == key)
            .filter((V.kind == "RUN") | ((V.kind == "OPENING") & V.approved_by_id.isnot(None))).all())
    if not rows:
        raise MXBlock("MX_VARIABLE_OPENING_BALANCE_MISSING",
                      f"no committed or approved opening variable pay for bimester {key} (Phase 6 D4)")
    return {"total": sum((_dec(r.variable_total) for r in rows), _ZERO),
            "days": sum((_dec(r.days) for r in rows), _ZERO), "bimester": key, "rows": [r.id for r in rows]}


_NOT_COMMITTED = datetime.max


def _payment_order(run, on: date) -> tuple:
    """Deterministic order of the month's payments: (pay date, committedAt,
    run id). A run not committed yet sorts after every committed run of its
    pay date; a preview (run None) sorts after everything on its date."""
    if run is None:
        return (on, _NOT_COMMITTED, float("inf"))
    committed = (run.mx_approval_fingerprint or {}).get("committedAt")
    return (on, datetime.fromisoformat(committed) if committed else _NOT_COMMITTED, run.id)


def _month_to_date(db: Session, employee_id: int, run, on: date) -> dict:
    """Committed Mexican payslips of the same pay-date month that come BEFORE
    this one in `_payment_order` (subsidy, MX-013): an earlier pay date, or the
    same pay date committed earlier (run id breaks an exact tie). A payment
    ordered after this one never counts, so committing another run — a later
    pay date, or the same pay date afterwards, in either id order — cannot
    change (and invalidate) an already committed run's inputs.

    Phase 9a corrections: a committed CORRECTION payslip adds only its delta
    (corrected − original), and only to runs committed after it (or not yet
    committed); a correction run's own calculation leaves out the payslips it
    replaces (and their earlier chain) — mexico_correction_service."""
    from app.modules.payroll import mexico_correction_service as corrections
    from app.modules.payroll.models import PayrollRun, PayslipItem

    me = _payment_order(run, on)
    replaced = corrections.replaced_chain(db, run)
    my_committed_at = (getattr(run, "mx_approval_fingerprint", None) or {}).get("committedAt") if run is not None else None
    q = (db.query(PayslipItem, PayrollRun).join(PayrollRun, PayrollRun.id == PayslipItem.payroll_run_id)
         .filter(PayslipItem.employee_id == employee_id, PayslipItem.mx_calculation_snapshot.isnot(None)))
    taxable = applied = _ZERO
    for item, r in q.all():
        if run is not None and r.id == run.id:
            continue
        if not (r.pay_date.year == on.year and r.pay_date.month == on.month):
            continue
        if not (r.mx_approval_fingerprint or {}).get("committedAt"):
            continue
        if _payment_order(r, r.pay_date) >= me or item.id in replaced:
            continue
        part = corrections.contribution(db, item, r, run, my_committed_at)
        if part is None:
            continue
        taxable += part[0]
        applied += part[1]
    return {"taxable": taxable, "subsidy_applied": applied}


def _bank(employee) -> dict:
    return {"bank_name": getattr(employee, "bank_name", None), "bank_account": getattr(employee, "bank_account", None),
            "clabe": ((getattr(employee, "compliance_fields", None) or {}).get("clabe"))}


# ── 4. calc_inputs (the hook) ────────────────────────────────────────────────

def calc_inputs(db: Session, run, employee, resolved_pack=None, as_of: Optional[date] = None, *,
                period: Optional[tuple] = None, allowance_items: Optional[list] = None,
                attendance_records: Optional[list] = None) -> dict:
    """PayrollContext kwargs for one Mexican employee — read-only. `run` None
    = preview (pay date = as_of, the preview's period end)."""
    from app.modules.payroll import mexico_employer_service, service

    guard(db, employee, run)
    on = run.pay_date if run is not None else as_of
    if on is None:
        raise MXBlock("MX_PAY_DATE_MISSING", "a Mexican calculation needs the pay date (MX-004); none was given",
                      employee.organization_id)
    start, end = (run.period_start, run.period_end) if run is not None else (period or (None, None))
    if start is None or end is None:
        raise MXBlock("MX_PAY_DATE_MISSING", "a Mexican calculation needs the period start and end",
                      employee.organization_id)

    pack = resolved_pack[2] if resolved_pack else None
    if pack is None:
        pack = mexico_employer_service._active_national_pack(db, on)
    if pack is None:
        raise MXBlock("MX_NO_ACTIVE_PACK", f"no Active Mexico national pack covers {on.isoformat()}")
    pay_rates, pay_slabs = service.pack_rows_for_golden(db, pack, on)
    run_type = (run.mx_run_type or "ORDINARY") if run is not None else "ORDINARY"
    if run_type == "AGUINALDO":
        return _aguinaldo_inputs(db, run, employee, pack, pay_rates, pay_slabs)
    if run_type == "FINIQUITO":
        return _finiquito_inputs(db, run, employee, pack, pay_rates, pay_slabs)
    if run_type == "PTU":
        return _ptu_inputs(db, run, employee, pack, pay_rates, pay_slabs)

    prof = _profile(db, employee, on)
    reg = _registration(db, prof, on)
    premium = _risk_premium(db, reg, start, end)
    policy_row = _labor_policy(db, reg, on)
    if policy_row is not None and policy_row.floor_check_status != "PASS":
        raise MXBlock("MX_LABOR_POLICY_FLOOR_NOT_PASS", "the employer labour policy has not passed its floor check")
    tariff = payment_period(prof, start, end)
    # Phase 9c: an approved termination ends the employment — the final period
    # pays to the termination date; a later period pays nothing.
    from app.modules.payroll import mexico_termination_service

    ended = mexico_termination_service.settling(db, employee.id)
    final_period = None
    if ended is not None and ended.termination_date < end:
        if ended.termination_date < start:
            raise MXBlock("MX_EMPLOYEE_TERMINATED",
                          f"the employment ended on {ended.termination_date.isoformat()}, before this period",
                          employee.organization_id)
        if tariff in _FIXED_SALARY_DAYS and (policy_row.salary_days_convention if policy_row else None) != "CALENDAR":
            raise MXBlock("MX_SALARY_DAYS_PARTIAL_PERIOD",
                          f"the employment ends on {ended.termination_date.isoformat()}, inside this {tariff} period, "
                          f"and the labour policy pays fixed salary days — no proration of fixed days is transcribed",
                          employee.organization_id)
        final_period = {"terminationId": ended.id, "periodEnd": end, "endsOn": ended.termination_date}
        end = ended.termination_date
    days_paid = salary_days(tariff, start, end, policy_row.salary_days_convention if policy_row else None)
    counts = _attendance_counts(db, employee.organization_id, employee.id, start, end, attendance_records)
    segs = segments(db, pack, start, end)
    hours, hours_rows = _hours(db, employee.id, start, end)
    zone = mexico_employer_service.min_wage_zone(prof.mx_work_state or "", prof.mx_work_municipality or "")["zone"]

    daily = _dec(prof.mx_daily_salary)
    earnings = [{"code": SALARY_CODE, "kind": "ORDINARY_SALARY", "amount": daily * days_paid}]
    for a in allowance_items or []:
        if _dec(a.get("amount")):
            earnings.append({"code": f"allowance:{a['key']}", "kind": "OTHER", "amount": _dec(a["amount"])})
    extras = service._hk_attendance_extras_by_kind(db, employee.organization_id, employee.id, start, end,
                                                   records=attendance_records)
    for code, amount in sorted(extras.items()):
        earnings.append({"code": code, "kind": "OTHER", "amount": _dec(amount)})

    policy = None if policy_row is None else {
        "id": policy_row.id, "version": policy_row.version, "ordinary_weekly_hours": policy_row.ordinary_weekly_hours,
        "aguinaldo_days": policy_row.aguinaldo_days, "vacation_policy": policy_row.vacation_policy,
        "vacation_premium_pct": policy_row.vacation_premium_pct, "sunday_premium_pct": policy_row.sunday_premium_pct,
        "salary_days_convention": policy_row.salary_days_convention}
    # Phase 9b: the vacation premium of approved vacation records (special pay, engine special_pay).
    from app.modules.payroll import mexico_benefits_service as benefits

    earnings += benefits.premium_lines(db, run, employee.id, end, daily, policy)
    registration = None if reg is None else {"id": reg.id, "status": reg.status,
                                             "employer_profile_id": reg.employer_profile_id}
    risk = None if premium is None else {"id": premium.id, "registration_id": premium.registration_id,
                                         "status": premium.status, "premium_rate_pct": premium.premium_rate_pct,
                                         "period_from": premium.period_from, "period_to": premium.period_to}
    classifications = _classifications(db, employee.organization_id, on)
    notices = _notices(db, employee.id, start, end)
    isn_pack = _isn_state_pack(db, prof.mx_work_state, on)
    accumulator = _accumulator(db, employee.id, prof.mx_salary_type, end)
    mtd = _month_to_date(db, employee.id, run, on)
    profile_facts = {c: getattr(prof, c) for c in (
        "id", "effective_from", "mx_identifier_validation_status", "mx_daily_salary", "mx_salary_type",
        "mx_work_state", "mx_work_municipality", "mx_seniority_date", "mx_pay_frequency_code",
        "mx_professional_min_code", "mx_imss_registration_id", "mx_establishment_id")}

    components = {
        "content": _hash({"pack": [pack.pack_id, pack.version], "pay": [pay_rates, pay_slabs],
                          "segments": [[s["start"], s["rate_map"], s["slabs"]] for s in segs]}),
        "isnPack": _hash(isn_pack), "classifications": _hash(classifications), "registration": _hash(registration),
        "riskPremium": _hash(risk), "laborPolicy": _hash(policy), "profile": _hash(profile_facts),
        "infonavitNotices": _hash(notices), "approvedHours": _hash(hours_rows),
        "variableAccumulator": _hash(accumulator), "monthToDate": _hash(mtd), "earnings": _hash(earnings),
        "attendance": _hash(counts), "bankInstruction": _hash(_bank(employee)),
    }
    if final_period is not None:
        components["termination"] = _hash(final_period)
    return {
        "mx_payroll_date": on, "mx_payment_period": tariff, "mx_profile": prof,
        "mx_registration": registration, "mx_risk_premium": risk, "mx_labor_policy": policy,
        "mx_classifications": classifications, "mx_infonavit_notices": notices, "mx_isn_state_pack": isn_pack,
        "mx_earnings": earnings, "mx_hours": hours, "mx_min_wage_zone": zone,
        "mx_period": {"start": start, "end": end, "days_paid": days_paid, **counts,
                      **({"final_period": _plain(final_period)} if final_period is not None else {}),
                      "segments": [{"start": s["start"], "end": s["end"], "days": s["days"], "rate_map": s["rate_map"],
                                    "slabs": s["slabs"]} for s in segs]},
        "mx_variable_accumulator": {"total": accumulator["total"], "days": accumulator["days"]},
        "mx_month_to_date": mtd,
        "mx_pack": {"pack_id": pack.pack_id, "version": pack.version, "id": pack.id},
        "mx_pack_rows": {"rate_map": pay_rates, "slabs": pay_slabs},
        "mx_employee_id": employee.id, "mx_organization_id": employee.organization_id,
        "mx_input_components": components, "mx_run_type": run_type,
    }


def _aguinaldo_inputs(db: Session, run, employee, pack, pay_rates, pay_slabs) -> dict:
    """Phase 9b: the inputs of one AGUINALDO payslip — days from the labour
    policy (never below the statutory floor), × daily salary × the transcribed
    proportion for the part of the year employed (S26). No ordinary period,
    hours, accumulator or month-to-date: the engine's special-run path."""
    from app.modules.payroll import mexico_employer_service
    from app.modules.payroll.engine.jurisdictions.mexico import rounding, special_pay
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content

    on = run.pay_date
    prof = _profile(db, employee, on)
    reg = _registration(db, prof, on)
    policy_row = _labor_policy(db, reg, on)
    if policy_row is None:
        raise MXBlock("MX_LABOR_POLICY_MISSING", "no employer labour policy is in force on the pay date",
                      employee.organization_id)
    if policy_row.floor_check_status != "PASS":
        raise MXBlock("MX_LABOR_POLICY_FLOOR_NOT_PASS", "the employer labour policy has not passed its floor check")
    content = Content(pay_rates, pay_slabs)
    statutory_days = content.amount("mx_aguinaldo_min_days")
    days = _dec(policy_row.aguinaldo_days)
    if days < statutory_days:
        raise MXBlock("MX_LABOR_POLICY_BELOW_FLOOR", "the labour policy's aguinaldo days are below the statutory minimum")
    daily = _dec(prof.mx_daily_salary)
    year = run.period_start.year
    detail = special_pay.aguinaldo_amount(days, daily, year, employee.date_of_joining, employee.date_of_leaving)
    amount = rounding.rounder(content)(detail["amount"])
    earnings = [{"code": "MX_AGUINALDO", "kind": "AGUINALDO", "amount": amount}]
    zone = mexico_employer_service.min_wage_zone(prof.mx_work_state or "", prof.mx_work_municipality or "")["zone"]
    isn_pack = _isn_state_pack(db, prof.mx_work_state, on)
    policy = {"id": policy_row.id, "version": policy_row.version, "aguinaldo_days": policy_row.aguinaldo_days,
              "vacation_policy": policy_row.vacation_policy, "vacation_premium_pct": policy_row.vacation_premium_pct}
    registration = None if reg is None else {"id": reg.id, "status": reg.status,
                                             "employer_profile_id": reg.employer_profile_id}
    employment = {"from": employee.date_of_joining, "to": employee.date_of_leaving, "year": year}
    profile_facts = {c: getattr(prof, c) for c in ("id", "effective_from", "mx_daily_salary", "mx_work_state",
                                                    "mx_seniority_date", "mx_imss_registration_id")}
    components = {
        "content": _hash({"pack": [pack.pack_id, pack.version], "pay": [pay_rates, pay_slabs]}),
        "isnPack": _hash(isn_pack), "registration": _hash(registration), "laborPolicy": _hash(policy),
        "profile": _hash(profile_facts), "employment": _hash(employment), "earnings": _hash(earnings),
    }
    special_detail = {"concept": "AGUINALDO", "year": year, "days": days, "statutoryMinDays": statutory_days,
                      "dailySalary": daily, "fraction": detail["fraction"], "unrounded": detail["amount"],
                      "payableBy": detail["payable_by"], "employedFrom": employee.date_of_joining,
                      "employedTo": employee.date_of_leaving, "ruleSource": detail["rule_source"]}
    return {
        "mx_payroll_date": on, "mx_payment_period": None, "mx_profile": prof, "mx_registration": registration,
        "mx_risk_premium": None, "mx_labor_policy": policy, "mx_classifications": {}, "mx_infonavit_notices": [],
        "mx_isn_state_pack": isn_pack, "mx_earnings": earnings, "mx_hours": None, "mx_min_wage_zone": zone,
        "mx_period": {"start": run.period_start, "end": run.period_end, "days_paid": _ZERO, "segments": []},
        "mx_variable_accumulator": {"total": _ZERO, "days": _ZERO},
        "mx_month_to_date": {"taxable": _ZERO, "subsidy_applied": _ZERO},
        "mx_pack": {"pack_id": pack.pack_id, "version": pack.version, "id": pack.id},
        "mx_pack_rows": {"rate_map": pay_rates, "slabs": pay_slabs},
        "mx_employee_id": employee.id, "mx_organization_id": employee.organization_id,
        "mx_input_components": components, "mx_run_type": "AGUINALDO", "mx_special_detail": _plain(special_detail),
    }


def _finiquito_inputs(db: Session, run, employee, pack, pay_rates, pay_slabs) -> dict:
    """Phase 9c: the inputs of one FINIQUITO payslip — proportional aguinaldo,
    the vacation still owed paid out with its premium, and the separation
    components the termination's reason triggers (all from transcribed rules,
    mexico_termination_service.finiquito_lines). Profile, registration and
    labour policy are those in force on the last day employed; the content is
    the pay date's (MX-004). No ordinary period: the engine's special-run path."""
    from app.modules.payroll import mexico_employer_service, mexico_termination_service
    from app.modules.payroll.engine.jurisdictions.mexico import rounding
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content

    on = run.pay_date
    row = mexico_termination_service.for_run(db, run)
    if row.employee_id != employee.id:
        raise MXBlock("MX_FINIQUITO_TERMINATION_MISSING", f"run {run.id} settles another employee's termination",
                      employee.organization_id)
    last_day = row.termination_date
    prof = _profile(db, employee, last_day)
    reg = _registration(db, prof, last_day)
    policy_row = _labor_policy(db, reg, last_day)
    if policy_row is None:
        raise MXBlock("MX_LABOR_POLICY_MISSING", "no employer labour policy was in force on the termination date",
                      employee.organization_id)
    if policy_row.floor_check_status != "PASS":
        raise MXBlock("MX_LABOR_POLICY_FLOOR_NOT_PASS", "the employer labour policy has not passed its floor check")
    content = Content(pay_rates, pay_slabs)
    rounder = rounding.rounder(content)
    zone = mexico_employer_service.min_wage_zone(prof.mx_work_state or "", prof.mx_work_municipality or "")["zone"]
    policy = {"id": policy_row.id, "version": policy_row.version, "aguinaldo_days": policy_row.aguinaldo_days,
              "vacation_policy": policy_row.vacation_policy, "vacation_premium_pct": policy_row.vacation_premium_pct}
    facts = {"termination_date": last_day, "pay_date": on, "daily_salary": _dec(prof.mx_daily_salary),
             "seniority_date": prof.mx_seniority_date, "date_of_joining": employee.date_of_joining,
             "work_state": prof.mx_work_state, "zone": zone, "content": content}
    earnings, detail = mexico_termination_service.finiquito_lines(db, row, employee, prof, policy, content, rounder,
                                                                  facts)
    isn_pack = _isn_state_pack(db, prof.mx_work_state, on)
    registration = None if reg is None else {"id": reg.id, "status": reg.status,
                                             "employer_profile_id": reg.employer_profile_id}
    profile_facts = {c: getattr(prof, c) for c in ("id", "effective_from", "mx_daily_salary", "mx_work_state",
                                                    "mx_seniority_date", "mx_imss_registration_id")}
    termination = {"id": row.id, "date": last_day, "reason": row.reason_code, "status": row.status}
    components = {
        "content": _hash({"pack": [pack.pack_id, pack.version], "pay": [pay_rates, pay_slabs]}),
        "isnPack": _hash(isn_pack), "registration": _hash(registration), "laborPolicy": _hash(policy),
        "profile": _hash(profile_facts), "termination": _hash(termination),
        "vacationRecords": _hash(_vacation_facts(db, employee.id)), "earnings": _hash(earnings),
    }
    return {
        "mx_payroll_date": on, "mx_payment_period": None, "mx_profile": prof, "mx_registration": registration,
        "mx_risk_premium": None, "mx_labor_policy": policy, "mx_classifications": {}, "mx_infonavit_notices": [],
        "mx_isn_state_pack": isn_pack, "mx_earnings": earnings, "mx_hours": None, "mx_min_wage_zone": zone,
        "mx_period": {"start": run.period_start, "end": run.period_end, "days_paid": _ZERO, "segments": []},
        "mx_variable_accumulator": {"total": _ZERO, "days": _ZERO},
        "mx_month_to_date": {"taxable": _ZERO, "subsidy_applied": _ZERO},
        "mx_pack": {"pack_id": pack.pack_id, "version": pack.version, "id": pack.id},
        "mx_pack_rows": {"rate_map": pay_rates, "slabs": pay_slabs},
        "mx_employee_id": employee.id, "mx_organization_id": employee.organization_id,
        "mx_input_components": components, "mx_run_type": "FINIQUITO", "mx_special_detail": _plain(detail),
    }


def _ptu_inputs(db: Session, run, employee, pack, pay_rates, pay_slabs) -> dict:
    """Phase 9d: the inputs of one PTU payslip — the worker's final amount from
    the APPROVED allocation of the run's cycle. Profile and registration are
    those in force on the pay date, or on the last day employed for a leaver;
    the content is the pay date's (MX-004). No ordinary period: the engine's
    special-run path (withheld by the special-pay rule, never in ordinary pay
    or accumulators — MX-056)."""
    from app.modules.payroll import mexico_employer_service, mexico_ptu_service

    on = run.pay_date
    cycle, alloc = mexico_ptu_service.allocation_for(db, run, employee.id)
    if cycle.status not in ("APPROVED", "DISTRIBUTED"):
        raise MXBlock("MX_PTU_CYCLE_NOT_APPROVED", f"PTU cycle {cycle.id} is {cycle.status}", employee.organization_id)
    as_of = employee.date_of_leaving if employee.date_of_leaving and employee.date_of_leaving < on else on
    prof = _profile(db, employee, as_of)
    reg = _registration(db, prof, as_of)
    policy_row = _labor_policy(db, reg, as_of)
    zone = mexico_employer_service.min_wage_zone(prof.mx_work_state or "", prof.mx_work_municipality or "")["zone"]
    isn_pack = _isn_state_pack(db, prof.mx_work_state, on)
    earnings = [{"code": "MX_PTU", "kind": "PTU", "amount": _dec(alloc.final_amount)}]
    policy = None if policy_row is None else {"id": policy_row.id, "version": policy_row.version}
    registration = None if reg is None else {"id": reg.id, "status": reg.status,
                                             "employer_profile_id": reg.employer_profile_id}
    profile_facts = {c: getattr(prof, c) for c in ("id", "effective_from", "mx_daily_salary", "mx_work_state",
                                                    "mx_seniority_date", "mx_imss_registration_id")}
    allocation = {"cycle": cycle.id, "fingerprint": cycle.allocation_fingerprint, "final": alloc.final_amount,
                  "days": alloc.qualifying_days, "salary": alloc.qualifying_salary}
    components = {
        "content": _hash({"pack": [pack.pack_id, pack.version], "pay": [pay_rates, pay_slabs]}),
        "isnPack": _hash(isn_pack), "registration": _hash(registration), "laborPolicy": _hash(policy),
        "profile": _hash(profile_facts), "ptuAllocation": _hash(allocation), "earnings": _hash(earnings),
    }
    special_detail = {"concept": "PTU", "cycleId": cycle.id, "fiscalYear": cycle.fiscal_year,
                      "qualifyingDays": alloc.qualifying_days, "qualifyingSalary": alloc.qualifying_salary,
                      "daysShare": alloc.days_share, "salaryShare": alloc.salary_share,
                      "capReference": alloc.cap_reference, "capApplied": alloc.cap_applied,
                      "finalAmount": alloc.final_amount, "allocationRule": cycle.rule_source,
                      "paymentDeadline": cycle.payment_deadline, "deadlineRule": cycle.deadline_rule_ref}
    return {
        "mx_payroll_date": on, "mx_payment_period": None, "mx_profile": prof, "mx_registration": registration,
        "mx_risk_premium": None, "mx_labor_policy": policy, "mx_classifications": {}, "mx_infonavit_notices": [],
        "mx_isn_state_pack": isn_pack, "mx_earnings": earnings, "mx_hours": None, "mx_min_wage_zone": zone,
        "mx_period": {"start": run.period_start, "end": run.period_end, "days_paid": _ZERO, "segments": []},
        "mx_variable_accumulator": {"total": _ZERO, "days": _ZERO},
        "mx_month_to_date": {"taxable": _ZERO, "subsidy_applied": _ZERO},
        "mx_pack": {"pack_id": pack.pack_id, "version": pack.version, "id": pack.id},
        "mx_pack_rows": {"rate_map": pay_rates, "slabs": pay_slabs},
        "mx_employee_id": employee.id, "mx_organization_id": employee.organization_id,
        "mx_input_components": components, "mx_run_type": "PTU", "mx_special_detail": _plain(special_detail),
    }


def _vacation_facts(db: Session, employee_id: int) -> list:
    """The vacation records a finiquito reads (approval drift: a change after
    the calculation is seen as stale)."""
    from app.modules.payroll.models import PayrollMxVacationRecord as V

    return [{"id": r.id, "year": r.service_year, "kind": r.kind, "days": r.days, "status": r.status}
            for r in db.query(V).filter(V.employee_id == employee_id).order_by(V.id)]


def payslip_split(inputs: dict) -> dict:
    """The shared payslip columns for a Mexican payslip (D2): basic = salary
    line, overtime = hour-derived lines, additional = other lines; gross is
    their sum — the engine refuses any other gross (MX_GROSS_MISMATCH)."""
    from app.modules.payroll.engine.jurisdictions.mexico import labor
    from app.modules.payroll.engine.jurisdictions.mexico.content import Content

    lines = inputs["mx_earnings"]
    basic = sum((l["amount"] for l in lines if l["kind"] == "ORDINARY_SALARY"), _ZERO)
    allowances = sum((l["amount"] for l in lines if str(l["code"]).startswith("allowance:")), _ZERO)
    extras = sum((l["amount"] for l in lines
                  if l["kind"] != "ORDINARY_SALARY" and not str(l["code"]).startswith("allowance:")), _ZERO)
    hour = _ZERO
    if inputs.get("mx_hours"):
        rows = inputs["mx_pack_rows"]
        out = labor.hour_lines(Content(rows["rate_map"], rows["slabs"]), inputs["mx_hours"], inputs["mx_labor_policy"],
                               _dec(getattr(inputs["mx_profile"], "mx_daily_salary", 0)))
        hour = sum((l["amount"] for l in out["lines"]), _ZERO)
    # The shared payslip keeps named allowances in their own rows
    # (PayslipAllowanceItem); "extras" are the attendance extras.
    return {"basic": basic, "allowances": allowances, "extras": extras, "overtime": hour,
            "gross": basic + allowances + extras + hour}


def check_manual_amounts(data, split: dict) -> None:
    """add_payslip_item for a Mexican employee: the amounts are the computed
    Mexican lines (no allowance rows on this path); any manual figure that
    disagrees is refused, never silently replaced."""
    expected = {"basicSalary": split["basic"], "hra": _ZERO, "specialAllowance": _ZERO,
                "overtime": split["overtime"]}
    given = {"basicSalary": _dec(getattr(data, "basic_salary", 0)), "hra": _dec(getattr(data, "hra", 0)),
             "specialAllowance": _dec(getattr(data, "special_allowance", 0)),
             "overtime": _dec(getattr(data, "overtime", 0))}
    wrong = [f"{k} {given[k]} (Mexico computes {expected[k]})" for k in expected if given[k] != expected[k]]
    if split["allowances"] or split["extras"]:
        wrong.append("attendance extras / allowances exist for the period — use run generation")
    if wrong:
        raise BadRequestException("Mexican payslip amounts are computed from the profile, labour policy and "
                                  "approved hours: " + "; ".join(wrong))


def input_hash(components: dict) -> str:
    return _hash(components)


def payslip_snapshot(mx_result: dict, inputs: dict) -> dict:
    comps = inputs.get("mx_input_components") or {}
    return {"result": mx_result, "inputHash": input_hash(comps), "components": comps,
            "pack": _plain(inputs.get("mx_pack")), "engineVersion": (mx_result or {}).get("engine_version")}


def preview_block(exc, employee) -> MXBlock:
    """A preview refusal naming the employee and every reason (coded 4xx via
    the shared MissingComplianceConfigurationError handler). Generation, by
    contrast, records a FAILED sentinel plus exception rows."""
    name = getattr(employee, "name", None) or f"Employee #{employee.id}"
    reasons = list(getattr(exc, "reasons", None) or [(exc.key, exc.reason)])
    return MXBlock(exc.key, f"preview refused for {name} (#{employee.id}): "
                   + "; ".join(f"{k}: {m}" for k, m in reasons),
                   getattr(employee, "organization_id", None), reasons=reasons)


def blocked_snapshot(exc) -> dict:
    return {"blocked": True, "code": exc.key, "reason": exc.reason,
            "reasons": [{"code": k, "message": m} for k, m in getattr(exc, "reasons", [(exc.key, exc.reason)])]}


# ── 5. Generation hooks (preflight exceptions) ───────────────────────────────

def clear_exceptions(db: Session, run_id: int, employee_id: int) -> None:
    from app.modules.payroll.models import PayrollMxPreflightException as E

    db.query(E).filter(E.payroll_run_id == run_id, E.employee_id == employee_id).delete(synchronize_session=False)


def record_block(db: Session, run, employee, item, exc) -> None:
    from app.modules.payroll.models import PayrollMxPreflightException as E

    clear_exceptions(db, run.id, employee.id)
    for code, message in getattr(exc, "reasons", None) or [(exc.key, exc.reason)]:
        db.add(E(payroll_run_id=run.id, payslip_item_id=getattr(item, "id", None), employee_id=employee.id,
                 code=code, severity="BLOCK", message=message))


def _exception_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "payslipItemId": row.payslip_item_id, "code": row.code,
            "severity": row.severity, "message": row.message, "acknowledgedById": row.acknowledged_by_id,
            "acknowledgementNote": row.acknowledgement_note,
            "acknowledgedAt": row.acknowledged_at.isoformat() if row.acknowledged_at else None}


def _mx_items(db: Session, run) -> list:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                         PayslipItem.country_code == MX).order_by(PayslipItem.id).all())


def run_preflight(db: Session, run) -> dict:
    from app.modules.payroll.models import PayrollMxPreflightException as E

    rows = db.query(E).filter(E.payroll_run_id == run.id).order_by(E.employee_id, E.id).all()
    items = _mx_items(db, run)
    return {"runId": run.id, "exceptions": [_exception_view(r) for r in rows],
            "blocking": sum(1 for r in rows if r.severity == "BLOCK"),
            "unacknowledgedWarnings": sum(1 for r in rows if r.severity == "WARN" and not r.acknowledged_at),
            "items": len(items), "failedItems": sum(1 for i in items if (i.status or "").lower() == "failed")}


def acknowledge_exception(db: Session, run, exception_id: int, note: str, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxPreflightException as E

    row = db.get(E, exception_id)
    if row is None or row.payroll_run_id != run.id:
        raise NotFoundException("Mexico preflight exception", exception_id)
    if row.severity == "BLOCK":
        raise BadRequestException("A BLOCK exception cannot be acknowledged — fix its cause and regenerate (D8)")
    if not (note or "").strip():
        raise BadRequestException("An acknowledgement note is required")
    row.acknowledged_by_id, row.acknowledgement_note, row.acknowledged_at = actor_id, note.strip()[:500], datetime.utcnow()
    _audit(db, actor_id=actor_id, action="acknowledge", entity_type="mx_preflight_exception", entity_id=row.id,
           new={"code": row.code, "note": row.acknowledgement_note})
    db.commit()
    return _exception_view(row)


# ── 6. Approval fingerprint + commit (MX-040, MX-039) ────────────────────────

def _current_components(db: Session, run, item) -> dict:
    from app.modules.payroll.models import PayrollEmployee, PayslipAllowanceItem

    emp = db.get(PayrollEmployee, item.employee_id)
    allowances = [{"key": a.key, "amount": a.amount}
                  for a in db.query(PayslipAllowanceItem).filter(PayslipAllowanceItem.payslip_item_id == item.id).all()]
    return calc_inputs(db, run, emp, None, allowance_items=allowances)["mx_input_components"]


def compute_fingerprint(db: Session, run) -> dict:
    items = []
    for item in _mx_items(db, run):
        snap = item.mx_calculation_snapshot or {}
        if snap.get("blocked") or not snap.get("inputHash"):
            raise BadRequestException(f"payslip {item.id} has no Mexican calculation — fix its exceptions and "
                                      "regenerate before approval")
        items.append({"payslipItemId": item.id, "employeeId": item.employee_id, "inputHash": snap["inputHash"],
                      "components": snap.get("components") or {},
                      "totals": {"net": str(item.net_pay or 0), "gross": str(item.gross_pay or 0)}})
    return {"fingerprint": _hash([[i["payslipItemId"], i["inputHash"], i["totals"]] for i in items]), "items": items}


def approval_drift(db: Session, run) -> list:
    """[{payslipItemId, employeeId, changed:[component…]}] — empty when every
    bound input still matches (re-verified from the database, not the snapshot)."""
    stored = run.mx_approval_fingerprint or {}
    out = []
    for entry in stored.get("items") or []:
        from app.modules.payroll.models import PayslipItem

        item = db.get(PayslipItem, entry["payslipItemId"])
        if item is None:
            out.append({"payslipItemId": entry["payslipItemId"], "employeeId": entry["employeeId"], "changed": ["payslip"]})
            continue
        try:
            current = _current_components(db, run, item)
        except MXBlock as exc:
            out.append({"payslipItemId": item.id, "employeeId": item.employee_id, "changed": [f"blocked:{exc.key}"]})
            continue
        changed = sorted(k for k in set(current) | set(entry["components"]) if current.get(k) != entry["components"].get(k))
        if changed:
            out.append({"payslipItemId": item.id, "employeeId": item.employee_id, "changed": changed})
    return out


def commit_run(db: Session, run, actor_id: Optional[int]) -> dict:
    """Every ledger row of the run, in the caller's transaction (the APPROVED
    transition). Idempotent: a committed run is a no-op."""
    from app.modules.payroll.models import (
        PayrollMxBenefitAccrual, PayrollMxImssBranchLine, PayrollMxIsnLiability, PayrollMxSbcHistory,
        PayrollMxVariableAccumulator,
    )

    if (run.mx_approval_fingerprint or {}).get("committedAt"):
        return {"committed": False, "reason": "already committed"}
    counts = {"imss": 0, "isn": 0, "sbc": 0, "accumulators": 0, "accruals": 0}
    period_key = run.pay_date.strftime("%Y-%m")
    # Phase 9a: a CORRECTION run posts DELTAS (corrected − original) to the
    # aggregate ledgers (ISN, accumulators, accruals) and the full corrected
    # rows to the per-payslip traces (IMSS lines, SBC history).
    from app.modules.payroll import mexico_correction_service as corrections

    is_correction = (run.mx_run_type or "ORDINARY") == "CORRECTION"
    for item in _mx_items(db, run):
        res = (item.mx_calculation_snapshot or {}).get("result") or {}
        base = corrections.result_of(corrections.original_item_for(db, item)) if is_correction else {}
        for branch in res.get("imss") or []:
            for line in branch.get("lines") or []:
                db.add(PayrollMxImssBranchLine(
                    payslip_item_id=item.id, organization_id=run.organization_id, branch_code=line["branch"],
                    side=line["side"], segment_start=date.fromisoformat(line["segment"]),
                    base_amount=_dec(line["base"]), contribution_days=_dec(line["days"]),
                    rate_pct=_dec(line["rate_pct"]), amount=_dec(line["amount"]), band=line.get("band")))
                counts["imss"] += 1
        isn_now = {(res.get("isn") or {}).get("state"): res.get("isn") or {}}
        isn_was = {(base.get("isn") or {}).get("state"): base.get("isn") or {}}
        for state in sorted(s for s in set(isn_now) | set(isn_was) if s):
            now, was = isn_now.get(state, {}), isn_was.get(state, {})
            d_base, d_amount = _dec(now.get("base")) - _dec(was.get("base")), _dec(now.get("amount")) - _dec(was.get("amount"))
            if is_correction and d_base == 0 and d_amount == 0:
                continue
            db.add(PayrollMxIsnLiability(
                payslip_item_id=item.id, organization_id=run.organization_id, state_code=state, base_amount=d_base,
                rate_pct=_dec(now.get("rate_pct") or was.get("rate_pct")), amount=d_amount,
                jurisdiction_pack_id=now.get("pack_id") or was.get("pack_id"), period_key=period_key))
            counts["isn"] += 1
        sbc = res.get("sbc") or {}
        comp = sbc.get("components") or {}
        for seg in sbc.get("segments") or []:
            db.add(PayrollMxSbcHistory(
                organization_id=run.organization_id, employee_id=item.employee_id, payroll_run_id=run.id,
                effective_from=date.fromisoformat(seg["start"]), sbc_fixed=_dec(comp.get("fixed")),
                sbc_variable=_dec(comp.get("variable_daily")), sbc_total=_dec(seg.get("sbc")),
                factor=_dec(comp.get("factor")), components=comp, source="CORRECTION" if is_correction else "RUN"))
            counts["sbc"] += 1

        def _variable(r):
            return sum((_dec(c["gross"]) for c in r.get("concepts") or [] if c.get("sbc") == "VARIABLE"), _ZERO)

        db.add(PayrollMxVariableAccumulator(
            organization_id=run.organization_id, employee_id=item.employee_id, payroll_run_id=run.id,
            bimester_key=bimester_key(run.period_end), variable_total=_variable(res) - _variable(base),
            days=_dec(res.get("contribution_days")) - _dec(base.get("contribution_days")), kind="RUN",
            recorded_by_id=actor_id))
        counts["accumulators"] += 1
        concepts = {"aguinaldo days": "AGUINALDO", "vacation days": "VACATION", "vacation premium %": "VACATION_PREMIUM"}
        was_ent = {concepts.get(e.get("concept")): e for e in base.get("entitlements") or []}
        for ent in res.get("entitlements") or []:
            concept = concepts.get(ent.get("concept"))
            if concept:
                prev = was_ent.get(concept, {})
                db.add(PayrollMxBenefitAccrual(
                    organization_id=run.organization_id, employee_id=item.employee_id, payroll_run_id=run.id,
                    concept=concept, period_key=period_key,
                    statutory_amount=_dec(ent.get("statutory_amount")) - _dec(prev.get("statutory_amount")),
                    employer_amount=_dec(ent.get("employer_amount")) - _dec(prev.get("employer_amount"))))
                counts["accruals"] += 1
    if is_correction:
        corrections.on_commit(db, run)
    from app.modules.payroll import mexico_benefits_service

    counts["vacationPremiumsPaid"] = mexico_benefits_service.on_commit(db, run)
    from app.modules.payroll import mexico_termination_service

    counts["vacationPaidOut"] = mexico_termination_service.on_commit(db, run)
    from app.modules.payroll import mexico_ptu_service

    counts["ptuAllocationsPaid"] = mexico_ptu_service.on_commit(db, run)
    db.flush()
    return {"committed": True, **counts}


def _ledger_queries(db: Session, run):
    from app.modules.payroll.models import (
        PayrollMxBenefitAccrual, PayrollMxImssBranchLine, PayrollMxIsnLiability, PayrollMxSbcHistory,
        PayrollMxVariableAccumulator,
    )

    ids = [i.id for i in _mx_items(db, run)] or [-1]
    return (db.query(PayrollMxImssBranchLine).filter(PayrollMxImssBranchLine.payslip_item_id.in_(ids)),
            db.query(PayrollMxIsnLiability).filter(PayrollMxIsnLiability.payslip_item_id.in_(ids)),
            db.query(PayrollMxSbcHistory).filter(PayrollMxSbcHistory.payroll_run_id == run.id),
            db.query(PayrollMxVariableAccumulator).filter(PayrollMxVariableAccumulator.payroll_run_id == run.id),
            db.query(PayrollMxBenefitAccrual).filter(PayrollMxBenefitAccrual.payroll_run_id == run.id))


def ledger_counts(db: Session, run) -> dict:
    names = ("imssBranchLines", "isnLiabilities", "sbcHistory", "variableAccumulators", "benefitAccruals")
    return {n: q.count() for n, q in zip(names, _ledger_queries(db, run))}


def before_run_transition(db: Session, run, next_status, approver_id) -> None:
    """Reached only for a run with Mexican payslips. APPROVED: no BLOCK / no
    unacknowledged WARN / no FAILED item, every payslip current, then the
    fingerprint is stored and the ledgers committed in this transaction.
    AUTHORIZED / PAID stay refused (CFDI Phase 7, bank Phase 10; MX-041)."""
    from app.modules.payroll.models import PayrollStatus

    value = getattr(next_status, "value", next_status)
    if value in (PayrollStatus.AUTHORIZED.value, PayrollStatus.PAID.value, PayrollStatus.CLOSED.value):
        raise MXBlock("MX_RUN_NOT_SUPPORTED",
                      f"a run with Mexican payslips cannot be {value} until CFDI stamping (Phase 7) and bank "
                      "settlement (Phase 10) exist", run.organization_id)
    if value != PayrollStatus.APPROVED.value:
        return
    pre = run_preflight(db, run)
    if pre["blocking"] or pre["failedItems"]:
        raise MXBlock("MX_PREFLIGHT_BLOCKED",
                      f"{pre['blocking']} blocking exception(s) / {pre['failedItems']} failed payslip(s) — fix and "
                      "regenerate before approval", run.organization_id)
    if pre["unacknowledgedWarnings"]:
        raise MXBlock("MX_WARNINGS_UNACKNOWLEDGED",
                      f"{pre['unacknowledgedWarnings']} warning(s) need an acknowledgement note", run.organization_id)
    fp = compute_fingerprint(db, run)
    stale = []
    for entry in fp["items"]:
        from app.modules.payroll.models import PayslipItem

        current = _current_components(db, run, db.get(PayslipItem, entry["payslipItemId"]))
        if input_hash(current) != entry["inputHash"]:
            stale.append(str(entry["employeeId"]))
    if stale:
        raise MXBlock("MX_PAYSLIP_STALE", f"inputs changed since generation for employee(s) {', '.join(stale)} — "
                      "regenerate before approval", run.organization_id)
    result = commit_run(db, run, approver_id)          # before committedAt is stamped (its idempotency key)
    now = datetime.utcnow().isoformat()
    run.mx_approval_fingerprint = {**fp, "approvedBy": approver_id, "approvedAt": now, "committedAt": now,
                                   "spec": SPEC}
    _audit(db, actor_id=approver_id, action="approve", entity_type="mx_run_approval", entity_id=run.id,
           new={"fingerprint": fp["fingerprint"], "ledgers": result})


# ── 7. Reset (plan §4) ───────────────────────────────────────────────────────

def run_downstream_actions(db: Session, run) -> list:
    """Reasons a downstream lifecycle has acted on the run, which refuse a
    reset. Phase 7: every CFDI of the run that was transmitted or stamped
    (SUBMITTED onward, Phase 7 D2). Phase 8: any IMSS movement exported /
    filed / UNKNOWN, any liability past ACCRUED (or ever sent), any SUA
    period RECONCILED onward and any ISN return past DRAFT that includes it
    (Phase 8 plan §6). Phase 9a: any live correction of one of its payslips.
    Phase 10 MUST add: any RELEASED bank instruction for it. Each with a test."""
    from app.modules.payroll import mexico_cfdi_service, mexico_correction_service, mexico_filing_service

    return (mexico_cfdi_service.downstream_reasons(db, run) + mexico_filing_service.downstream_reasons(db, run)
            + mexico_correction_service.downstream_reasons(db, run))


def reset_run(db: Session, run, actor_id: Optional[int], reason: str) -> dict:
    from app.modules.payroll.models import PayrollStatus

    if not (reason or "").strip():
        raise BadRequestException("A reset reason is required")
    if run.status != PayrollStatus.APPROVED.value or not (run.mx_approval_fingerprint or {}).get("committedAt"):
        raise BadRequestException("Only an Approved (committed) Mexico run can be reset")
    acted = run_downstream_actions(db, run)
    if acted:
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="MX_RESET_DOWNSTREAM_ACTED: " + "; ".join(acted))
    from app.modules.payroll import mexico_cfdi_service, mexico_filing_service

    voided = mexico_cfdi_service.void_untransmitted(db, run, actor_id)   # never transmitted → VOIDED (D3)
    removed = {"cfdiVoided": voided, **mexico_filing_service.withdraw_on_reset(db, run, actor_id)}
    from app.modules.payroll import mexico_correction_service

    removed["correctionsReopened"] = mexico_correction_service.on_reset(db, run)
    from app.modules.payroll import mexico_benefits_service

    removed["vacationPremiumsReopened"] = mexico_benefits_service.on_reset(db, run)
    from app.modules.payroll import mexico_termination_service

    removed["vacationPaidOutRemoved"] = mexico_termination_service.on_reset(db, run)
    from app.modules.payroll import mexico_ptu_service

    removed["ptuAllocationsReopened"] = mexico_ptu_service.on_reset(db, run)
    names = ("imssBranchLines", "isnLiabilities", "sbcHistory", "variableAccumulators", "benefitAccruals")
    for name, q in zip(names, _ledger_queries(db, run)):
        removed[name] = q.delete(synchronize_session=False)
    old = run.mx_approval_fingerprint
    run.mx_approval_fingerprint = None
    run.status = PayrollStatus.REVIEW.value
    run.approved_by = None
    run.approved_at = None
    _audit(db, actor_id=actor_id, action="reset", entity_type="mx_run_approval", entity_id=run.id,
           old={"fingerprint": (old or {}).get("fingerprint")}, new={"removed": removed}, reason=reason.strip())
    db.commit()
    return {"runId": run.id, "status": run.status, "removed": removed}


def refuse_if_committed(run) -> None:
    """Shared deletion paths: a committed Mexico run's items / run are never
    deleted (its ledger rows would otherwise be orphaned; FK RESTRICT backs this)."""
    if run is not None and (getattr(run, "mx_approval_fingerprint", None) or {}).get("committedAt"):
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="This Mexico run is committed — reset it first (no downstream lifecycle may "
                                   "have acted on it).")


# ── 8. Payment hold (D11) and run status view (MX-041) ──────────────────────

def payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    return {i.id: "MX_BANK_SETTLEMENT_PHASE10" for i in items if (i.country_code or "").upper() == MX}


def _cfdi_lane(db: Session, run) -> dict:
    from app.modules.payroll import mexico_cfdi_service

    out = mexico_cfdi_service.run_summary(db, run)
    if out["status"] == "NOT_STARTED":
        out["detail"] = ("no CFDI generated — the builder needs S28 / S30 / S4, signing needs Secret Manager and no "
                         "PAC is chosen (Phase 7 X1–X4)")
    return out


def _authorities_lane(db: Session, run) -> dict:
    from app.modules.payroll import mexico_filing_service

    return mexico_filing_service.run_lane(db, run)


def run_status(db: Session, run) -> dict:
    stored = run.mx_approval_fingerprint or {}
    drift = approval_drift(db, run) if stored.get("committedAt") else []
    return {"runId": run.id, "runType": run.mx_run_type or "ORDINARY",
            "payroll": {"status": run.status, "committedAt": stored.get("committedAt"),
                        "approvalInvalidated": bool(drift), "drift": drift},
            "cfdi": _cfdi_lane(db, run),
            "authorities": _authorities_lane(db, run),
            "bank": {"status": "HELD", "detail": "bank settlement is built in Phase 10; every Mexican payment is held"},
            "ledgers": ledger_counts(db, run)}


# ── 9. Approved hours (D1) and opening balances (D4) — four-eyes ─────────────

def _hours_view(r) -> dict:
    return {"id": r.id, "employeeId": r.employee_id, "weekStart": r.week_start.isoformat(),
            "ordinaryHours": str(r.ordinary_hours), "overtimeHours": str(r.overtime_hours),
            "sundaysWorked": r.sundays_worked, "restDaysWorked": r.rest_days_worked,
            "evidenceDocumentId": r.evidence_document_id, "status": r.status, "recordedById": r.recorded_by_id,
            "approvedById": r.approved_by_id, "approvedAt": r.approved_at.isoformat() if r.approved_at else None}


def record_hours(db: Session, org_id: int, employee_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll import mexico_employee_service
    from app.modules.payroll.models import PayrollMxApprovedHours as H

    mexico_employee_service._mx_employee(db, org_id, employee_id)
    week = data.get("week_start")
    if not isinstance(week, date):
        raise BadRequestException("weekStart is required")
    if not data.get("evidence_document_id"):
        raise BadRequestException("Approved hours need an evidence document (time record)")
    vals = {}
    for key in ("ordinary_hours", "overtime_hours", "sundays_worked", "rest_days_worked"):
        v = _dec(data.get(key))
        if v < 0:
            raise BadRequestException(f"{key} must be zero or more")
        vals[key] = v
    row = H(organization_id=org_id, employee_id=employee_id, week_start=week, ordinary_hours=vals["ordinary_hours"],
            overtime_hours=vals["overtime_hours"], sundays_worked=int(vals["sundays_worked"]),
            rest_days_worked=int(vals["rest_days_worked"]), evidence_document_id=data["evidence_document_id"],
            status="DRAFT", recorded_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_approved_hours", entity_id=row.id,
           new=_hours_view(row))
    db.commit()
    return _hours_view(row)


def approve_hours(db: Session, org_id: int, hours_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxApprovedHours as H

    row = db.get(H, hours_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException("Mexico approved hours", hours_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only DRAFT hours can be approved")
    if actor_id is not None and actor_id == row.recorded_by_id:
        raise ForbiddenException("Hours must be approved by someone other than the person who recorded them")
    for old in db.query(H).filter(H.employee_id == row.employee_id, H.week_start == row.week_start,
                                  H.status == "APPROVED").all():
        old.status = "SUPERSEDED"
    db.flush()
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    _audit(db, actor_id=actor_id, action="approve", entity_type="mx_approved_hours", entity_id=row.id,
           new={"status": "APPROVED"})
    db.commit()
    return _hours_view(row)


def list_hours(db: Session, org_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import PayrollMxApprovedHours as H

    return [_hours_view(r) for r in db.query(H).filter(H.organization_id == org_id, H.employee_id == employee_id)
            .order_by(H.week_start.desc(), H.id.desc()).all()]


def _opening_view(r) -> dict:
    return {"id": r.id, "employeeId": r.employee_id, "bimester": r.bimester_key, "variableTotal": str(r.variable_total),
            "days": str(r.days), "evidenceDocumentId": r.evidence_document_id, "recordedById": r.recorded_by_id,
            "approvedById": r.approved_by_id}


def record_opening_balance(db: Session, org_id: int, employee_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll import mexico_employee_service
    from app.modules.payroll.models import PayrollMxVariableAccumulator as V

    mexico_employee_service._mx_employee(db, org_id, employee_id)
    key = str(data.get("bimester") or "")
    if len(key) != 7 or key[4:6] != "-B" or key[6] not in "123456" or not key[:4].isdigit():
        raise BadRequestException("bimester must look like YYYY-Bn (n = 1–6)")
    if not data.get("evidence_document_id"):
        raise BadRequestException("An opening variable-pay balance needs an evidence document")
    total, days = _dec(data.get("variable_total")), _dec(data.get("days"))
    if total < 0 or days < 0 or (total > 0 and days == 0):
        raise BadRequestException("variableTotal and days must be zero or more, and days > 0 when there is pay")
    if db.query(V).filter(V.employee_id == employee_id, V.bimester_key == key, V.kind == "OPENING").first():
        raise BadRequestException(f"an opening balance for {key} already exists")
    row = V(organization_id=org_id, employee_id=employee_id, payroll_run_id=None, bimester_key=key,
            variable_total=total, days=days, kind="OPENING", evidence_document_id=data["evidence_document_id"],
            recorded_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_opening_balance", entity_id=row.id,
           new=_opening_view(row))
    db.commit()
    return _opening_view(row)


def approve_opening_balance(db: Session, org_id: int, row_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxVariableAccumulator as V

    row = db.get(V, row_id)
    if row is None or row.organization_id != org_id or row.kind != "OPENING":
        raise NotFoundException("Mexico opening balance", row_id)
    if row.approved_by_id is not None:
        raise BadRequestException("Already approved")
    if actor_id is not None and actor_id == row.recorded_by_id:
        raise ForbiddenException("An opening balance must be approved by someone other than its recorder")
    row.approved_by_id = actor_id
    _audit(db, actor_id=actor_id, action="approve", entity_type="mx_opening_balance", entity_id=row.id,
           new={"approvedById": actor_id})
    db.commit()
    return _opening_view(row)
