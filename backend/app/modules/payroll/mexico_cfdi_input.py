"""
modules/payroll/mexico_cfdi_input.py
------------------------------------
Assembles one payslip's `document_input` for the CFDI builder (ZP-MX-ENG-001
Phase 11b, MEXICO_PHASE_11_PLAN.md §4.4) from the committed result, the
employer version and IMSS registration in force, the employee's statutory
profile and the release's approved system-concept mappings.

MX-061: the employee's RFC / CURP / NSS are read from `compliance_fields` into
this in-memory structure only; nothing here stores, logs or returns them, and
no message names a value.

What it refuses (each with its own code):
  MX_CFDI_SCHEMA_SET_UNUSABLE   the release was not loaded from a verified pinned set
  MX_CFDI_INPUT_MISSING         a field the receipt needs is not recorded (named, never its value)
  MX_CFDI_CONCEPT_UNMAPPED      a non-zero engine amount without an APPROVED SAT-code mapping
  MX_CFDI_TIMEZONE_RULE_INVALID the place of issue's time-zone row is unreadable or inconsistent (S30)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
# Run types paid as an extraordinary payroll (S4 p. 20: separation payments,
# aguinaldo and other non-periodic concepts).
EXTRAORDINARY_RUN_TYPES = ("AGUINALDO", "PTU", "FINIQUITO")
# Engine kinds whose SAT code comes from a system-concept mapping, not from an
# earning classification.
SPECIAL_KIND_CONCEPTS = ("AGUINALDO", "VACATION_PREMIUM", "VACATION_PAYOUT", "PTU", "SEPARATION_SENIORITY_PREMIUM",
                         "SEPARATION_PAYMENT", "SEPARATION_INDEMNITY")
# Where SalarioDiarioIntegrado (S4 p. 40, LFT Art. 84) comes from. The engine
# computes the IMSS SBC (LSS Art. 27), which the guide treats as a different
# field (SalarioBaseCotApor, S4 p. 39). Choosing the source is a G1 decision;
# until it is recorded here, a receipt that needs it is refused.
SDI_SOURCE: Optional[str] = None
_TZ = "Referencias del Huso Horario"


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value if value not in (None, "") else 0))


def _missing(fields: list, what: str):
    raise MXBlock("MX_CFDI_INPUT_MISSING", f"{what}: " + ", ".join(fields) + " not recorded",
                  reasons=[("MX_CFDI_INPUT_MISSING", f"{what}: {f}") for f in fields])


_MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                        "septiembre", "octubre", "noviembre", "diciembre"), 1)}
_ORDINALS = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "último": -1,
             "ultimo": -1}
_WEEKDAYS = {d: i for i, d in enumerate(("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"))}


def _tz(attrs: dict, field: str):
    return attrs.get(f"{_TZ}/{field}")


def _nth_weekday(year: int, month: int, phrase: str):
    """'Segundo domingo' of a month -> that date (S30 c_CodigoPostal wording)."""
    import calendar
    from datetime import date as _date

    words = str(phrase or "").strip().lower().split()
    if len(words) != 2 or words[0] not in _ORDINALS or words[1] not in _WEEKDAYS:
        raise MXBlock("MX_CFDI_TIMEZONE_RULE_INVALID", "the place of issue's change-over day is not readable (S30)")
    nth, weekday = _ORDINALS[words[0]], _WEEKDAYS[words[1]]
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if _date(year, month, d).weekday() == weekday]
    return _date(year, month, days[nth - 1] if nth > 0 else days[-1])


def _change_over(attrs: dict, season: str, year: int, offset: int) -> datetime:
    """The UTC instant a season starts. S30 gives month, day and hour; the hour
    is read as the local clock just before the change (standard time when
    summer starts, summer time when it ends)."""
    month = _MONTHS.get(str(_tz(attrs, f"Mes_Inicio_Horario_{season}") or "").strip().lower())
    hour = str(_tz(attrs, f"Día_Inicio_Horario_{season} #2") or "")
    if not month or len(hour.split(":")) != 2:
        raise MXBlock("MX_CFDI_TIMEZONE_RULE_INVALID", "the place of issue's change-over rule is not readable (S30)")
    day = _nth_weekday(year, month, _tz(attrs, f"Día_Inicio_Horario_{season}"))
    hh, mm = (int(x) for x in hour.split(":"))
    local = datetime(day.year, day.month, day.day, hh, mm)
    return local - timedelta(hours=offset)


def local_issue_time(set_id: str, postal_code: str, issued_utc: datetime) -> datetime:
    """S4 p. 6: Fecha is the local time where the receipt is issued, from the
    place of issue's c_CodigoPostal row (S30): its winter and summer offsets
    and, where it observes summer time, the month / day / hour each season
    starts. A row whose summer offset is not one hour ahead of its winter
    offset is refused as inconsistent (MX_CFDI_TIMEZONE_RULE_INVALID)."""
    from app.modules.payroll import mexico_cfdi_xml as X

    utc = issued_utc if issued_utc.tzinfo else issued_utc.replace(tzinfo=timezone.utc)
    utc = utc.astimezone(timezone.utc).replace(tzinfo=None)
    found = X._Catalogs(set_id).entry("c_CodigoPostal", postal_code, utc.date())
    if found is None:
        raise MXBlock("MX_CFDI_INPUT_MISSING", "place of issue: not a c_CodigoPostal code valid today")
    attrs = found[1]
    winter, summer = _tz(attrs, "Diferencia_Horaria_Invierno"), _tz(attrs, "Diferencia_Horaria_Verano")
    if winter is None or summer is None:
        raise MXBlock("MX_CFDI_TIMEZONE_RULE_INVALID", "the place of issue has no UTC offset (S30)")
    winter, summer = int(winter), int(summer)
    if winter == summer and not _tz(attrs, "Mes_Inicio_Horario_Verano"):
        return utc + timedelta(hours=winter)
    if summer != winter + 1:
        raise MXBlock("MX_CFDI_TIMEZONE_RULE_INVALID",
                      f"the place of issue's c_CodigoPostal row gives a summer offset ({summer}) that is not one hour "
                      f"ahead of its winter offset ({winter}) — inconsistent in the SAT catalog (S30); reported for G1")
    starts = _change_over(attrs, "Verano", utc.year, winter)
    ends = _change_over(attrs, "Invierno", utc.year, summer)
    in_summer = starts <= utc < ends if starts < ends else not (ends <= utc < starts)
    return utc + timedelta(hours=summer if in_summer else winter)


def sat_state(set_id: str, internal_code: str, on) -> Optional[str]:
    """The c_Estado code for the employee's work state: the same code where SAT
    uses it, otherwise the c_Estado row with the same name (S30)."""
    from app.modules.payroll import mexico_cfdi_schema
    from app.modules.payroll.engine.countries.mexico_content import MX_FEDERAL_ENTITIES

    rows = {e[0]: e[1] for e in mexico_cfdi_schema.catalogs(set_id)["c_Estado"]["entries"]
            if (e[4] or {}).get("c_Pais") == "MEX"}
    if internal_code in rows:
        return internal_code
    name = dict(MX_FEDERAL_ENTITIES).get(internal_code)
    matches = [code for code, label in rows.items() if label == name]
    return matches[0] if len(matches) == 1 else None


def _overtime_detail(set_id: str, result: dict, on) -> dict:
    """HorasExtra (S4 pp. 51–53) from the approved weeks: the days are the
    distinct dates recorded on the approved hours. A week with triple-rate hours
    is refused — dates alone do not tell which days those hours fell on."""
    from decimal import ROUND_HALF_UP

    from app.modules.payroll import mexico_cfdi_xml as X

    weeks = ((result.get("labor") or {}).get("overtime")) or []
    if not weeks:
        return {"overtimeRefusal": "the result has no approved overtime weeks"}
    if any(not w.get("dates") for w in weeks):
        return {"overtimeRefusal": "the dates on which the overtime was worked are not recorded on every approved week"}
    if any(_d(w.get("second_tier_hours")) > 0 for w in weeks):
        return {"overtimeRefusal": "a week has triple-rate hours, and the recorded dates do not tell which days they "
                                   "fell on (S4 p. 51 counts days per hour type)"}
    found = [code for code, rows in X._Catalogs(set_id).index.get("c_TipoHoras", {}).items()
             if any(r[2] == X.OVERTIME_TYPE_DOUBLE for r in rows)]
    if len(found) != 1:
        return {"overtimeRefusal": "c_TipoHoras has no single code for double-rate hours (S28)"}
    days = {d for w in weeks for d in w["dates"]}
    hours = sum((_d(w.get("first_tier_hours")) for w in weeks), _ZERO)
    amount = sum((_d(w.get("first_tier_amount", w.get("amount"))) for w in weeks), _ZERO)
    return {"overtime": [{"days": len(days), "type": found[0],
                          "hours": int(hours.quantize(Decimal("1"), ROUND_HALF_UP)),     # S4 p. 52: rounded
                          "amount": amount.quantize(Decimal("0.01"), ROUND_HALF_UP)}]}


def _concept_lines(db: Session, release_id: int, set_id: str, result: dict, on):
    """(perceptions, deductions, other payments, unmapped keys) from the committed result."""
    from app.modules.payroll import mexico_cfdi_catalog_service as cat
    from app.modules.payroll import mexico_cfdi_xml as X
    from app.modules.payroll.models import PayrollMxEarningClassification

    catalogs = X._Catalogs(set_id)
    unmapped = []

    def mapped(key):
        row = cat.approved_concept(db, release_id, key)
        if row is None:
            unmapped.append(key)
        return row

    def describe(catalog, code):
        found = catalogs.entry(catalog, code, on)
        return found[0] if found else code

    perceptions = []
    for c in result.get("concepts") or []:
        gross = _d(c.get("gross"))
        if not gross:
            continue
        kind = c.get("kind")
        if kind in SPECIAL_KIND_CONCEPTS:
            row = mapped(kind)
            if row is None:
                continue
            perceptions.append({"key": row.sat_code, "satCode": row.sat_code,
                                "concept": describe("c_TipoPercepcion", row.sat_code),
                                "taxed": _d(c.get("isr_taxable")), "exempt": _d(c.get("isr_exempt"))})
            continue
        code = c.get("cfdi_concept_code")
        if not code:
            unmapped.append(f"earning {c.get('code')} (its classification has no SAT code)")
            continue
        label = None
        if c.get("classification_id"):
            cls = db.get(PayrollMxEarningClassification, c["classification_id"])
            label = cls.label if cls else None
        line = {"key": c.get("code"), "satCode": code, "concept": label or describe("c_TipoPercepcion", code),
                "taxed": _d(c.get("isr_taxable")), "exempt": _d(c.get("isr_exempt"))}
        if c.get("kind") == "OVERTIME":
            line.update(_overtime_detail(set_id, result, on))
        perceptions.append(line)

    deductions, others = [], []
    annual = result.get("annual_adjustment") or {}
    period_isr = _d(annual.get("period_withheld")) if annual else _d(result.get("isr_withheld"))
    change = _d(annual.get("change")) if annual else _ZERO
    amounts = [("ISR_WITHHELD", period_isr, "DEDUCCION"), ("IMSS_EMPLOYEE", _d(result.get("imss_employee")), "DEDUCCION"),
               ("INFONAVIT_CREDIT", _d(result.get("infonavit_credit")), "DEDUCCION"),
               ("ANNUAL_ADJUSTMENT_CHARGE", change if change > 0 else _ZERO, "DEDUCCION"),
               ("ANNUAL_ADJUSTMENT_REFUND", -change if change < 0 else _ZERO, "OTRO_PAGO"),
               ("SUBSIDY_APPLIED", _d((result.get("subsidy") or {}).get("applied")), "OTRO_PAGO")]
    for key, amount, node in amounts:
        if not amount:
            continue
        row = mapped(key)
        if row is None:
            continue
        if row.node_type != node:
            unmapped.append(f"{key} (mapped as {row.node_type}, needs {node})")
            continue
        catalog = "c_TipoDeduccion" if node == "DEDUCCION" else "c_TipoOtroPago"
        line = {"key": row.sat_code, "satCode": row.sat_code, "concept": describe(catalog, row.sat_code),
                "amount": amount}
        (deductions if node == "DEDUCCION" else others).append(line)
    return perceptions, deductions, others, unmapped


def document_input(db: Session, run, item, release, base: dict) -> dict:
    """`base` (payslip id, folio, issuedAtUtc, replacesUuid, ...) + everything
    the receipt needs. Refuses (MXBlock) instead of guessing a value."""
    from app.modules.payroll import mexico_cfdi_catalog_service, mexico_employee_service, mexico_employer_service
    from app.modules.payroll.models import PayrollEmployee, PayrollMxImssRegistration

    set_id = mexico_cfdi_catalog_service.release_set_id(release)
    if set_id is None:
        raise MXBlock("MX_CFDI_SCHEMA_SET_UNUSABLE",
                      "the Active CFDI release was not loaded from a verified pinned SAT set (Phase 11a)")
    result = (item.mx_calculation_snapshot or {}).get("result") or {}
    on = run.pay_date
    employee = db.get(PayrollEmployee, item.employee_id)
    prof = mexico_employee_service._profile_on(db, item.employee_id, on)
    if employee is None or prof is None:
        _missing(["statutory profile"], "employee")
    reg = db.get(PayrollMxImssRegistration, prof.mx_imss_registration_id) if prof.mx_imss_registration_id else None
    version = mexico_employer_service.version_in_force(db, reg.employer_profile_id, on) if reg else None
    if version is None:
        _missing(["employer profile / IMSS registration"], "employer")
    ids = employee.compliance_fields or {}
    receiver = {
        "rfc": (ids.get("rfc") or "").strip().upper() or None, "curp": (ids.get("curp") or "").strip().upper() or None,
        "nss": (ids.get("nss") or "").strip() or None, "name": (employee.name or "").strip() or None,
        "fiscalPostalCode": prof.mx_fiscal_postal_code, "fiscalRegime": prof.mx_receiver_fiscal_regime,
        "employeeNumber": employee.employee_code, "contractType": prof.mx_contract_type_code,
        "regimeType": prof.mx_regime_type_code, "workdayType": prof.mx_workday_type_code,
        "riskClass": prof.mx_job_risk_code, "payFrequency": prof.mx_pay_frequency_code,
        "state": sat_state(set_id, (prof.mx_work_state or "").upper(), on) if prof.mx_work_state else None,
        "seniorityDate": prof.mx_seniority_date.isoformat() if prof.mx_seniority_date else None,
        "sdi": None,
    }
    needed = ["rfc", "curp", "name", "fiscalPostalCode", "employeeNumber", "contractType", "regimeType", "payFrequency",
              "state"]
    if reg is not None:
        needed += ["nss", "seniorityDate", "riskClass"]
    missing = [f for f in needed if not receiver.get(f)]
    if missing:
        _missing(missing, "employee")
    if reg is not None:
        if SDI_SOURCE is None:
            raise MXBlock("MX_CFDI_INPUT_MISSING",
                          "SalarioDiarioIntegrado (S4 p. 40, LFT Art. 84) has no recorded source — the engine computes "
                          "the IMSS SBC (S4 p. 39 treats it as SalarioBaseCotApor); a G1 decision is needed")
        receiver["sdi"] = SDI_SOURCE(result, prof) if callable(SDI_SOURCE) else None
        if not receiver["sdi"]:
            _missing(["SalarioDiarioIntegrado"], "employee")
    perceptions, deductions, others, unmapped = _concept_lines(db, release.id, set_id, result, on)
    if unmapped:
        raise MXBlock("MX_CFDI_CONCEPT_UNMAPPED",
                      "no APPROVED SAT-code mapping for: " + ", ".join(unmapped) + " (CFDI catalogs tab — a "
                      "system concept, or the earning classification's code)",
                      reasons=[("MX_CFDI_CONCEPT_UNMAPPED", u) for u in unmapped])
    issued_utc = base.get("issuedAtUtc") or datetime.now(timezone.utc)
    annual = result.get("annual_adjustment") or {}
    change = _d(annual.get("change")) if annual else _ZERO
    # The committed result's own totals, independent of the lines above
    # (MX_CFDI_TOTALS_MISMATCH when the receipt would differ).
    expected = {"perceptions": _d(result.get("gross")),
                "deductions": _d(result.get("isr_withheld")) + (-change if change < 0 else _ZERO)
                + _d(result.get("employee_total")),
                "otherPayments": _d((result.get("subsidy") or {}).get("applied")) + (-change if change < 0 else _ZERO)}
    return {**base, "setId": set_id,
            "issuedAt": local_issue_time(set_id, version.place_of_issue_postal_code, issued_utc).isoformat(),
            "placeOfIssue": version.place_of_issue_postal_code,
            "issuer": {"rfc": version.rfc, "name": version.legal_name, "regime": version.fiscal_regime_code,
                       "registroPatronal": reg.registro_patronal if reg else None, "curp": None},
            "receiver": receiver,
            "payroll": {"payDate": on.isoformat(), "periodStart": run.period_start.isoformat(),
                        "periodEnd": run.period_end.isoformat(), "daysPaid": result.get("days_paid"),
                        "extraordinary": (run.mx_run_type or "ORDINARY") in EXTRAORDINARY_RUN_TYPES},
            "perceptions": perceptions, "deductions": deductions, "otherPayments": others,
            "expectedTotals": expected}
