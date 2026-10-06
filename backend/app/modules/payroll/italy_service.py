"""modules/payroll/italy_service.py
----------------------------------
Italy (ZP-IT-ENG-001) service layer: everything between the database and
engine/countries/italy.py.

Kept out of service.py on purpose — that module is shared by every
jurisdiction — and wired into it at exactly the same points as Ireland and
Sweden: the per-employee input resolver (preview, generation, correction),
the payslip snapshot, and the year-to-date posting inside _post_payslip_ytd.

Same discipline as _resolve_ie_calc_inputs / _resolve_se_calc_inputs: the
resolver assembles FACTS only and never a statutory result. Whatever it cannot
establish is left absent, so italy.py raises its own specific block instead of
this layer guessing — an unrecorded surtax balance, a part-time worker with no
hours, a missing CCNL level all reach the operator as named blocks.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.payroll.engine.countries import italy_content
from app.modules.payroll.models import (
    CollectiveAgreement,
    EmployerItalyProfile,
    ItalyCcnlLevelTerms,
    PayrollYtdAccumulator,
)

_COUNTRY = "IT"
ZERO = Decimal("0")
_YEAR_COMPONENTS = ("it_irpef", "it_inps_base", "it_fringe", "it_wedge_paid", "it_mensilita",
                    "it_addreg_saldo", "it_addcom_saldo", "it_addcom_acconto")
_RECOVERY = "it_wedge_recovery"
_RECOVERY_INST = "it_wedge_recovery_inst"


def tax_year_key(year: int) -> str:
    """PayrollYtdAccumulator.tax_year for an Italian calendar year (the US
    "US-CY-2026" convention)."""
    return f"IT-CY-{year}"


# ── reads ───────────────────────────────────────────────────────────────────
def _rows(db: Session, employee_id: int, tax_year: str) -> dict:
    return {r.tax_component: r for r in db.query(PayrollYtdAccumulator).filter(
        PayrollYtdAccumulator.employee_id == employee_id,
        PayrollYtdAccumulator.tax_year == tax_year).all()}


def _wages(rows: dict, component: str) -> Decimal:
    row = rows.get(component)
    return Decimal(str(row.ytd_taxable_wages)) if row is not None else ZERO


def _withheld(rows: dict, component: str) -> Decimal:
    row = rows.get(component)
    return Decimal(str(row.ytd_tax_withheld)) if row is not None else ZERO


def resolve_ccnl_level_terms(db: Session, profile, as_of: date) -> Optional[ItalyCcnlLevelTerms]:
    """§9 — the Active terms in force on `as_of` for the worker's CNEL code and
    level, or None. Draft content never drives a payroll (IT-003)."""
    cnel, level = getattr(profile, "it_cnel_code", None), getattr(profile, "it_cnel_level", None)
    if not cnel or not level:
        return None
    return (db.query(ItalyCcnlLevelTerms)
            .join(CollectiveAgreement, CollectiveAgreement.id == ItalyCcnlLevelTerms.collective_agreement_id)
            .filter(CollectiveAgreement.jurisdiction_country == _COUNTRY,
                    CollectiveAgreement.agreement_code == cnel,
                    CollectiveAgreement.status == "Active",
                    ItalyCcnlLevelTerms.level_code == level,
                    ItalyCcnlLevelTerms.status == "Active",
                    ItalyCcnlLevelTerms.effective_from <= as_of,
                    (ItalyCcnlLevelTerms.effective_to.is_(None)) | (ItalyCcnlLevelTerms.effective_to >= as_of))
            .order_by(ItalyCcnlLevelTerms.effective_from.desc())
            .first())


def contributory_days(period_start: Optional[date], period_end: Optional[date],
                      joined: Optional[date], left: Optional[date]) -> dict:
    """§6 — the contributory period. A worker employed the whole period is a
    FULL month (the engine applies the configured day count); otherwise the
    Monday-Saturday days of employment inside the period are counted (the
    six-day week behind INPS's monthly convention). Never more than a full
    month. Returns {} when the period itself is unknown, so the engine blocks."""
    if period_start is None or period_end is None or period_end < period_start:
        return {}
    start = max(period_start, joined) if joined else period_start
    end = min(period_end, left) if left else period_end
    if start == period_start and end == period_end:
        return {"it_contributory_full_month": True}
    if end < start:
        return {"it_contributory_days": ZERO}
    days, day = 0, start
    while day <= end:
        if day.weekday() < 6:   # Monday-Saturday
            days += 1
        day += timedelta(days=1)
    return {"it_contributory_days": Decimal(min(days, 26))}


def work_days_in_year(year: int, joined: Optional[date], left: Optional[date]) -> int:
    """§4 — days of employment in the tax year, for pro-rating the deductions:
    from hiring (or 1 January) to leaving (or 31 December), inclusive."""
    start = max(date(year, 1, 1), joined) if joined else date(year, 1, 1)
    end = min(date(year, 12, 31), left) if left else date(year, 12, 31)
    return max(0, (end - start).days + 1)


def resolve_it_calc_inputs(db: Session, organization_id: int, employee, payroll_date: date,
                           period_start: Optional[date] = None, period_end: Optional[date] = None,
                           exclude_run_id: Optional[int] = None) -> dict:
    """Build build_context_from_employee(italy_inputs=...) for one Italian
    employee — facts only. Read-only: a preview never advances anything."""
    from app.modules.payroll.service import resolve_employee_statutory_profile

    profile = resolve_employee_statutory_profile(db, employee.id, organization_id, as_of=payroll_date)
    employer = (db.query(EmployerItalyProfile)
                .filter(EmployerItalyProfile.organization_id == organization_id).first())
    year = payroll_date.year
    rows = _rows(db, employee.id, tax_year_key(year))
    plan = _rows(db, employee.id, italy_content.IT_WEDGE_RECOVERY_PLAN_YEAR)
    joined = getattr(employee, "date_of_joining", None)
    left = getattr(employee, "date_of_leaving", None)
    period_start = period_start or payroll_date.replace(day=1)
    period_end = period_end or payroll_date

    inputs = {
        "italy_statutory_profile": profile,
        "italy_employer_profile": employer,
        "italy_organization_id": organization_id,
        "it_employee_id": employee.id,
        "it_ytd_taxable_prior": _wages(rows, "it_irpef"),
        "it_ytd_irpef_withheld_prior": _withheld(rows, "it_irpef"),
        "it_ytd_contributory_base_prior": _wages(rows, "it_inps_base"),
        "it_ytd_fringe_prior": _wages(rows, "it_fringe"),
        "it_ytd_wedge_paid_prior": _wages(rows, "it_wedge_paid"),
        "it_mensilita_paid_prior": int(_wages(rows, "it_mensilita")),
        "it_work_days_in_year": work_days_in_year(year, joined, left),
        # A recovery plan only ever exists because a conguaglio opened one, so
        # no plan row is a fact: nothing is being recovered.
        "it_wedge_recovery_outstanding": _wages(plan, _RECOVERY) - _withheld(plan, _RECOVERY),
        "it_wedge_recovery_instalment": _wages(plan, _RECOVERY_INST),
    }
    # §5: a determined amount is passed only when its row exists — an
    # employee's opening position is recorded explicitly (record_opening_
    # balances), never assumed to be zero (IT-008).
    for component, due_key, prior_key in (
            ("it_addreg_saldo", "it_addreg_saldo_due", "it_addreg_saldo_withheld_prior"),
            ("it_addcom_saldo", "it_addcom_saldo_due", "it_addcom_saldo_withheld_prior"),
            ("it_addcom_acconto", "it_addcom_acconto_due", "it_addcom_acconto_withheld_prior")):
        if component in rows:
            inputs[due_key] = _wages(rows, component)
            inputs[prior_key] = _withheld(rows, component)

    terminating = bool(left and period_start <= left <= period_end)
    inputs["it_is_termination_period"] = terminating
    inputs["it_is_conguaglio_period"] = terminating or period_end.month == 12

    terms = resolve_ccnl_level_terms(db, profile, payroll_date) if profile is not None else None
    if terms is not None:
        inputs["it_mensilita"] = terms.mensilita
        inputs["it_ccnl_weekly_hours"] = terms.weekly_hours
    contractual = getattr(profile, "it_contractual_weekly_hours", None) if profile is not None else None
    if terms is not None and contractual is not None and Decimal(str(contractual)) < Decimal(str(terms.weekly_hours)):
        # IT-018: hourly minimum. The hours PAID this period come from
        # approved attendance, which is not wired yet, so they stay absent
        # and the engine blocks with it_part_time_hours.
        inputs["it_is_part_time"] = True
    else:
        inputs.update(contributory_days(period_start, period_end, joined, left))
    return inputs


# ── writes (COMMIT side, called from _post_payslip_ytd) ──────────────────────
def _upsert(db: Session, employee_id: int, tax_year: str, component: str,
            wages: Decimal, withheld: Decimal, payslip_id: Optional[int]) -> None:
    row = (db.query(PayrollYtdAccumulator)
           .filter(PayrollYtdAccumulator.employee_id == employee_id,
                   PayrollYtdAccumulator.tax_year == tax_year,
                   PayrollYtdAccumulator.tax_component == component).first())
    if row is None:
        row = PayrollYtdAccumulator(employee_id=employee_id, tax_year=tax_year, tax_component=component,
                                    ytd_taxable_wages=ZERO, ytd_tax_withheld=ZERO)
        db.add(row)
    row.ytd_taxable_wages = Decimal(str(wages))
    row.ytd_tax_withheld = Decimal(str(withheld))
    row.last_updated_payslip_id = payslip_id


def post_it_payslip_ytd(db: Session, employee_id: int, result, payslip_id: Optional[int]) -> None:
    """Persist exactly the running totals the engine reported (never a
    recomputation). Absolute writes to PayrollYtdAccumulator, so the shared
    ytdPostings lifecycle records them and can reverse them if the payslip is
    deleted or corrected.

    At a year-end conguaglio the next year's determined surtax balances are
    opened as well; at termination they were withheld now, so none is opened.
    A recovery plan is advanced by what was recovered and widened by any new
    recovery the conguaglio found."""
    after = getattr(result, "it_ytd_after", None)
    if not after:
        return
    year = int(after["tax_year"])
    key = tax_year_key(year)
    for component in _YEAR_COMPONENTS:
        if component in after:
            wages, withheld = after[component]
            _upsert(db, employee_id, key, component, wages, withheld, payslip_id)
    # The TFR accrual is NOT a year-to-date total: it is posted to the TFR
    # liability ledger (payroll_it_tfr_ledger_entries) when the run is
    # committed, which is P6 work.

    if getattr(result, "it_conguaglio", False) and not _is_termination(result):
        next_key = tax_year_key(year + 1)
        _upsert(db, employee_id, next_key, "it_addreg_saldo",
                result.it_addreg_saldo_determined, ZERO, payslip_id)
        _upsert(db, employee_id, next_key, "it_addcom_saldo",
                result.it_addcom_saldo_determined, ZERO, payslip_id)
        if result.it_addcom_credit_determined:
            _upsert(db, employee_id, next_key, "it_addcom_credit",
                    result.it_addcom_credit_determined, ZERO, payslip_id)

    recovered = Decimal(str(getattr(result, "it_wedge_recovery_now", ZERO) or ZERO))
    new = Decimal(str(getattr(result, "it_wedge_recovery_new", ZERO) or ZERO))
    if recovered or new:
        plan_key = italy_content.IT_WEDGE_RECOVERY_PLAN_YEAR
        plan = _rows(db, employee_id, plan_key)
        _upsert(db, employee_id, plan_key, _RECOVERY,
                _wages(plan, _RECOVERY) + new, _withheld(plan, _RECOVERY) + recovered, payslip_id)
        _upsert(db, employee_id, plan_key, _RECOVERY_INST,
                result.it_wedge_recovery_instalment_after, ZERO, payslip_id)
    db.flush()


def _is_termination(result) -> bool:
    trace = getattr(result, "it_calculation_trace", None) or {}
    return bool(trace.get("terminationPeriod"))


def record_opening_balances(db: Session, employee_id: int, year: int, *, addreg_saldo_due,
                            addcom_saldo_due, addcom_acconto_due,
                            withheld_elsewhere: Optional[dict] = None) -> None:
    """IT-008 — an employee's §5 opening position for `year`, recorded
    explicitly (from the prior employer's CU or this employer's own history).
    Zero is a legitimate recorded value; an unrecorded one blocks payroll.
    `withheld_elsewhere` carries any part already withheld this year by a
    previous payroll, so it is never withheld twice."""
    withheld_elsewhere = withheld_elsewhere or {}
    key = tax_year_key(year)
    for component, due in (("it_addreg_saldo", addreg_saldo_due),
                           ("it_addcom_saldo", addcom_saldo_due),
                           ("it_addcom_acconto", addcom_acconto_due)):
        if due is None:
            raise ValueError(f"{component}: an opening amount must be recorded explicitly (0 if none)")
        due = Decimal(str(due))
        prior = Decimal(str(withheld_elsewhere.get(component, ZERO)))
        if due < ZERO or prior < ZERO or prior > due:
            raise ValueError(f"{component}: invalid opening amounts (due {due}, withheld {prior})")
        _upsert(db, employee_id, key, component, due, prior, None)
    db.flush()


# ── payslip snapshot ────────────────────────────────────────────────────────
def it_payslip_snapshot(result) -> "dict | None":
    """PayslipItem.it_calculation_snapshot for an Italy result (None for every
    other country): the statutory lines a report or the LUL reads, and the
    engine trace verbatim, JSON-safe."""
    trace = getattr(result, "it_calculation_trace", None)
    if trace is None:
        return None

    def s(name):
        value = getattr(result, name, None)
        return None if value is None else str(value)

    return _json_safe({
        "inps": {"employee": s("it_employee_contributions"), "employer": s("it_employer_social_security"),
                 "base": s("it_contributory_base"), "additional1pct": s("it_ivs_additional"),
                 "minimumApplied": getattr(result, "it_contributory_minimum_applied", False)},
        "irpef": {"withheld": s("it_irpef"), "refund": s("it_irpef_refund"),
                  "annualNet": s("it_irpef_annual"), "detrazione": s("it_detrazione_lavoro"),
                  "additionalDeduction": s("it_wedge_additional_deduction")},
        "wedge": {"taxFreeSum": s("it_wedge_tax_free_sum"), "recoveredNow": s("it_wedge_recovery_now")},
        "localTax": {"regionalSaldo": s("it_addreg_saldo_withheld"),
                     "municipalSaldo": s("it_addcom_saldo_withheld"),
                     "municipalAcconto": s("it_addcom_acconto_withheld"),
                     "terminationWithheld": s("it_termination_surtax_withheld")},
        "tfr": {"accrual": s("it_tfr_gross_accrual"), "inpsOffset": s("it_tfr_inps_offset"),
                "net": s("it_tfr_amount"), "destination": getattr(result, "it_tfr_destination", None)},
        "benefits": {"fringeTaxable": s("it_fringe_taxable"), "mealTaxable": s("it_meal_voucher_taxable")},
        "conguaglio": getattr(result, "it_conguaglio", False),
        "calculation": trace,
    })


def _json_safe(value):
    """Decimals as exact strings and dates as ISO text, recursively — the
    snapshot is JSON and must never lose a cent to a float."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


# ── rate map ────────────────────────────────────────────────────────────────
def italy_rate_map(rows) -> dict:
    """The engine-facing rate_map for an Italian canonical pack.

    The shared builder keys rows by component_key alone, which is right for
    every scalar parameter and WRONG for the §7 INPS matrix: one family
    (it_inps_ivs, it_inps_cigs, ...) has a row per CSC/CA scope and worker
    class, and keying by family alone keeps only the last one — every worker
    would silently get one class's rates. Matrix rows (jurisdiction_state
    "CSC_...") are keyed "<scope>|<class>|<family>" instead; italy.py finds
    them by scanning the values, never by key."""
    from app.modules.payroll.service import _normalize_engine_component_key

    out = {}
    for row in rows:
        scope = getattr(row, "jurisdiction_state", None) or ""
        if scope.startswith("CSC_"):
            out[f"{scope}|{(row.tax_regime or '').upper()}|{row.component_key}"] = row
        else:
            out[_normalize_engine_component_key(row.component_key)] = row
    return out


# ── Draft canonical content (italy_content.py -> rows) ──────────────────────
IT_PACK_ID = "IT-PAYROLL-2026"


def seed_italy_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                    status: str = "Draft"):
    """Write italy_content.py into one tax JurisdictionPack: every scalar
    parameter, every INPS matrix row (scoped CSC_<csc>[_CA_<ca>], worker class
    in tax_regime, causale in filing_status) and every IRPEF / deduction /
    wedge / local-surtax band. Draft by default — the content carries "needs
    source" figures and must pass G1 before any pack is activated (IT-003).

    Idempotent and non-destructive: a pack that has left Draft is never
    rewritten; a Draft pack's rows are replaced wholesale from the content."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == IT_PACK_ID, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{IT_PACK_ID} is {pack.status!r}, not Draft — refusing to rewrite it")
    if pack is None:
        pack = JurisdictionPack(pack_id=IT_PACK_ID, version="1.0", jurisdiction_country=_COUNTRY,
                                pack_type="tax", effective_from=effective_from)
        db.add(pack)
        db.flush()
    pack.status = status
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).delete()

    def pct(value):
        return Decimal(value) if value is not None else None

    def share(value):
        return f"{value}%" if value is not None else "—"

    order = 0
    for key, label, ee, er, flat, _source in italy_content.IT_SCALAR_CONTENT:
        order += 1
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=_COUNTRY,
            component_key=key, label=label[:100], employee_share=share(ee), employer_share=share(er),
            total=share(flat) if flat is not None else "—",
            employee_rate_pct=pct(ee), employer_rate_pct=pct(er),
            flat_amount=Decimal(flat) if flat is not None else None, sort_order=order))
    for csc, ca, worker_class, family, causale, ee, er in italy_content.IT_INPS_MATRIX:
        order += 1
        scope = f"CSC_{csc}" + (f"_CA_{ca}" if ca else "")
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=_COUNTRY,
            jurisdiction_state=scope, tax_regime=worker_class, filing_status=causale,
            component_key=family, label=f"INPS {family} {scope} {worker_class}"[:100],
            employee_share=share(ee), employer_share=share(er), total="—",
            employee_rate_pct=Decimal(ee), employer_rate_pct=Decimal(er), sort_order=order))
    for rule, table, lo, hi, rate, flat, label in (italy_content.IT_TAX_SLABS
                                                    + italy_content.IT_LOCAL_TAX_SLABS):
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=_COUNTRY,
            rule_type=rule, tax_table_number=table, min_amount=Decimal(lo),
            max_amount=Decimal(hi) if hi is not None else None, rate_pct=Decimal(rate),
            flat_amount=Decimal(flat) if flat is not None else None,
            rate_label=label[:150], tax_formula=label[:150], sort_order=order))
    db.flush()
    return pack
