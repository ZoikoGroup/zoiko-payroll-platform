"""
modules/payroll/japan_service.py
--------------------------------
Japan statutory workflows (ZP-JP-ENG-001) — the ONLY Japan service module, on
the shared platform the same way south_africa_service.py is.

Scope (Phase 1): seeding the canonical JP-PAYROLL-2026 Draft pack from
engine/countries/japan_content.py. The Japan tables, calc inputs and platform
hooks (calc_inputs, run preflight, pack activation refusal, retention,
service-registry transition, …) arrive with Phases 2 and 5 and are registered
in jurisdiction_hooks._MODULES only then — registering a module that lacks a
hook the platform calls would make every Japan code path raise (fail-closed).
"""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

JP = "JP"
SPEC = "ZP-JP-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"


def seed_japan_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                    status: str = "Draft") -> "JurisdictionPack":
    """Write japan_content.py into the JP-PAYROLL-2026 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S17), reused if present;
      * every scalar parameter (ContributionRate) with its real value in the
        slot its kind names (employee/employer pct, flat_amount, text_value)
        and its own legal effective_from / effective_to where it has one;
      * every earning-classification row (TaxSlab rule_type="JP_EARNING_CLASS",
        filing_status = component, tax_regime = obligation,
        assessment_basis = treatment).
    The authority tables the specification does not reproduce
    (content.JP_EMPTY_TABLES) write no rows: they are filled from archived
    artefacts at G1/G3/G4, and until then the engine BLOCKS.

    Draft by default; a pack that has left Draft is never rewritten, and a
    Draft pack's canonical rows are replaced wholesale from the content."""
    from app.modules.payroll.engine.countries import japan_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if status != "Draft":
        raise ValueError("seed_japan_pack only writes Draft content")
    pack_id, window_from, window_to = content.JP_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-JP-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=JP, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "NTA / Japan Pension Service / MHLW / Municipalities"
    pack.source_document_id = sources["S1"]
    # Canonical rows only: org-scoped rows (organization_id IS NOT NULL) are an
    # organisation's overrides and are never deleted by a re-seed.
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    def pending(label, flag, limit):
        return (label + (PENDING_G1_SUFFIX if flag else ""))[:limit]

    order = 0
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to) in content.JP_SCALAR_CONTENT:
        order += 1
        ee_shown = f"{ee}%" if ee is not None else "—"
        er_shown = f"{er}%" if er is not None else "—"
        if ee is not None or er is not None:
            total = " / ".join(s for s in (ee_shown, er_shown) if s != "—")
        elif text is None and flat is None:
            # Empty by design (content.JP_EMPTY_BY_DESIGN): the specification gives
            # no value, so the row exists only to make "not configured" explicit.
            total = "NOT CONFIGURED"
        elif content.JP_PARAMETER_KEYS[key] == "pct_total":
            total = f"{flat}% total"
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=JP,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share=ee_shown[:50], employer_share=er_shown[:50], total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.JP_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=JP,
            rule_type=content.JP_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=pending(label, True, 150), tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    db.flush()
    return pack


# ── shared validation helpers ───────────────────────────────────────────────
def _as_date(value, field: str):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


def _money(value, field: str):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal amount.")

# ======================================================================
# Japan Phase 5: platform hooks, calculation inputs, freeze and lifecycle
# ======================================================================
JP_PROFILE_STATUSES = ("ACTIVE",)
JP_SOCIAL_INSURANCE_EVENTS = ("MATERNITY_EXEMPTION", "CHILDCARE_EXEMPTION")


def _jp_value(employee, *keys):
    fields = getattr(employee, "compliance_fields", None) or {}
    for key in keys:
        if key in fields:
            return fields[key]
        if hasattr(employee, key):
            return getattr(employee, key)
    return None


def _jp_models():
    from app.modules.payroll import models

    return models




def _jp_one_active(db: Session, model, organization_id: int, employee_id: Optional[int],
                   as_of: date, label: str):
    q = (db.query(model)
         .filter(model.organization_id == organization_id,
                 model.status == "ACTIVE",
                 model.effective_from <= as_of,
                 (model.effective_to.is_(None)) | (model.effective_to >= as_of)))
    if employee_id is not None:
        q = q.filter(model.employee_id == employee_id)
    rows = q.order_by(model.effective_from.desc(), model.id.desc()).all()
    if len(rows) > 1:
        raise BadRequestException(
            f"{len(rows)} ACTIVE Japan {label} versions are in force on {as_of}; exactly one is required.")
    return rows[0] if rows else None


def _jp_events_for_month(db: Session, organization_id: int, employee_id: int, as_of: date):
    m = _jp_models()
    start = date(as_of.year, as_of.month, 1)
    if as_of.month == 12:
        end = date(as_of.year + 1, 1, 1)
    else:
        end = date(as_of.year, as_of.month + 1, 1)
    return (db.query(m.PayrollJpSocialInsuranceEvent)
            .filter(m.PayrollJpSocialInsuranceEvent.organization_id == organization_id,
                    m.PayrollJpSocialInsuranceEvent.employee_id == employee_id,
                    m.PayrollJpSocialInsuranceEvent.effective_from < end,
                    (m.PayrollJpSocialInsuranceEvent.effective_to.is_(None))
                    | (m.PayrollJpSocialInsuranceEvent.effective_to >= start))
            .order_by(m.PayrollJpSocialInsuranceEvent.id).all())


def _jp_insurance_year_start(on: date) -> date:
    return date(on.year, 4, 1) if on.month >= 4 else date(on.year - 1, 4, 1)


def _jp_prior_payslips(db: Session, organization_id: int, employee_id: int, as_of: date,
                       *, since: Optional[date] = None, until: Optional[date] = None,
                       current_run_id: Optional[int] = None):
    """Paid or closed JP payslips on or before ``as_of``.

    Draft/review/approved runs are not statutory history: they can still be
    discarded, so counting them would double-charge caps and prior-pay bands.
    Same-day runs are included; the caller excludes the current run by id.
    """
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    q = (db.query(PayslipItem, PayrollRun.pay_date)
         .join(PayrollRun, PayrollRun.id == PayslipItem.payroll_run_id)
         .filter(PayslipItem.organization_id == organization_id,
                 PayslipItem.employee_id == employee_id,
                 PayslipItem.country_code == JP,
                 PayrollRun.status.in_((PayrollStatus.PAID.value, PayrollStatus.CLOSED.value)),
                 PayrollRun.pay_date <= as_of))
    if since is not None:
        q = q.filter(PayrollRun.pay_date >= since)
    if until is not None:
        q = q.filter(PayrollRun.pay_date < until)
    if current_run_id is not None:
        q = q.filter(PayrollRun.id != current_run_id)
    return q.order_by(PayrollRun.pay_date, PayslipItem.id).all()


def _jp_snapshot_result(item):
    return (getattr(item, "jp_calculation_snapshot", None) or {})


def _jp_bonus_priors(db: Session, organization_id: int, employee_id: int, as_of: date,
                     current_run_id: Optional[int] = None) -> dict:
    """The two prior bonus figures and the prior-month pay, never guessed.

    Health SBA is cumulative from 1 April; pension SBA is per calendar month.
    The engine stores both cap-consumed bases under ``jp_bonus``. The prior-month
    salary base is the previous calendar month's latest paid/closed salary
    payslip only; an absent month stays None (the engine blocks instead of
    treating it as zero).
    """
    year_start = _jp_insurance_year_start(as_of)
    month_start = date(as_of.year, as_of.month, 1)
    previous_month_start = (date(as_of.year - 1, 12, 1) if as_of.month == 1
                            else date(as_of.year, as_of.month - 1, 1))
    health = Decimal("0")
    pension_month = Decimal("0")
    for item, pay_date in _jp_prior_payslips(
            db, organization_id, employee_id, as_of, since=year_start,
            current_run_id=current_run_id):
        snap = _jp_snapshot_result(item)
        # A bonus paid inside a SALARY payment counts toward the caps exactly
        # like a bonus-only payment.
        bonus = snap.get("jp_bonus") or {}
        if not isinstance(bonus, dict):
            continue
        health_base = bonus.get("jp_bonus_health_sba_base")
        pension_base = bonus.get("jp_bonus_pension_sba_base")
        if health_base not in (None, ""):
            health += Decimal(str(health_base))
        if pay_date.year == as_of.year and pay_date.month == as_of.month:
            if pension_base not in (None, ""):
                pension_month += Decimal(str(pension_base))

    prior_salary_base = None
    for item, _pay_date in reversed(_jp_prior_payslips(
            db, organization_id, employee_id, as_of, since=previous_month_start,
            until=month_start, current_run_id=current_run_id)):
        snap = _jp_snapshot_result(item)
        kind = str(snap.get("jp_payment_kind") or "SALARY").upper()
        if kind == "SALARY" and snap.get("jp_wht_base") not in (None, ""):
            prior_salary_base = Decimal(str(snap["jp_wht_base"]))
            break
    return {"ytd_health_sba": health, "month_pension_sba": pension_month,
            "prior_month_pay_after_si": prior_salary_base}


def _jp_period(run, period, as_of: date):
    if period is not None:
        return period
    if run is not None:
        start = getattr(run, "period_start", None)
        end = getattr(run, "period_end", None)
        if start and end:
            return start, end
    start = date(as_of.year, as_of.month, 1)
    end = (date(as_of.year + 1, 1, 1) if as_of.month == 12
           else date(as_of.year, as_of.month + 1, 1)) - timedelta(days=1)
    return start, end


def _jp_holiday_dates(db: Session, start: date, end: date) -> set:
    from app.modules.payroll.engine.jurisdictions.japan import labour

    out = set()
    for year in range(start.year, end.year + 1):
        for holiday in _jp_pack_holidays(db, year):
            day = holiday.get("date") if isinstance(holiday, dict) else None
            if day and start.isoformat() <= day <= end.isoformat():
                out.add(day)
    return out


def _jp_scheduled_weekdays(conditions) -> Optional[set]:
    text = getattr(conditions, "scheduled_weekdays", None)
    if text in (None, ""):
        return None
    return {int(part) for part in str(text).split(",") if part.strip()}


def _jp_attendance_records(db: Session, organization_id: int, employee_id: int,
                           start: date, end: date) -> list:
    from app.modules.payroll.models import PayrollAttendanceRecord

    return (db.query(PayrollAttendanceRecord)
            .filter(PayrollAttendanceRecord.organization_id == organization_id,
                    PayrollAttendanceRecord.employee_id == employee_id,
                    PayrollAttendanceRecord.date >= start,
                    PayrollAttendanceRecord.date <= end)
            .order_by(PayrollAttendanceRecord.date, PayrollAttendanceRecord.id).all())


def _jp_attendance_fingerprint(records) -> tuple:
    """SHA-256 over every attendance fact the engine reads, in date order."""
    facts = [[r.date.isoformat(), str(getattr(r, "status", "") or ""),
              str(getattr(r, "hours", "") or ""), str(getattr(r, "check_in", "") or ""),
              str(getattr(r, "check_out", "") or ""), bool(getattr(r, "is_half_day", False)),
              str(getattr(r, "leave_type", "") or "")] for r in records]
    raw = json.dumps(facts, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(records)


def _jp_hours_approved(db: Session, organization_id: int, employee_id: int,
                       start: date, end: date) -> bool:
    """True only when an APPROVED attendance approval for exactly this period
    matches the attendance rows as they are now."""
    m = _jp_models()
    fingerprint, _count = _jp_attendance_fingerprint(
        _jp_attendance_records(db, organization_id, employee_id, start, end))
    return (db.query(m.PayrollJpAttendanceApproval)
            .filter(m.PayrollJpAttendanceApproval.organization_id == organization_id,
                    m.PayrollJpAttendanceApproval.employee_id == employee_id,
                    m.PayrollJpAttendanceApproval.period_start == start,
                    m.PayrollJpAttendanceApproval.period_end == end,
                    m.PayrollJpAttendanceApproval.status == "APPROVED",
                    m.PayrollJpAttendanceApproval.fingerprint == fingerprint)
            .first()) is not None


def _jp_hours_for_period(db: Session, organization_id: int, employee_id: int,
                         start: date, end: date, conditions) -> list:
    """Attendance days for the period, without inventing missing facts.

    Only ``present`` rows are worked days. The days of the first week that
    fall before the period are loaded as context (``in_period`` False) so the
    weekly limit is assessed over the whole week. Each day carries the
    schedule and the statutory day off from the work calendar; a fact the
    work conditions do not record is passed as None and the engine BLOCKS.
    A national holiday is never treated as the statutory day off.
    """
    if conditions is None or start is None or end is None:
        return []
    week_start = int(getattr(conditions, "week_start_day", 0) or 0)
    context_start = start - timedelta(days=(start.weekday() - week_start) % 7)
    records = _jp_attendance_records(db, organization_id, employee_id, context_start, end)
    holidays = _jp_holiday_dates(db, context_start, end)
    weekdays = _jp_scheduled_weekdays(conditions)
    day_off = getattr(conditions, "statutory_day_off_weekday", None)
    holidays_off = getattr(conditions, "public_holidays_off", None)
    daily = int(getattr(conditions, "scheduled_daily_minutes", 0) or 0)
    out = []
    for record in records:
        if str(getattr(record, "status", "") or "").lower() != "present":
            continue
        raw_hours = getattr(record, "hours", None)
        try:
            minutes = int(Decimal(str(raw_hours or 0)) * 60)
        except (InvalidOperation, ValueError):
            raise BadRequestException(
                f"Japan attendance hours on {record.date} are not a number.")
        day = record.date.isoformat()
        public_holiday = day in holidays
        scheduled = None if weekdays is None else (daily if record.date.weekday() in weekdays else 0)
        policy_missing = False
        if public_holiday and scheduled:
            if holidays_off is None:
                policy_missing = True
            elif holidays_off:
                scheduled = 0
        out.append({"date": day, "worked_minutes": minutes,
                    "scheduled_minutes": scheduled,
                    "statutory_day_off": (None if day_off is None
                                          else record.date.weekday() == int(day_off)),
                    "public_holiday": public_holiday,
                    "public_holiday_policy_missing": policy_missing,
                    "in_period": record.date >= start,
                    "check_in": getattr(record, "check_in", None),
                    "check_out": getattr(record, "check_out", None)})
    return out


def _jp_year_end_inputs(db: Session, organization_id: int, employee_id: int, run) -> dict:
    """The REVIEWED-and-APPLIED year-end case targeted at this run, if any."""
    run_id = getattr(run, "id", None)
    if run_id is None:
        return {"jp_year_end_difference": None, "jp_yea_case_id": None}
    m = _jp_models()
    case = (db.query(m.PayrollJpYeaCase)
            .filter(m.PayrollJpYeaCase.organization_id == organization_id,
                    m.PayrollJpYeaCase.employee_id == employee_id,
                    m.PayrollJpYeaCase.applied_run_id == run_id,
                    m.PayrollJpYeaCase.state.in_(("APPLIED", "LOCKED"))).first())
    if case is None:
        return {"jp_year_end_difference": None, "jp_yea_case_id": None}
    return {"jp_year_end_difference": case.difference, "jp_yea_case_id": case.id}


def resolve_jp_calc_inputs(db: Session, organization_id: int, employee, as_of: date,
                           run=None, period=None) -> dict:
    """Resolve every Japan input effective at ``as_of``. No value is inferred:
    a missing row stays missing so the engine's own BLOCK is the one surfaced.
    """
    m = _jp_models()
    registration = _jp_one_active(
        db, m.PayrollJpEmployerRegistration, organization_id, None, as_of,
        "employer registration")
    profile = _jp_one_active(
        db, m.PayrollJpWorkerTaxProfile, organization_id, employee.id, as_of,
        "worker tax profile")
    enrollment = _jp_one_active(
        db, m.PayrollJpSocialInsuranceEnrollment, organization_id, employee.id, as_of,
        "social-insurance enrollment")
    ei_profile = _jp_one_active(
        db, m.PayrollJpEmploymentInsuranceProfile, organization_id, employee.id, as_of,
        "employment-insurance profile")
    work_conditions = _jp_one_active(
        db, m.PayrollJpWorkConditions, organization_id, None, as_of,
        "work conditions")
    period_start, period_end = _jp_period(run, period, as_of)
    hours = _jp_hours_for_period(
        db, organization_id, employee.id, period_start, period_end, work_conditions)

    assessments = (db.query(m.PayrollJpResidentTaxAssessment)
                   .filter(m.PayrollJpResidentTaxAssessment.organization_id == organization_id,
                           m.PayrollJpResidentTaxAssessment.employee_id == employee.id,
                           m.PayrollJpResidentTaxAssessment.status.in_(("APPROVED", "SUPERSEDED")))
                   .order_by(m.PayrollJpResidentTaxAssessment.first_deduction_month,
                             m.PayrollJpResidentTaxAssessment.version,
                             m.PayrollJpResidentTaxAssessment.id).all())

    components = _jp_value(employee, "jp_components")
    if not isinstance(components, dict):
        components = None
    payment_kind = _jp_value(run, "jp_payment_kind") if run is not None else None
    payment_kind = str(payment_kind or "SALARY").strip().upper()
    if payment_kind not in ("SALARY", "BONUS"):
        raise BadRequestException("jp_payment_kind must be SALARY or BONUS.")
    has_bonus = any(str(name).upper() == "BONUS" for name in (components or {}))
    priors = (_jp_bonus_priors(db, organization_id, employee.id, as_of,
                               current_run_id=getattr(run, "id", None))
              if payment_kind == "BONUS" or has_bonus else {})

    return {
        "jp_worker_tax_profile": profile,
        "jp_employer_registration": registration,
        "jp_social_insurance_enrollment": enrollment,
        "jp_employment_insurance_profile": ei_profile,
        "jp_resident_tax_assessments": assessments,
        "jp_organization_id": organization_id,
        "jp_employee_id": employee.id,
        "jp_date_of_birth": getattr(employee, "date_of_birth", None),
        "jp_components": components,
        "jp_payment_kind": str(payment_kind).strip().upper(),
        "jp_prior_month_pay_after_si": priors.get("prior_month_pay_after_si"),
        "jp_ytd_health_sba": priors.get("ytd_health_sba"),
        "jp_month_pension_sba": priors.get("month_pension_sba"),
        "jp_social_insurance_events": _jp_events_for_month(
            db, organization_id, employee.id, as_of),
        **_jp_year_end_inputs(db, organization_id, employee.id, run),
        "jp_work_conditions": work_conditions,
        "jp_hours": hours,
        "jp_hours_approved": (bool(hours) and _jp_hours_approved(
            db, organization_id, employee.id, period_start, period_end)),
    }


def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of: Optional[date] = None,
                period=None) -> dict:
    on = as_of or getattr(run, "pay_date", None) or date.today()
    return resolve_jp_calc_inputs(db, employee.organization_id, employee, on, run=run,
                                  period=period)


# ---------------------------------------------------------------------
# Frozen context and payslip snapshot
# ---------------------------------------------------------------------
def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


_JP_CTX_DECIMALS = ("gross", "basic", "hra", "special_allowance", "overtime",
                    "additional_compensation", "jp_prior_month_pay_after_si",
                    "jp_ytd_health_sba", "jp_month_pension_sba", "jp_year_end_difference")
_JP_CTX_PLAIN = ("pay_frequency", "jp_organization_id", "jp_employee_id",
                 "jp_components", "jp_payment_kind", "unpaid_leave_days",
                 "date_of_joining", "jp_yea_case_id")
_JP_CTX_DATES = ("pay_date", "period_start", "period_end", "jp_date_of_birth",
                 "date_of_birth")
_JP_WORK_CONDITION_FIELDS = (
    "id", "effective_from", "effective_to", "working_time_system", "week_start_day",
    "scheduled_daily_minutes", "scheduled_monthly_hours", "workplace_prefecture",
    "specific_minimum_wage_applies", "scheduled_weekdays", "statutory_day_off_weekday",
    "public_holidays_off", "status", "evidence_ref",
)
_JP_RATE_FIELDS = ("employee_rate_pct", "employer_rate_pct", "flat_amount",
                   "text_value", "effective_from", "effective_to")
# Every TaxSlab field an engine module reads: a replay (correction, year-end)
# must select the same rows - the withholding column, the prefecture of a
# health or minimum-wage row and any formula included.
_JP_SLAB_FIELDS = ("rule_type", "filing_status", "tax_regime", "assessment_basis",
                   "tax_column", "tax_table_number", "jurisdiction_state", "rate_pct",
                   "employer_rate_pct", "min_amount", "max_amount", "flat_amount",
                   "formula_expression", "rate_label", "effective_from", "effective_to")
_JP_PROFILE_FIELDS = ("id", "residency_status", "declaration_class",
                      "declaration_received_on", "dependants_count", "dependant_facts",
                      "municipality_code", "residence_prefecture",
                      "resident_tax_collection", "my_number_vault_id", "effective_from",
                      "effective_to", "status", "evidence_ref")
_JP_REGISTRATION_FIELDS = ("id", "corporate_number", "withholding_tax_office",
                           "withholding_payer_status", "jps_office_symbol",
                           "jps_office_number", "health_insurer_type",
                           "health_insurer_code", "health_insurer_prefecture",
                           "si_deduction_timing", "labour_insurance_number",
                           "ei_office_number", "ei_industry_class",
                           "workers_comp_rate_class", "municipality_reporting_enabled",
                           "effective_from", "effective_to", "status", "evidence_ref")
_JP_ENROLLMENT_FIELDS = ("id", "health_eligible", "pension_eligible",
                         "health_insurer_code", "smr_health_grade", "smr_pension_grade",
                         "smr_health_amount", "smr_pension_amount", "smr_basis",
                         "actual_remuneration", "care_state", "child_support_state",
                         "qualification_date", "loss_date", "effective_from",
                         "effective_to", "status", "evidence_ref")
_JP_EI_FIELDS = ("id", "insured", "ei_insured_number", "industry_class",
                 "qualification_date", "loss_date", "effective_from", "effective_to",
                 "status", "evidence_ref")
_JP_ASSESSMENT_FIELDS = ("id", "municipality_code", "fiscal_notice_year", "notice_id",
                         "version", "received_on", "first_deduction_month",
                         "monthly_amounts", "total_amount", "source_hash", "replaces_id",
                         "status", "evidence_ref")
_JP_EVENT_FIELDS = ("id", "event_type", "effective_from", "effective_to", "payload",
                    "bonus_paid_on", "sba_amount", "report_due_on",
                    "submission_status", "receipt_ref", "evidence_ref")


def _jp_facts(row, fields):
    if row is None:
        return None
    return {name: getattr(row, name, None) for name in fields}


def jp_freeze_context(ctx, calculation_mode: str = "standard") -> dict:
    return _json_safe({
        "version": 1,
        "calculationMode": calculation_mode,
        "ctx": {k: getattr(ctx, k, None) for k in _JP_CTX_DECIMALS + _JP_CTX_PLAIN + _JP_CTX_DATES},
        "profile": _jp_facts(getattr(ctx, "jp_worker_tax_profile", None), _JP_PROFILE_FIELDS),
        "registration": _jp_facts(getattr(ctx, "jp_employer_registration", None),
                                  _JP_REGISTRATION_FIELDS),
        "enrollment": _jp_facts(getattr(ctx, "jp_social_insurance_enrollment", None),
                                _JP_ENROLLMENT_FIELDS),
        "employmentInsurance": _jp_facts(
            getattr(ctx, "jp_employment_insurance_profile", None), _JP_EI_FIELDS),
        "residentTaxAssessments": [
            _jp_facts(row, _JP_ASSESSMENT_FIELDS)
            for row in (getattr(ctx, "jp_resident_tax_assessments", None) or [])],
        "socialInsuranceEvents": [
            _jp_facts(row, _JP_EVENT_FIELDS)
            for row in (getattr(ctx, "jp_social_insurance_events", None) or [])],
        "workConditions": _jp_facts(getattr(ctx, "jp_work_conditions", None),
                                    _JP_WORK_CONDITION_FIELDS),
        "attendance": {
            "approved": bool(getattr(ctx, "jp_hours_approved", None)),
            "days": list(getattr(ctx, "jp_hours", None) or []),
        },
        "rateMap": {k: {f: getattr(r, f, None) for f in _JP_RATE_FIELDS}
                    for k, r in (getattr(ctx, "rate_map", None) or {}).items()},
        "slabs": [{f: getattr(s, f, None) for f in _JP_SLAB_FIELDS}
                  for s in (getattr(ctx, "slabs", None) or [])],
    })


JP_TOTAL_KEYS = ("jp_wht", "jp_si_employee_total", "jp_ei_employee",
                 "jp_resident_tax", "jp_employee_total", "jp_employer_total")


def jp_totals_all(result) -> dict:
    r = getattr(result, "jp_result", None) if not isinstance(result, dict) else result
    return {k: str((r or {}).get(k) or "0") for k in JP_TOTAL_KEYS}


def jp_payslip_snapshot(result, frozen: Optional[dict] = None) -> Optional[dict]:
    r = getattr(result, "jp_result", None) if not isinstance(result, dict) else result
    if not r:
        return None
    snap = {**r, "totalsAll": jp_totals_all(r)}
    if frozen is not None:
        snap["frozenContext"] = frozen
    return _json_safe(snap)


# Frozen values are JSON-safe strings; the engine needs dates and Decimals back.
_JP_THAW_DATE_KEYS = {"effective_from", "effective_to", "declaration_received_on",
                      "qualification_date", "loss_date", "received_on",
                      "first_deduction_month", "bonus_paid_on", "report_due_on", "date"}
_JP_THAW_DECIMAL_KEYS = {"employee_rate_pct", "employer_rate_pct", "flat_amount", "rate_pct",
                         "min_amount", "max_amount", "smr_health_amount", "smr_pension_amount",
                         "total_amount", "scheduled_monthly_hours", "sba_amount"}


def _jp_thaw_value(key, value):
    if value is None or value == "":
        return value
    if key in _JP_THAW_DATE_KEYS and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if key in _JP_THAW_DECIMAL_KEYS and not isinstance(value, Decimal):
        return Decimal(str(value))
    return value


def _jp_thaw_row(facts):
    from types import SimpleNamespace

    if facts is None:
        return None
    return SimpleNamespace(**{k: _jp_thaw_value(k, v) for k, v in facts.items()})


def jp_thaw_context(frozen: dict):
    """Rebuild the PayrollContext a payslip was calculated with, from its
    frozen snapshot (jp_freeze_context). Used by corrections and the
    year-end adjustment; nothing is re-read from the live tables."""
    from types import SimpleNamespace

    from app.modules.payroll.engine.base import PayrollContext

    if not frozen or frozen.get("version") != 1:
        raise BadRequestException("This payslip has no replayable Japan calculation context.")
    raw = dict(frozen.get("ctx") or {})
    ctx = {}
    for key, value in raw.items():
        if key in _JP_CTX_DECIMALS:
            ctx[key] = None if value in (None, "") else Decimal(str(value))
        elif key in _JP_CTX_DATES:
            ctx[key] = None if value in (None, "") else date.fromisoformat(str(value)[:10])
        else:
            ctx[key] = value
    attendance = frozen.get("attendance") or {}
    return PayrollContext(
        **ctx, country=JP,
        jp_worker_tax_profile=_jp_thaw_row(frozen.get("profile")),
        jp_employer_registration=_jp_thaw_row(frozen.get("registration")),
        jp_social_insurance_enrollment=_jp_thaw_row(frozen.get("enrollment")),
        jp_employment_insurance_profile=_jp_thaw_row(frozen.get("employmentInsurance")),
        jp_resident_tax_assessments=[_jp_thaw_row(r) for r in frozen.get("residentTaxAssessments") or []],
        jp_social_insurance_events=[_jp_thaw_row(r) for r in frozen.get("socialInsuranceEvents") or []],
        jp_work_conditions=_jp_thaw_row(frozen.get("workConditions")),
        jp_hours=list(attendance.get("days") or []),
        jp_hours_approved=bool(attendance.get("approved")),
        rate_map={k: SimpleNamespace(**{f: _jp_thaw_value(f, v) for f, v in row.items()})
                  for k, row in (frozen.get("rateMap") or {}).items()},
        slabs=[SimpleNamespace(**{f: _jp_thaw_value(f, v) for f, v in row.items()})
               for row in frozen.get("slabs") or []],
    )


def jp_replay(frozen: dict):
    """Recalculate a frozen Japan payslip exactly as it was calculated."""
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(jp_thaw_context(frozen), frozen.get("calculationMode") or "standard")


def jp_approval_fingerprint(db: Session, run) -> Optional[str]:
    import hashlib
    import json

    from app.modules.payroll.models import PayslipItem

    rows = (db.query(PayslipItem)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == JP)
            .order_by(PayslipItem.id).all())
    if not rows:
        return None
    payload = [{"employeeId": row.employee_id, "snapshot": row.jp_calculation_snapshot}
               for row in rows]
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------
# Run preflight
# ---------------------------------------------------------------------
def _jp_run_has_payslips(db: Session, run) -> bool:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem.id)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == JP)
            .first() is not None)


def before_run_transition(db: Session, run, next_status, actor_id: Optional[int]) -> None:
    """JP approval needs every payslip frozen; a later transition re-verifies
    the approval fingerprint and PAID records each bonus report obligation."""
    from fastapi import HTTPException, status as http_status

    from app.modules.payroll.models import PayrollStatus, PayslipItem

    if not _jp_run_has_payslips(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        missing = sum(1 for item in (db.query(PayslipItem)
                                     .filter(PayslipItem.payroll_run_id == run.id,
                                             PayslipItem.country_code == JP).all())
                      if item.jp_calculation_snapshot is None)
        if missing:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"Japan: {missing} payslip(s) have no frozen JP calculation snapshot - "
                "recalculate the run before approval."))
        from app.modules.payroll import japan_filing, japan_lifecycle as lifecycle

        japan_filing.refuse_uncertified_remittance_scheme(db, run)
        from app.modules.payroll import japan_year_end

        japan_year_end.require_cases_reflected(db, run)
        open_items = [e for e in lifecycle.jp_run_exceptions(db, run) if not e["approved"]]
        if open_items:
            listing = "; ".join(f"{e['code']} ({'employee #' + str(e['employeeId']) if e['employeeId'] else 'run'})"
                                for e in open_items)
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"Japan: {len(open_items)} exception(s) need a second person's approval "
                f"before the run is approved: {listing}"))
        run.jp_approval_fingerprint = jp_approval_fingerprint(db, run)
        return
    if next_status in (PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        current = jp_approval_fingerprint(db, run)
        if not run.jp_approval_fingerprint or current != run.jp_approval_fingerprint:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "Japan: the approved calculation no longer matches this run - "
                "recalculate and approve it again."))
    if next_status != PayrollStatus.PAID:
        return
    from app.modules.payroll import japan_lifecycle as lifecycle

    for item in (db.query(PayslipItem)
                 .filter(PayslipItem.payroll_run_id == run.id,
                         PayslipItem.country_code == JP)
                 .order_by(PayslipItem.id).all()):
        snap = item.jp_calculation_snapshot or {}
        if snap.get("jp_bonus"):
            lifecycle.record_bonus_obligation(
                db, organization_id=run.organization_id, employee_id=item.employee_id,
                jp_result=snap, paid_on=run.pay_date, actor_id=actor_id)
    from app.modules.payroll import japan_filing, japan_year_end

    japan_filing.refuse_uncertified_remittance_scheme(db, run)
    japan_filing.record_run_obligations(db, run, actor_id)
    japan_year_end.lock_cases_for_run(db, run)


# ---------------------------------------------------------------------
# Profile validation (the shared EmployeeStatutoryProfile has no JP columns)
# ---------------------------------------------------------------------
def _jp_statutory_profile_errors(data) -> list:
    errors = []
    residency = getattr(data, "jp_residency_status", None)
    if residency is not None:
        value = str(residency).strip().upper()
        if value not in ("RESIDENT", "NON_RESIDENT"):
            errors.append("jp_residency_status must be RESIDENT or NON_RESIDENT.")
    declaration = getattr(data, "jp_declaration_class", None)
    if declaration is not None:
        value = str(declaration).strip().upper()
        if value not in ("PRIMARY", "SECONDARY"):
            errors.append("jp_declaration_class must be PRIMARY or SECONDARY.")
    dependants = getattr(data, "jp_dependants_count", None)
    if dependants is not None and (not isinstance(dependants, int) or dependants < 0):
        errors.append("jp_dependants_count must be a whole number of zero or more.")
    collection = getattr(data, "jp_resident_tax_collection", None)
    if collection is not None:
        value = str(collection).strip().upper()
        if value not in ("SPECIAL", "NOT_APPLICABLE"):
            errors.append("jp_resident_tax_collection must be SPECIAL or NOT_APPLICABLE.")
    return errors


def _jp_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


# ---------------------------------------------------------------------
# Pack / service-registry / retention / summary hooks
# ---------------------------------------------------------------------
def _jp_pack_activation_refusal(db: Session, pack, actor_id: Optional[int]) -> Optional[str]:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if pack is None or (pack.jurisdiction_country or "").upper() != JP:
        return None
    marker = f"%{PENDING_G1_SUFFIX.strip()}%"
    pending_rates = (db.query(ContributionRate)
                     .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                             ContributionRate.organization_id.is_(None),
                             ContributionRate.label.like(marker))
                     .count())
    pending_slabs = (db.query(TaxSlab)
                     .filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None),
                             TaxSlab.rate_label.like(marker))
                     .count())
    if pending_rates or pending_slabs:
        return (f"{pending_rates + pending_slabs} Japan pack row(s) are still PENDING G1 - "
                "they must be signed at gate G1 before the pack can be activated")
    return None


def _jp_pack_holidays(db: Session, year: int) -> list:
    """The year's statutory holidays from the in-force JP pack's own calendar
    rows. No pack / no rows means nothing is seeded, never a guessed date."""
    from app.modules.payroll.engine.countries.japan import JapanCalculationBlockedError
    from app.modules.payroll.engine.jurisdictions.japan import labour
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        _rates, slabs, pack = resolve_tax_configuration(
            db, JP, payroll_date=date(year, 12, 31))
        if pack is None:
            return []
        return labour.holidays_for_year(slabs, year)
    except (BadRequestException, JapanCalculationBlockedError):
        return []


def _jp_template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    country = (getattr(template, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(template, "report_type", "") or "").upper()
    if country != JP and not report_type.startswith("JP_"):
        return None
    return ("Japan filing and payment-report templates stay inactive until the official "
            "form revision and the JP-1 evidence decision are recorded.")


def _jp_payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    return {}


def _jp_payslip_hold_view(item) -> Optional[dict]:
    return None


def _jp_statutory_editors(db: Session, pack) -> set:
    return set()


def _jp_decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _jp_retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    m = _jp_models()
    for model, label in (
            (m.PayrollJpWorkerTaxProfile, "worker tax profiles"),
            (m.PayrollJpSocialInsuranceEnrollment, "social-insurance enrollments"),
            (m.PayrollJpResidentTaxAssessment, "resident-tax notices")):
        if db.query(model.id).filter(model.organization_id == organization_id,
                                     model.employee_id == employee_id).first():
            return label
    return None


def _jp_has_statutory_profile(db: Session, employee_id: int) -> bool:
    from app.modules.payroll.models import PayrollJpWorkerTaxProfile

    return (db.query(PayrollJpWorkerTaxProfile.id)
            .filter(PayrollJpWorkerTaxProfile.employee_id == employee_id)
            .first() is not None)


def _jp_is_report(report) -> bool:
    country = (getattr(report, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(report, "report_type", "") or "").upper()
    return country == JP or report_type.startswith("JP_")


JP_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and the frozen JP calculation snapshot"),
    ("TAX_RECORDS", "Withholding, resident-tax notices and NTA records"),
    ("SOCIAL_INSURANCE_RECORDS", "SMR, social-insurance and bonus obligations"),
    ("EMPLOYEE_IDENTITY", "My Number vault metadata and worker tax profiles"),
    ("ACCESS_LOGS", "My Number reveal/export access events"),
    ("CORRECTIONS", "Payslip corrections and their evidence"),
)

JP_DECISIONS = {
    "D-1": ("Retention period per Japan data category", True),
    "D-2": ("Deletion vs anonymisation of My Number at end of retention", True),
    "D-3": ("Japan payroll-run approval four-eyes", True),
    "D-4": ("My Number reveal approval four-eyes", True),
    "D-5": ("Data location and cross-border transfer basis", True),
}


def _jp_evidence(db: Session, tag: str):
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact)
            .filter(SourceArtifact.form_number == tag,
                    SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    accepted = next((r for r in rows if (r.reviewer_id and r.file_path
                                         and r.reviewer_id != r.created_by_id)), None)
    return accepted, bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in JP_DECISIONS.items():
        accepted, submitted = _jp_evidence(db, f"JP-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks,
                    "evidenceTag": f"JP-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def _jp_retention_employee(db: Session, employee_id: int, organization_id: int) -> None:
    """Retention scope check: the employee must be this organisation's Japan
    employee (404 outside the tenant / jurisdiction)."""
    employee = _jp_employee(db, organization_id, employee_id)
    if (getattr(employee, "country_code", None) or "").upper() != JP:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Japan employee not found.")


def _jp_retention_settings():
    # The platform calls this hook with no arguments (retention_service.settings).
    from app.modules.payroll.retention_service import RetentionJurisdiction

    return RetentionJurisdiction(
        country=JP, label="Japan", categories=JP_RETENTION_CATEGORIES,
        period_decision="D-1", end_decision="D-2", decision_reference="JP-RETENTION",
        decision_state=_jp_decision_state,
        validate_employee=_jp_retention_employee,
        retained_record_label=_jp_retained_record_label,
        has_statutory_profile=_jp_has_statutory_profile,
        report_matches=_jp_is_report)


def statutory_summary(db: Session) -> dict:
    m = _jp_models()
    from app.modules.payroll.models import JurisdictionPack

    packs = (db.query(JurisdictionPack)
             .filter(JurisdictionPack.jurisdiction_country == JP,
                     JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.effective_from.desc()).all())
    registrations = (db.query(m.PayrollJpEmployerRegistration)
                     .filter(m.PayrollJpEmployerRegistration.status == "ACTIVE").count())
    profiles = (db.query(m.PayrollJpWorkerTaxProfile)
                .filter(m.PayrollJpWorkerTaxProfile.status == "ACTIVE").count())
    enrollments = (db.query(m.PayrollJpSocialInsuranceEnrollment)
                   .filter(m.PayrollJpSocialInsuranceEnrollment.status == "ACTIVE").count())
    notices = (db.query(m.PayrollJpResidentTaxAssessment)
               .filter(m.PayrollJpResidentTaxAssessment.status == "APPROVED").count())
    pending_events = (db.query(m.PayrollJpSocialInsuranceEvent)
                      .filter(m.PayrollJpSocialInsuranceEvent.submission_status == "CREATED")
                      .count())
    return {
        "jurisdiction": JP, "spec": SPEC, "available": False,
        "packs": [{"id": p.id, "packId": p.pack_id, "version": p.version,
                   "status": p.status,
                   "effectiveFrom": p.effective_from.isoformat() if p.effective_from else None,
                   "effectiveTo": p.effective_to.isoformat() if p.effective_to else None}
                  for p in packs],
        "activeEmployerRegistrations": registrations,
        "activeWorkerTaxProfiles": profiles,
        "activeSocialInsuranceEnrollments": enrollments,
        "approvedResidentTaxNotices": notices,
        "pendingSocialInsuranceEvents": pending_events,
        "decisions": owner_decisions(db),
        "note": ("Japan remains PLANNED; the official values and JP-1 evidence "
                 "decisions are not yet recorded."),
    }


def _jp_service_registry_transition(db: Session, target: str, reason: str,
                                    actor_id: Optional[int] = None,
                                    as_of: Optional[date] = None):
    from app.modules.payroll import service

    def readiness():
        unmet = [{"key": "JP-1", "label": "Japan official-values decision",
                  "detail": "JP-1 has not been recorded; every value stays PENDING G1"}]
        return unmet, {"decision": "JP-1", "recorded": False}

    return service.transition_service_registry(
        db, JP, target, reason, actor_id, label="Japan", readiness=readiness,
        invalid_target_message=lambda t: (
            f"Japan availability can only be {service.SERVICE_REGISTRY_OPEN} or "
            f"{service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message=("There is no Japan registry row - seed it (PLANNED); "
                             "it is never created here."),
        open_from_message=lambda a: f"Japan is {a}; only PLANNED moves to AVAILABLE.")


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_jp_statutory_profile_errors",
    "statutory_profile_values": "_jp_profile_values",
    "pack_activation_refusal": "_jp_pack_activation_refusal",
    "retention_settings": "_jp_retention_settings",
    "service_registry_transition": "_jp_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_jp_statutory_editors",
    "template_activation_refusal": "_jp_template_activation_refusal",
    "pack_holidays": "_jp_pack_holidays",
    "payment_treatment": "_jp_payment_treatment",
    "payslip_hold_view": "_jp_payslip_hold_view",
}

# ======================================================================
# Japan organisation version writers and approvals (Phase 5)
# ======================================================================
JP_EMPLOYER_FIELDS = (
    "effective_from", "effective_to", "corporate_number", "withholding_tax_office",
    "withholding_payer_status", "jps_office_symbol", "jps_office_number",
    "health_insurer_type", "health_insurer_code", "health_insurer_prefecture",
    "si_deduction_timing", "labour_insurance_number", "ei_office_number",
    "ei_industry_class", "workers_comp_rate_class", "municipality_reporting_enabled",
    "legal_entity_id", "source_document_id", "evidence_ref",
)
JP_PROFILE_FIELDS = (
    "effective_from", "effective_to", "residency_status", "declaration_class",
    "declaration_received_on", "dependants_count", "dependant_facts",
    "municipality_code", "residence_prefecture", "resident_tax_collection",
    "my_number_vault_id", "legal_entity_id", "evidence_ref",
)
JP_ENROLLMENT_FIELDS = (
    "effective_from", "effective_to", "health_eligible", "pension_eligible",
    "health_insurer_code", "smr_health_grade", "smr_pension_grade",
    "smr_health_amount", "smr_pension_amount", "smr_basis", "actual_remuneration",
    "care_state", "child_support_state", "qualification_date", "loss_date",
    "legal_entity_id", "evidence_ref",
)
JP_EI_FIELDS = (
    "effective_from", "effective_to", "insured", "ei_insured_number",
    "industry_class", "qualification_date", "loss_date", "legal_entity_id",
    "evidence_ref",
)
JP_ASSESSMENT_FIELDS = (
    "municipality_code", "fiscal_notice_year", "notice_id", "received_on",
    "first_deduction_month", "monthly_amounts", "total_amount", "source_hash",
    "replaces_id", "legal_entity_id", "evidence_ref",
)
JP_WORK_CONDITION_FIELDS = (
    "effective_from", "effective_to", "working_time_system", "week_start_day",
    "scheduled_daily_minutes", "scheduled_monthly_hours", "workplace_prefecture",
    "specific_minimum_wage_applies", "scheduled_weekdays", "statutory_day_off_weekday",
    "public_holidays_off", "legal_entity_id", "evidence_ref",
)
_JP_INT_FIELDS = {"dependants_count", "smr_health_grade", "smr_pension_grade",
                  "fiscal_notice_year", "version", "legal_entity_id",
                  "source_document_id", "my_number_vault_id", "replaces_id",
                  "week_start_day", "scheduled_daily_minutes", "statutory_day_off_weekday"}
_JP_DECIMAL_FIELDS = {"smr_health_amount", "smr_pension_amount", "total_amount",
                      "scheduled_monthly_hours"}
_JP_BOOL_FIELDS = {"municipality_reporting_enabled", "specific_minimum_wage_applies",
                   "public_holidays_off"}
_JP_DATE_FIELDS = {"effective_from", "effective_to", "declaration_received_on",
                   "qualification_date", "loss_date", "received_on",
                   "first_deduction_month"}


def _jp_employee(db: Session, organization_id: int, employee_id: int):
    from app.modules.payroll.models import PayrollEmployee

    employee = (db.query(PayrollEmployee)
                .filter(PayrollEmployee.id == employee_id,
                        PayrollEmployee.organization_id == organization_id).first())
    if employee is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Japan employee not found.")
    return employee


def _jp_bool(value, field: str) -> bool:
    """Strict boolean: the string "false" is False, never truthy."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise BadRequestException(f"{field} must be true or false.")


def _jp_work_calendar_errors(data: dict) -> None:
    for key in ("week_start_day", "statutory_day_off_weekday"):
        value = data.get(key)
        if value is not None and not 0 <= value <= 6:
            raise BadRequestException(f"{key} must be 0 (Monday) to 6 (Sunday).")
    text = data.get("scheduled_weekdays")
    if text is not None:
        parts = [part.strip() for part in str(text).split(",")]
        if (any(not part.isdigit() or not 0 <= int(part) <= 6 for part in parts)
                or len(set(parts)) != len(parts)):
            raise BadRequestException(
                "scheduled_weekdays must list distinct weekdays 0 (Monday) to 6 (Sunday), "
                "comma-separated.")
        data["scheduled_weekdays"] = ",".join(str(day) for day in sorted(int(p) for p in parts))
        day_off = data.get("statutory_day_off_weekday")
        if day_off is not None and day_off in {int(p) for p in parts}:
            raise BadRequestException("The statutory day off cannot be a scheduled working day.")


def _jp_clean(payload: dict, fields, *, required=()) -> dict:
    unknown = sorted(set(payload) - set(fields))
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    data = {}
    for key, value in payload.items():
        if value is None or value == "":
            data[key] = None
        elif key in _JP_DATE_FIELDS:
            data[key] = _as_date(value, key)
        elif key in _JP_INT_FIELDS:
            try:
                data[key] = int(value)
            except (TypeError, ValueError):
                raise BadRequestException(f"{key} must be a whole number.")
        elif key in _JP_DECIMAL_FIELDS:
            data[key] = _money(value, key)
        elif key in _JP_BOOL_FIELDS:
            data[key] = _jp_bool(value, key)
        else:
            data[key] = value
    missing = [key for key in required if data.get(key) in (None, "")]
    if missing:
        raise BadRequestException(f"required field(s): {', '.join(missing)}")
    return data


def _jp_audit(db, actor_id, action, entity_type, entity_id, old=None, new=None):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type,
                     entity_id=entity_id, old_value=old, new_value=new, auto_commit=False)


def _jp_create_version(db: Session, model, organization_id: int, employee_id: Optional[int],
                       data: dict, actor_id: Optional[int], label: str):
    query = db.query(model).filter(model.organization_id == organization_id)
    if employee_id is not None:
        query = query.filter(model.employee_id == employee_id)
    prior = query.order_by(model.effective_from.desc(), model.id.desc()).first()
    row = model(organization_id=organization_id, status="DRAFT",
                created_by_id=actor_id, previous_version_id=getattr(prior, "id", None),
                **data)
    if employee_id is not None:
        row.employee_id = employee_id
    db.add(row)
    db.flush()
    _jp_audit(db, actor_id, "created", label, row.id,
              new={"effective_from": data.get("effective_from").isoformat()})
    return row


def record_employer_registration(db: Session, organization_id: int, payload: dict,
                                 actor_id: Optional[int]):
    m = _jp_models()
    data = _jp_clean(payload, JP_EMPLOYER_FIELDS,
                     required=("effective_from", "health_insurer_type",
                               "ei_industry_class"))
    return _jp_create_version(db, m.PayrollJpEmployerRegistration, organization_id, None,
                              data, actor_id, "jp_employer_registration")


def record_work_conditions(db: Session, organization_id: int, payload: dict,
                           actor_id: Optional[int]):
    m = _jp_models()
    data = _jp_clean(
        payload, JP_WORK_CONDITION_FIELDS,
        required=("effective_from", "working_time_system", "week_start_day",
                  "scheduled_daily_minutes", "scheduled_monthly_hours",
                  "workplace_prefecture"))
    _jp_work_calendar_errors(data)
    return _jp_create_version(db, m.PayrollJpWorkConditions, organization_id, None,
                              data, actor_id, "jp_work_conditions")


def record_worker_tax_profile(db: Session, organization_id: int, employee_id: int,
                              payload: dict, actor_id: Optional[int]):
    m = _jp_models()
    _jp_employee(db, organization_id, employee_id)
    data = _jp_clean(payload, JP_PROFILE_FIELDS, required=("effective_from",))
    return _jp_create_version(db, m.PayrollJpWorkerTaxProfile, organization_id,
                              employee_id, data, actor_id, "jp_worker_tax_profile")


def record_social_insurance_enrollment(db: Session, organization_id: int, employee_id: int,
                                       payload: dict, actor_id: Optional[int]):
    m = _jp_models()
    _jp_employee(db, organization_id, employee_id)
    data = _jp_clean(payload, JP_ENROLLMENT_FIELDS,
                     required=("effective_from", "health_eligible", "pension_eligible"))
    return _jp_create_version(db, m.PayrollJpSocialInsuranceEnrollment, organization_id,
                              employee_id, data, actor_id, "jp_social_insurance_enrollment")


def record_employment_insurance_profile(db: Session, organization_id: int, employee_id: int,
                                        payload: dict, actor_id: Optional[int]):
    m = _jp_models()
    _jp_employee(db, organization_id, employee_id)
    data = _jp_clean(payload, JP_EI_FIELDS,
                     required=("effective_from", "insured", "industry_class"))
    return _jp_create_version(db, m.PayrollJpEmploymentInsuranceProfile, organization_id,
                              employee_id, data, actor_id, "jp_employment_insurance_profile")


def _jp_approve_version(db: Session, model, organization_id: int, row_id: int,
                        actor_id: Optional[int], label: str):
    from app.modules.payroll.service import require_four_eyes

    row = (db.query(model).filter(model.id == row_id,
                                  model.organization_id == organization_id).first())
    if row is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException(f"Japan {label.replace('_', ' ')} not found.")
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT {label.replace('_', ' ')} can be approved.")
    require_four_eyes(row.created_by_id, actor_id, f"Approving a Japan {label}",
                      db=db, entity_type=label, entity_id=row.id,
                      current_status=row.status)
    start = row.effective_from
    q = (db.query(model)
         .filter(model.organization_id == organization_id,
                 model.status == "ACTIVE",
                 model.id != row.id))
    if hasattr(row, "employee_id"):
        q = q.filter(model.employee_id == row.employee_id)
    for old in q.all():
        if old.effective_from >= start:
            raise BadRequestException("A version on or after this effective date already exists.")
        if old.effective_to is None or old.effective_to >= start:
            old.effective_to = date.fromordinal(start.toordinal() - 1)
            old.status = "SUPERSEDED"
    row.status = "ACTIVE"
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    _jp_audit(db, actor_id, "approved", label, row.id,
              old={"status": "DRAFT"},
              new={"status": "ACTIVE", "effective_from": start.isoformat()})
    return row


def approve_employer_registration(db: Session, organization_id: int, row_id: int,
                                  actor_id: Optional[int]):
    return _jp_approve_version(db, _jp_models().PayrollJpEmployerRegistration,
                               organization_id, row_id, actor_id, "jp_employer_registration")


def approve_work_conditions(db: Session, organization_id: int, row_id: int,
                            actor_id: Optional[int]):
    return _jp_approve_version(db, _jp_models().PayrollJpWorkConditions,
                               organization_id, row_id, actor_id, "jp_work_conditions")


def list_bonus_reports(db: Session, organization_id: int, status: Optional[str] = None,
                       today: Optional[date] = None) -> list:
    """The JPS bonus payment report obligations (BONUS events) of the
    organisation, oldest due first, with an overdue flag. ``status`` filters
    on the event's submission status; OPEN means not yet SUBMITTED/ACCEPTED."""
    m = _jp_models()
    Event = m.PayrollJpSocialInsuranceEvent
    today = today or date.today()
    q = db.query(Event).filter(Event.organization_id == organization_id,
                               Event.event_type == "BONUS")
    wanted = str(status or "").strip().upper()
    if wanted == "OPEN":
        q = q.filter(Event.submission_status.in_(("CREATED", "APPROVED", "REJECTED")))
    elif wanted:
        q = q.filter(Event.submission_status == wanted)
    out = []
    for row in q.order_by(Event.report_due_on, Event.id).all():
        done = row.submission_status in ("SUBMITTED", "ACCEPTED", "CORRECTED")
        out.append({"id": row.id, "employeeId": row.employee_id,
                    "bonusPaidOn": row.bonus_paid_on.isoformat() if row.bonus_paid_on else None,
                    "sbaAmount": None if row.sba_amount is None else str(row.sba_amount),
                    "reportDueOn": row.report_due_on.isoformat() if row.report_due_on else None,
                    "submissionStatus": row.submission_status, "receiptRef": row.receipt_ref,
                    "overdue": bool(row.report_due_on and not done and row.report_due_on < today)})
    return out


def employee_summary(db: Session, organization_id: int, employee_id: int,
                     as_of: Optional[date] = None) -> dict:
    """One read for the employee panel: the versions in force on ``as_of``,
    the latest attendance approvals and the masked My Number rows. Several
    ACTIVE versions in force are reported, never resolved by picking one."""
    m = _jp_models()
    employee = _jp_employee(db, organization_id, employee_id)
    as_of = as_of or date.today()

    def in_force(model, employee_scoped=True):
        q = db.query(model).filter(model.organization_id == organization_id,
                                   model.status == "ACTIVE",
                                   model.effective_from <= as_of,
                                   (model.effective_to.is_(None)) | (model.effective_to >= as_of))
        if employee_scoped:
            q = q.filter(model.employee_id == employee_id)
        rows = q.order_by(model.effective_from.desc(), model.id.desc()).all()
        if not rows:
            return {"state": "MISSING", "row": None}
        if len(rows) > 1:
            return {"state": "AMBIGUOUS", "row": None, "count": len(rows)}
        row = rows[0]
        return {"state": "ACTIVE",
                "row": {c.name: getattr(row, c.name) for c in row.__table__.columns}}

    approvals = (db.query(m.PayrollJpAttendanceApproval)
                 .filter(m.PayrollJpAttendanceApproval.organization_id == organization_id,
                         m.PayrollJpAttendanceApproval.employee_id == employee_id)
                 .order_by(m.PayrollJpAttendanceApproval.period_start.desc(),
                           m.PayrollJpAttendanceApproval.id.desc()).limit(6).all())
    return {
        "employeeId": employee.id, "asOf": as_of.isoformat(),
        "countryCode": (getattr(employee, "country_code", None) or "").upper() or None,
        "taxProfile": in_force(m.PayrollJpWorkerTaxProfile),
        "socialInsurance": in_force(m.PayrollJpSocialInsuranceEnrollment),
        "employmentInsurance": in_force(m.PayrollJpEmploymentInsuranceProfile),
        "workConditions": in_force(m.PayrollJpWorkConditions, employee_scoped=False),
        "attendanceApprovals": [
            {"id": a.id, "periodStart": a.period_start.isoformat(),
             "periodEnd": a.period_end.isoformat(), "status": a.status,
             "rowCount": a.row_count, "createdById": a.created_by_id,
             "approvedById": a.approved_by_id} for a in approvals],
        "myNumbers": list_my_numbers(db, organization_id, employee_id),
    }


def request_attendance_approval(db: Session, organization_id: int, employee_id: int,
                                payload: dict, actor_id: Optional[int]):
    """Ask a second person to approve one employee's attendance for one pay
    period. The request records a fingerprint of the rows as they are now."""
    m = _jp_models()
    _jp_employee(db, organization_id, employee_id)
    unknown = sorted(set(payload) - {"period_start", "period_end", "evidence_ref"})
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    start = _as_date(payload.get("period_start"), "period_start")
    end = _as_date(payload.get("period_end"), "period_end")
    if end < start:
        raise BadRequestException("period_end must not be before period_start.")
    records = _jp_attendance_records(db, organization_id, employee_id, start, end)
    if not records:
        raise BadRequestException("There is no attendance in this period to approve.")
    fingerprint, count = _jp_attendance_fingerprint(records)
    row = m.PayrollJpAttendanceApproval(
        organization_id=organization_id, employee_id=employee_id, period_start=start,
        period_end=end, fingerprint=fingerprint, row_count=count, status="REQUESTED",
        evidence_ref=payload.get("evidence_ref") or None, created_by_id=actor_id)
    db.add(row)
    db.flush()
    _jp_audit(db, actor_id, "created", "jp_attendance_approval", row.id,
              new={"period_start": start.isoformat(), "period_end": end.isoformat(),
                   "row_count": count})
    return row


def approve_attendance_approval(db: Session, organization_id: int, approval_id: int,
                                actor_id: Optional[int]):
    """REQUESTED -> APPROVED by a different person, only while the attendance
    rows still match the fingerprint taken at the request."""
    from app.modules.payroll.service import require_four_eyes

    m = _jp_models()
    row = (db.query(m.PayrollJpAttendanceApproval)
           .filter(m.PayrollJpAttendanceApproval.id == approval_id,
                   m.PayrollJpAttendanceApproval.organization_id == organization_id).first())
    if row is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Japan attendance approval not found.")
    if row.status != "REQUESTED":
        raise BadRequestException(f"Only a REQUESTED attendance approval can be approved "
                                  f"(this one is {row.status}).")
    require_four_eyes(row.created_by_id, actor_id, "Approving Japan attendance",
                      db=db, entity_type="jp_attendance_approval", entity_id=row.id,
                      current_status=row.status)
    fingerprint, _count = _jp_attendance_fingerprint(_jp_attendance_records(
        db, organization_id, row.employee_id, row.period_start, row.period_end))
    if fingerprint != row.fingerprint:
        raise BadRequestException("The attendance changed after this approval was requested; "
                                  "request a new approval.")
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    _jp_audit(db, actor_id, "approved", "jp_attendance_approval", row.id,
              old={"status": "REQUESTED"}, new={"status": "APPROVED"})
    return row


def approve_worker_tax_profile(db: Session, organization_id: int, row_id: int,
                               actor_id: Optional[int]):
    return _jp_approve_version(db, _jp_models().PayrollJpWorkerTaxProfile,
                               organization_id, row_id, actor_id, "jp_worker_tax_profile")


def approve_social_insurance_enrollment(db: Session, organization_id: int, row_id: int,
                                        actor_id: Optional[int]):
    return _jp_approve_version(db, _jp_models().PayrollJpSocialInsuranceEnrollment,
                               organization_id, row_id, actor_id,
                               "jp_social_insurance_enrollment")


def approve_employment_insurance_profile(db: Session, organization_id: int, row_id: int,
                                         actor_id: Optional[int]):
    return _jp_approve_version(db, _jp_models().PayrollJpEmploymentInsuranceProfile,
                               organization_id, row_id, actor_id,
                               "jp_employment_insurance_profile")


def record_resident_tax_assessment(db: Session, organization_id: int, employee_id: int,
                                   payload: dict, actor_id: Optional[int]):
    m = _jp_models()
    _jp_employee(db, organization_id, employee_id)
    data = _jp_clean(payload, JP_ASSESSMENT_FIELDS,
                     required=("municipality_code", "fiscal_notice_year", "notice_id",
                               "received_on", "first_deduction_month",
                               "monthly_amounts", "total_amount", "source_hash"))
    amounts = data["monthly_amounts"]
    if not isinstance(amounts, dict) or len(amounts) != 12:
        raise BadRequestException("monthly_amounts must be an object of exactly twelve amounts.")
    cleaned = {}
    for key, value in amounts.items():
        if (not isinstance(key, str) or len(key) != 7 or key[4] != "-"
                or not key[:4].isdigit() or not key[5:].isdigit()
                or not 1 <= int(key[5:]) <= 12):
            raise BadRequestException("monthly_amounts keys must be YYYY-MM.")
        amount = _money(value, f"monthly_amounts.{key}")
        if amount is None:
            raise BadRequestException(f"monthly_amounts.{key} must be an amount.")
        cleaned[key] = str(amount)
    data["monthly_amounts"] = cleaned
    latest = (db.query(m.PayrollJpResidentTaxAssessment)
              .filter(m.PayrollJpResidentTaxAssessment.organization_id == organization_id,
                      m.PayrollJpResidentTaxAssessment.employee_id == employee_id,
                      m.PayrollJpResidentTaxAssessment.municipality_code == data["municipality_code"],
                      m.PayrollJpResidentTaxAssessment.fiscal_notice_year == data["fiscal_notice_year"])
              .order_by(m.PayrollJpResidentTaxAssessment.version.desc()).first())
    data["version"] = (latest.version + 1) if latest else 1
    row = m.PayrollJpResidentTaxAssessment(
        organization_id=organization_id, employee_id=employee_id, status="IMPORTED",
        created_by_id=actor_id, previous_version_id=getattr(latest, "id", None),
        **data)
    db.add(row)
    db.flush()
    _jp_audit(db, actor_id, "created", "jp_resident_tax_assessment", row.id,
              new={"notice_id": row.notice_id, "version": row.version})
    return row


def approve_resident_tax_assessment(db: Session, organization_id: int, row_id: int,
                                    actor_id: Optional[int]):
    from app.modules.payroll.service import require_four_eyes

    m = _jp_models()
    Assessment = m.PayrollJpResidentTaxAssessment
    row = (db.query(Assessment)
           .filter(Assessment.id == row_id,
                   Assessment.organization_id == organization_id).first())
    if row is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("Japan resident-tax notice not found.")
    if row.status != "IMPORTED":
        raise BadRequestException("Only an IMPORTED resident-tax notice can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a Japan resident-tax notice",
                      db=db, entity_type="jp_resident_tax_assessment", entity_id=row.id,
                      current_status=row.status)
    now = datetime.utcnow()
    for old in (db.query(Assessment)
                .filter(Assessment.organization_id == organization_id,
                        Assessment.employee_id == row.employee_id,
                        Assessment.municipality_code == row.municipality_code,
                        Assessment.fiscal_notice_year == row.fiscal_notice_year,
                        Assessment.id != row.id,
                        Assessment.status == "APPROVED").all()):
        old.status = "SUPERSEDED"
        old.updated_at = now
    if row.replaces_id:
        replaced = db.get(Assessment, row.replaces_id)
        if replaced is not None and replaced.organization_id == organization_id:
            replaced.status = "SUPERSEDED"
            replaced.updated_at = now
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = now
    db.flush()
    _jp_audit(db, actor_id, "approved", "jp_resident_tax_assessment", row.id,
              old={"status": "IMPORTED"}, new={"status": "APPROVED"})
    return row

# ======================================================================
# My Number vault boundary (Phase 5)
# ======================================================================
def _jp_vault(db: Session, organization_id: int, vault_id: int):
    from app.core.exceptions import NotFoundException

    m = _jp_models()
    row = (db.query(m.PayrollJpMyNumberVault)
           .filter(m.PayrollJpMyNumberVault.id == vault_id,
                   m.PayrollJpMyNumberVault.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Japan My Number vault row not found.")
    return row


def _jp_vault_event(db: Session, organization_id: int, row, action: str, actor_id,
                    reason: Optional[str] = None, purpose: Optional[str] = None):
    m = _jp_models()
    event = m.PayrollJpMyNumberAccessEvent(
        organization_id=organization_id, employee_id=row.employee_id, vault_id=row.id,
        actor_id=actor_id, action=action, purpose=purpose or "TAX_SOCIAL_INSURANCE",
        reason=reason, created_by_id=actor_id)
    db.add(event)
    db.flush()
    _jp_audit(db, actor_id, action.lower(), "jp_my_number_access_event", event.id,
              new={"employee_id": row.employee_id, "vault_id": row.id})
    return event


def list_my_numbers(db: Session, organization_id: int, employee_id: Optional[int] = None):
    from app.modules.payroll import japan_my_number as my

    m = _jp_models()
    q = (db.query(m.PayrollJpMyNumberVault)
         .filter(m.PayrollJpMyNumberVault.organization_id == organization_id))
    if employee_id is not None:
        _jp_employee(db, organization_id, employee_id)
        q = q.filter(m.PayrollJpMyNumberVault.employee_id == employee_id)
    return [{"id": row.id, "employeeId": row.employee_id,
             "subjectType": row.subject_type, "subjectRef": row.subject_ref,
             "masked": my.masked(), "purpose": row.purpose, "status": row.status,
             "keyVersion": row.key_version,
             "collectedAt": row.collected_at.isoformat() if row.collected_at else None,
             "deletedAt": row.deleted_at.isoformat() if row.deleted_at else None}
            for row in q.order_by(m.PayrollJpMyNumberVault.id).all()]


def create_my_number(db: Session, organization_id: int, employee_id: int, payload: dict,
                     actor_id: Optional[int]):
    from app.modules.payroll import japan_my_number as my

    m = _jp_models()
    _jp_employee(db, organization_id, employee_id)
    number = str(payload.get("myNumber") or "").strip()
    subject_type = str(payload.get("subjectType") or "EMPLOYEE").strip().upper()
    if subject_type not in ("EMPLOYEE", "DEPENDANT"):
        raise BadRequestException("subjectType must be EMPLOYEE or DEPENDANT.")
    subject_ref = str(payload.get("subjectRef") or "self").strip() or "self"
    existing = (db.query(m.PayrollJpMyNumberVault)
                .filter(m.PayrollJpMyNumberVault.organization_id == organization_id,
                        m.PayrollJpMyNumberVault.employee_id == employee_id,
                        m.PayrollJpMyNumberVault.subject_type == subject_type,
                        m.PayrollJpMyNumberVault.subject_ref == subject_ref,
                        m.PayrollJpMyNumberVault.status == "ACTIVE").first())
    if existing is not None:
        raise BadRequestException("An ACTIVE My Number already exists for this subject; delete it first.")
    try:
        fingerprint = my.fingerprint(number)
    except my.MyNumberError as exc:
        raise BadRequestException(str(exc))
    duplicate = (db.query(m.PayrollJpMyNumberVault)
                 .filter(m.PayrollJpMyNumberVault.organization_id == organization_id,
                         m.PayrollJpMyNumberVault.fingerprint == fingerprint,
                         m.PayrollJpMyNumberVault.status == "ACTIVE").first())
    if duplicate is not None:
        raise BadRequestException("This My Number is already held for another active vault subject.")
    row = m.PayrollJpMyNumberVault(
        organization_id=organization_id, employee_id=employee_id,
        subject_type=subject_type, subject_ref=subject_ref, ciphertext="",
        key_version=1, fingerprint=fingerprint, purpose="TAX_SOCIAL_INSURANCE",
        collected_at=datetime.utcnow(), identity_verified_by=payload.get("identityVerifiedBy"),
        status="ACTIVE", created_by_id=actor_id, evidence_ref=payload.get("evidenceRef"))
    db.add(row)
    db.flush()
    try:
        ciphertext, version = my.encrypt(number, owner=my.vault_owner(
            organization_id, employee_id, row.id))
    except my.MyNumberError as exc:
        db.rollback()
        raise BadRequestException(str(exc))
    row.ciphertext = ciphertext
    row.key_version = version
    db.flush()
    _jp_vault_event(db, organization_id, row, "CREATE", actor_id)
    return row


def request_my_number_reveal(db: Session, organization_id: int, vault_id: int, reason: str,
                             actor_id: Optional[int]):
    row = _jp_vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The My Number has been deleted.")
    if not (reason or "").strip():
        raise BadRequestException("A reveal request needs a reason.")
    return _jp_vault_event(db, organization_id, row, "REVEAL_REQUESTED", actor_id,
                           reason=reason.strip(), purpose="REVEAL")


def approve_my_number_reveal(db: Session, organization_id: int, vault_id: int,
                             actor_id: Optional[int]):
    from app.modules.payroll.service import require_four_eyes

    m = _jp_models()
    row = _jp_vault(db, organization_id, vault_id)
    request = (db.query(m.PayrollJpMyNumberAccessEvent)
               .filter(m.PayrollJpMyNumberAccessEvent.organization_id == organization_id,
                       m.PayrollJpMyNumberAccessEvent.vault_id == row.id,
                       m.PayrollJpMyNumberAccessEvent.action == "REVEAL_REQUESTED")
               .order_by(m.PayrollJpMyNumberAccessEvent.id.desc()).first())
    if request is None:
        raise BadRequestException("There is no reveal request to approve.")
    approved = (db.query(m.PayrollJpMyNumberAccessEvent)
                .filter(m.PayrollJpMyNumberAccessEvent.organization_id == organization_id,
                        m.PayrollJpMyNumberAccessEvent.vault_id == row.id,
                        m.PayrollJpMyNumberAccessEvent.action == "REVEAL_APPROVED",
                        m.PayrollJpMyNumberAccessEvent.id > request.id).first())
    if approved is not None:
        raise BadRequestException("This reveal request has already been approved.")
    require_four_eyes(request.actor_id, actor_id, "Approving a My Number reveal",
                      db=db, entity_type="jp_my_number_access_event", entity_id=request.id,
                      current_status="REVEAL_REQUESTED")
    return _jp_vault_event(db, organization_id, row, "REVEAL_APPROVED", actor_id,
                           reason=request.reason, purpose="REVEAL")


def reveal_my_number(db: Session, organization_id: int, vault_id: int, actor_id: Optional[int]):
    from app.modules.payroll import japan_my_number as my

    m = _jp_models()
    row = _jp_vault(db, organization_id, vault_id)
    request = (db.query(m.PayrollJpMyNumberAccessEvent)
               .filter(m.PayrollJpMyNumberAccessEvent.organization_id == organization_id,
                       m.PayrollJpMyNumberAccessEvent.vault_id == row.id,
                       m.PayrollJpMyNumberAccessEvent.action == "REVEAL_REQUESTED")
               .order_by(m.PayrollJpMyNumberAccessEvent.id.desc()).first())
    approved = (db.query(m.PayrollJpMyNumberAccessEvent)
                .filter(m.PayrollJpMyNumberAccessEvent.organization_id == organization_id,
                        m.PayrollJpMyNumberAccessEvent.vault_id == row.id,
                        m.PayrollJpMyNumberAccessEvent.action == "REVEAL_APPROVED",
                        m.PayrollJpMyNumberAccessEvent.id > (request.id if request else 0))
                .order_by(m.PayrollJpMyNumberAccessEvent.id.desc()).first())
    if request is None or approved is None:
        raise BadRequestException("A reveal needs a request and a second person's approval.")
    # Owner-bound only: an unbound retry would let ciphertext copied from
    # another row reveal as this employee's number (no unbound row was ever
    # collected - Japan has never been enabled for a tenant).
    try:
        number = my.decrypt(row.ciphertext, row.key_version,
                            owner=my.vault_owner(organization_id, row.employee_id, row.id))
    except my.MyNumberError as bound_error:
        raise BadRequestException(str(bound_error))
    _jp_vault_event(db, organization_id, row, "REVEALED", actor_id,
                    reason=request.reason, purpose="REVEAL")
    return {"myNumber": number, "employeeId": row.employee_id,
            "subjectType": row.subject_type, "subjectRef": row.subject_ref}


def delete_my_number(db: Session, organization_id: int, vault_id: int,
                     actor_id: Optional[int]):
    row = _jp_vault(db, organization_id, vault_id)
    if row.status == "DELETED":
        raise BadRequestException("The My Number has already been deleted.")
    row.status = "DELETED"
    row.deleted_at = datetime.utcnow()
    row.ciphertext = None
    db.flush()
    _jp_vault_event(db, organization_id, row, "DELETED", actor_id)
    return row
