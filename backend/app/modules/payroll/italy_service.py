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


# ═══════════════════════════════════════════════════════════════════════════
# Employer profile, readiness and Super Admin preview (§17, §20, gates G1-G8)
#
# Nothing here computes a statutory figure: the preview runs the production
# engine, and readiness only reports which facts and content exist. Nothing
# here activates Italian payroll — the registry row stays PLANNED and the pack
# stays Draft until the release gates are evidenced.
# ═══════════════════════════════════════════════════════════════════════════
_FUND_POSITIONS = ("FIS", "CIG", "SECTOR_FUND")
_FIS_BANDS = ("UP_TO_5", "OVER_5")
_TESORERIA_STATUSES = ("OBLIGED", "NOT_OBLIGED", "TRANSFER_PRESERVED")


def latest_it_tax_pack(db: Session, pack_id: Optional[int] = None, as_of: Optional[date] = None):
    """The IT tax pack by id; otherwise the one in force on `as_of` (default
    today), else the most recent. None when no Italian pack exists."""
    from sqlalchemy import or_

    from app.core.exceptions import NotFoundException
    from app.modules.payroll.models import JurisdictionPack

    query = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == _COUNTRY,
                                             JurisdictionPack.pack_type == "tax")
    if pack_id is not None:
        pack = query.filter(JurisdictionPack.id == pack_id).first()
        if pack is None:
            raise NotFoundException("JurisdictionPack", pack_id)
        return pack
    as_of = as_of or date.today()
    in_force = (query.filter(or_(JurisdictionPack.effective_from.is_(None), JurisdictionPack.effective_from <= as_of),
                             or_(JurisdictionPack.effective_to.is_(None), JurisdictionPack.effective_to >= as_of))
                .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first())
    return in_force or query.order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first()


def _pack_rows(db: Session, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if pack is None:
        return [], []
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.organization_id.is_(None)).all()
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                     TaxSlab.organization_id.is_(None)).all()
    return rates, slabs


def _inps_scope(csc: Optional[str], ca: Optional[str]) -> Optional[str]:
    csc = (csc or "").strip().upper()
    ca = (ca or "").strip().upper()
    return (f"CSC_{csc}" + (f"_CA_{ca}" if ca else "")) if csc else None


def evaluate_employer_readiness(db: Session, profile: EmployerItalyProfile) -> tuple:
    """§17H / IT-049 — recompute the employer launch gate from facts. Never
    hand-set: the operator edits facts, this decides the status. Returns
    (status, evidence)."""
    items = []

    def add(key, label, complete, detail):
        items.append({"key": key, "label": label, "complete": bool(complete), "detail": detail})

    identity = bool(profile.matricola_inps and profile.csc_code)
    add("inps_identity", "INPS matricola and CSC captured (§17B)", identity,
        "Captured." if identity else "Matricola INPS and CSC are both required.")
    scope = _inps_scope(profile.csc_code, profile.ca_code)
    pack = latest_it_tax_pack(db)
    rates, _slabs = _pack_rows(db, pack)
    covered = scope is not None and any((r.jurisdiction_state or "") == scope and r.component_key == "it_inps_ivs"
                                        for r in rates)
    add("inps_classification", "INPS classification matrix covers this employer (IT-002)", covered,
        f"{scope} has IVS rows in {pack.pack_id} v{pack.version}." if covered else
        f"No IVS rows for {scope or 'an uncaptured CSC'} in the Italian pack — payroll would block.")
    status = profile.fund_status if isinstance(profile.fund_status, dict) else {}
    fund = (status.get("fund") or "").upper()
    fund_ok = fund == "CIG" or (fund == "FIS" and (status.get("fisBand") or "").upper() in _FIS_BANDS)
    add("fund_status", "Income-support fund position (FIS / CIG) (§7, IT-020)", fund_ok,
        "Captured." if fund_ok else ("Sector bilateral funds are not supported yet." if fund == "SECTOR_FUND"
                                     else "Record FIS with its size band, or CIG."))
    add("headcount", "Prior-year average headcount for the Fondo Tesoreria rule (IT-040)",
        profile.prior_year_avg_headcount is not None,
        f"{profile.prior_year_avg_headcount} employees." if profile.prior_year_avg_headcount is not None
        else "Required to decide where unallocated TFR goes.")
    agreement = None
    if profile.cnel_code:
        agreement = (db.query(CollectiveAgreement)
                     .filter(CollectiveAgreement.jurisdiction_country == _COUNTRY,
                             CollectiveAgreement.agreement_code == profile.cnel_code,
                             CollectiveAgreement.status == "Active").first())
    add("ccnl", "Reference CCNL configured and Active (§9)", agreement is not None,
        f"{profile.cnel_code} is Active." if agreement is not None else
        ("No Active agreement for " + profile.cnel_code if profile.cnel_code else "No CNEL code captured."))
    models_ok = bool(profile.f24_operating_model and profile.lul_method)
    add("operating_models", "F24 and LUL operating models chosen (§17F/G)", models_ok,
        "Chosen." if models_ok else "Choose both operating models.")
    # IT-022 facts live on EmployerTaxProfile (component_code IT_INAIL_<voce>,
    # agency_account_id = PAT, employer_rate_pct = tasso). Recording them is
    # the employer's part; the INAIL cost CALCULATION is a platform gate (G3)
    # reported by get_it_readiness, not an employer fact.
    from app.modules.payroll.models import EmployerTaxProfile

    today = date.today()
    inail_rows = [r for r in db.query(EmployerTaxProfile).filter(
        EmployerTaxProfile.organization_id == profile.organization_id,
        EmployerTaxProfile.component_code.like(f"{italy_content.IT_INAIL_COMPONENT_PREFIX}%")).all()
        if r.effective_from <= today and (r.effective_to is None or r.effective_to >= today)]
    inail_ok = bool(inail_rows) and all(r.agency_account_id and r.employer_rate_pct is not None for r in inail_rows)
    add("inail", "INAIL PAT and applicable rate recorded per voce di tariffa (§8, IT-022)", inail_ok,
        f"{len(inail_rows)} voce(i) recorded; INAIL cost is not calculated yet (platform gate G3)." if inail_ok else
        ("A recorded voce is missing its PAT or rate." if inail_rows else
         "Record each voce di tariffa with its PAT and tasso applicabile."))
    ready = all(i["complete"] for i in items)
    return ("READY" if ready else "NOT_READY"), {"items": items, "evaluatedAt": date.today().isoformat()}


def get_employer_profile(db: Session, organization_id: int) -> Optional[EmployerItalyProfile]:
    return (db.query(EmployerItalyProfile)
            .filter(EmployerItalyProfile.organization_id == organization_id).first())


def upsert_employer_profile(db: Session, organization_id: int, data, actor_id: Optional[int]) -> EmployerItalyProfile:
    """Create or edit the org's Italy employer facts, then RECOMPUTE readiness
    (readiness_status is never written from the request)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.service import record_tax_audit

    errors = []
    fund_status = data.fundStatus
    if fund_status is not None:
        fund = (fund_status.get("fund") or "").upper()
        if fund not in _FUND_POSITIONS:
            errors.append(f"fundStatus.fund must be one of {', '.join(_FUND_POSITIONS)}.")
        band = (fund_status.get("fisBand") or "").upper() or None
        if fund == "FIS" and band not in _FIS_BANDS:
            errors.append(f"An FIS employer needs fundStatus.fisBand: {' or '.join(_FIS_BANDS)}.")
        fund_status = {"fund": fund, "fisBand": band if fund == "FIS" else None}
    if data.priorYearAvgHeadcount is not None and data.priorYearAvgHeadcount < 0:
        errors.append("priorYearAvgHeadcount must not be negative.")
    if data.tesoreriaStatus and data.tesoreriaStatus.strip().upper() not in _TESORERIA_STATUSES:
        errors.append(f"tesoreriaStatus must be one of {', '.join(_TESORERIA_STATUSES)}.")
    for field, value in (("cscCode", data.cscCode), ("caCode", data.caCode)):
        if value and not value.strip().isalnum():
            errors.append(f"{field} must be letters and digits only.")
    if errors:
        raise BadRequestException("; ".join(errors))

    profile = get_employer_profile(db, organization_id)
    old = None
    if profile is None:
        profile = EmployerItalyProfile(organization_id=organization_id)
        db.add(profile)
    else:
        old = {"readinessStatus": profile.readiness_status, "cscCode": profile.csc_code,
               "caCode": profile.ca_code, "fundStatus": profile.fund_status}

    def code(value):
        return (value or "").strip().upper() or None

    def text(value):
        return (value or "").strip() or None

    profile.matricola_inps = text(data.matricolaInps)
    profile.csc_code = code(data.cscCode)
    profile.ca_code = code(data.caCode)
    profile.ateco_code = text(data.atecoCode)
    profile.inps_office = text(data.inpsOffice)
    profile.cnel_code = code(data.cnelCode)
    profile.fund_status = fund_status
    profile.prior_year_avg_headcount = data.priorYearAvgHeadcount
    profile.tesoreria_status = code(data.tesoreriaStatus)
    profile.f24_operating_model = code(data.f24OperatingModel)
    profile.lul_method = code(data.lulMethod)
    db.flush()
    profile.readiness_status, profile.readiness_evidence = evaluate_employer_readiness(db, profile)
    db.commit()
    db.refresh(profile)
    record_tax_audit(db, actor_id=actor_id, action="update" if old else "create",
                     entity_type="italy_employer_profile", entity_id=profile.id,
                     legal_reference="ZP-IT-ENG-001 §17", old_value=old,
                     new_value={"readinessStatus": profile.readiness_status, "cscCode": profile.csc_code,
                                "caCode": profile.ca_code, "fundStatus": profile.fund_status})
    return profile


def get_it_readiness(db: Session, pack_id: Optional[int] = None) -> dict:
    """Super Admin release gates (spec §27 G1-G8) for one Italian tax pack —
    read-only. Gates that depend on work outside this platform stay
    incomplete until evidenced: Italy never becomes ready because its content
    merely exists."""
    from app.modules.payroll.engine import fallback_registry
    from app.modules.payroll.models import ItalyF24Causale, SourceArtifact, TestCertificationRun

    pack = latest_it_tax_pack(db, pack_id)
    items = []

    def add(key, label, complete, detail, required=True):
        items.append({"key": key, "label": label, "required": required, "complete": bool(complete),
                      "detail": detail})

    if pack is None:
        add("statutory_pack", "Italian statutory tax pack exists", False,
            "No IT tax pack — run scripts/seed_italy_canonical_pack.py.")
        return {"packId": None, "packVersion": None, "packStatus": None, "ready": False, "items": items,
                "blockers": ["No Italian tax pack exists."]}

    rates, slabs = _pack_rows(db, pack)
    rate_keys = {r.component_key for r in rates if not (r.jurisdiction_state or "").startswith("CSC_")}
    rule_types = {s.rule_type for s in slabs}
    tables = {s.tax_table_number for s in slabs}

    source = (db.query(SourceArtifact).filter(SourceArtifact.id == pack.source_document_id).first()
              if pack.source_document_id else None)
    add("source_evidence", "Primary-source evidence linked to the pack (IT-003)", source is not None,
        source.title if source else "Link a Source Evidence artifact.")
    reviewed = bool(source and source.reviewer_approved_at)
    add("statutory_review", "G1 — IRPEF, deductions, wedge and local-tax content independently validated",
        reviewed, "Reviewed." if reviewed else "Awaiting independent Italian payroll review.")

    required = [e["resolverKey"] for e in fallback_registry._ENGINE_CONSTANT_REGISTRY
                if e["country"] == _COUNTRY and e.get("required", True)]
    missing = sorted(k for k in required if k not in rate_keys)
    add("parameters", "Scalar parameters configured (thresholds, TFR, FIS, floors)", not missing,
        "Missing: " + ", ".join(missing) if missing else f"All {len(required)} required parameters configured.")
    matrix_scopes = sorted({r.jurisdiction_state for r in rates
                            if (r.jurisdiction_state or "").startswith("CSC_") and r.component_key == "it_inps_ivs"})
    add("inps_matrix", "INPS classification matrix from the INPS catalogs (IT-002, IT-043)", bool(matrix_scopes),
        (f"IVS rows for {', '.join(matrix_scopes)}" if matrix_scopes else "No IVS rows.")
        + " — codes are Draft placeholders until replaced from the INPS catalog.")
    needed_rules = (italy_content.IT_IRPEF_BRACKET_RULE, italy_content.IT_DETR_FIXED_RULE,
                    italy_content.IT_DETR_TAPER_RULE, italy_content.IT_ADDL_FIXED_RULE,
                    italy_content.IT_ADDL_TAPER_RULE, italy_content.IT_WEDGE_SUM_RULE)
    absent = [r for r in needed_rules if r not in rule_types]
    add("tax_tables", "IRPEF brackets, detrazione, wedge sum and additional deduction (§3/§4)", not absent,
        "Missing: " + ", ".join(absent) if absent else "All national tax tables present.")
    uncovered = [name for cadastral, name, region in italy_content.IT_LAUNCH_COMMUNI
                 if f"{italy_content.REGION_TABLE_PREFIX}{region}" not in tables
                 or f"{italy_content.COMUNE_TABLE_PREFIX}{cadastral}" not in tables]
    add("local_tax", "Regional and municipal surtax for every launch commune (IT-012, D4)", not uncovered,
        "No MEF content for: " + ", ".join(uncovered) if uncovered else "All launch communes covered.")
    placeholders = sum(1 for s in slabs if "needs" in (s.rate_label or "").lower())
    add("no_placeholders", "No 'needs source' placeholder content left", placeholders == 0,
        f"{placeholders} band(s) still marked as needing a source." if placeholders else "None.")
    latest_run = (db.query(TestCertificationRun).filter(TestCertificationRun.jurisdiction_country == _COUNTRY)
                  .order_by(TestCertificationRun.run_at.desc(), TestCertificationRun.id.desc()).first())
    add("certification", "Golden-vector certification PASS", latest_run is not None and latest_run.status == "PASS",
        f"Latest run #{latest_run.id}: {latest_run.status}" if latest_run else
        "No IT certification run — the golden fixtures run in the test suite only so far.")
    add("approval", "Distinct approver recorded (four-eyes)", pack.approved_by_id is not None,
        "Approved." if pack.approved_by_id else "Not yet approved by a distinct Super Admin.")
    add("inail", "G3 — INAIL PAT rates and employer-cost model (§8)", False, "Not built.")
    # F24 and UniEmens were one gate saying "file generation is not built". That
    # conflated two unrelated states and, once 3A landed, became false in both
    # directions: F24 derivation IS built and tested, UniEmens genuinely is not.
    # A gate that misreports a delivered capability is worse than no gate — it
    # trains a reviewer to dismiss the whole checklist. They are now separate.
    add("f24_lines", "F24 line derivation from committed payroll (IT-046, IT-047)", True,
        "Built and covered by tests/test_italy_f24_liability.py.")
    approved_causali = (db.query(ItalyF24Causale)
                        .filter(ItalyF24Causale.status == "Approved")
                        .count())
    add("f24_causale_catalog", "F24 causale catalog populated from the Agenzia delle Entrate catalog (IT-043)",
        approved_causali > 0,
        (f"{approved_causali} approved causale(s) recorded."
         if approved_causali else
         "Empty by design. IT-043 forbids inventing causali, so build_italy_f24_lines "
         "refuses rather than emitting guessed codes; no F24 can be produced until "
         "real codes are loaded from the Agenzia catalog."))
    add("lul", "LUL registration ledger: sequence, corrections, retention (IT-058/IT-059/IT-060)", True,
        "Built and covered by tests/test_italy_lul_ledger.py. event_kind is recorded "
        "unvalidated until the official S10 vocabulary is available.")
    add("uniemens", "UniEmens transmission from committed payroll (IT-044)", False,
        "Not built. The filing outbox exists, but file generation is blocked on the "
        "INPS v4.32.0 technical spec and annex v4.32.3, which are not published.")
    add("parallel_payroll", "Two reconciled parallel payroll cycles plus termination and conguaglio (§27)", False,
        "Evidence required from the implementation team.")
    blockers = [f"{i['label']}: {i['detail']}" for i in items if i["required"] and not i["complete"]]
    return {"packId": pack.id, "packVersion": pack.version, "packStatus": pack.status, "ready": not blockers,
            "items": items, "blockers": blockers}


def preview_italy_calculation(db: Session, data) -> dict:
    """Read-only Super Admin simulation against ONE Italian pack: the SAME
    production engine a payroll run uses, with every worker and employer fact
    supplied inline. Writes nothing; a blocked calculation returns the
    engine's own reason, never a figure."""
    from types import SimpleNamespace

    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.service import _sg_rows_in_force

    pack = latest_it_tax_pack(db, data.jurisdictionPackId, as_of=data.payDate)
    if pack is None:
        raise BadRequestException("No Italian tax pack exists — run the Italy seed first.")
    rates, slabs = _pack_rows(db, pack)
    rates = _sg_rows_in_force(rates, data.payDate)
    slabs = _sg_rows_in_force(slabs, data.payDate)
    profile = SimpleNamespace(
        it_worker_class=data.workerClass, it_contract_type=data.contractType,
        it_cigs_applies=data.cigsApplies, it_contributory_cap_cohort=data.capCohort,
        it_tfr_destination=data.tfrDestination, it_pension_fund=data.pensionFund,
        it_tax_domicile_region=data.taxDomicileRegion, it_tax_domicile_comune=data.taxDomicileComune,
        it_fringe_child_declared=data.fringeChildDeclared, it_cnel_code=None, it_cnel_level=None,
        it_contractual_weekly_hours=None, it_termination_reason=None,
    )
    employer = SimpleNamespace(csc_code=data.cscCode, ca_code=data.caCode,
                               fund_status={"fund": data.fund, "fisBand": data.fisBand},
                               prior_year_avg_headcount=data.priorYearAvgHeadcount)
    inputs = {
        "italy_statutory_profile": profile, "italy_employer_profile": employer, "italy_organization_id": None,
        "it_ytd_taxable_prior": data.ytdTaxablePrior, "it_ytd_irpef_withheld_prior": data.ytdIrpefWithheldPrior,
        "it_ytd_contributory_base_prior": data.ytdContributoryBasePrior,
        "it_mensilita_paid_prior": data.mensilitaPaidPrior, "it_mensilita": data.mensilita,
        "it_work_days_in_year": data.workDaysInYear,
        "it_ytd_fringe_prior": data.ytdFringePrior, "it_ytd_wedge_paid_prior": data.ytdWedgePaidPrior,
        "it_wedge_recovery_outstanding": data.wedgeRecoveryOutstanding,
        "it_wedge_recovery_instalment": data.wedgeRecoveryInstalment,
        # A preview is one ordinary full month: no termination, no conguaglio.
        "it_contributory_full_month": True,
        "it_is_conguaglio_period": False, "it_is_termination_period": False,
    }
    # §5: a determined surtax amount is passed only when the operator supplies
    # it — exactly as a real run passes it only when its ledger row exists.
    for key, value in (("it_addreg_saldo_due", data.addregSaldoDue),
                       ("it_addcom_saldo_due", data.addcomSaldoDue),
                       ("it_addcom_acconto_due", data.addcomAccontoDue)):
        if value is not None:
            inputs[key] = value
            inputs[key.replace("_due", "_withheld_prior")] = ZERO
    ctx = PayrollContext(gross=data.gross, basic=data.gross, country=_COUNTRY, pay_frequency="Monthly",
                         pay_date=data.payDate, rate_map=italy_rate_map(rates), slabs=slabs, **inputs)
    base = {"pack": {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status},
            "payDate": data.payDate.isoformat(), "readOnly": True}
    try:
        result = calculate_payroll(ctx, "standard")
    except MissingComplianceConfigurationError as exc:
        return {**base, "blocked": True, "blockedKey": exc.key,
                "blockedReason": getattr(exc, "reason", None) or str(exc)}
    return {**base, "blocked": False,
            "result": {"gross": str(result.gross), "totalDeductions": str(result.total_deductions),
                       "netPay": str(result.net_pay)},
            "italy": it_payslip_snapshot(result)}
