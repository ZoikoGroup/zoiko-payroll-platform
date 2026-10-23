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
  MX_CFDI_TIMEZONE_UNSUPPORTED  the place of issue has a seasonal UTC offset (dates not in the sources)
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
_TZ_NAME = "Referencias del Huso Horario/Descripción del Huso Horario"
_TZ_WINTER = "Referencias del Huso Horario/Diferencia_Horaria_Invierno"
_TZ_SUMMER = "Referencias del Huso Horario/Diferencia_Horaria_Verano"


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value if value not in (None, "") else 0))


def _missing(fields: list, what: str):
    raise MXBlock("MX_CFDI_INPUT_MISSING", f"{what}: " + ", ".join(fields) + " not recorded",
                  reasons=[("MX_CFDI_INPUT_MISSING", f"{what}: {f}") for f in fields])


def local_issue_time(set_id: str, postal_code: str, issued_utc: datetime) -> datetime:
    """S4 p. 6: Fecha is the local time where the receipt is issued — the
    offset is the c_CodigoPostal row's (S30). A postal code whose winter and
    summer offsets differ is refused: the change-over dates are not in the
    saved sources."""
    from app.modules.payroll import mexico_cfdi_xml as X

    found = X._Catalogs(set_id).entry("c_CodigoPostal", postal_code, issued_utc.date())
    if found is None:
        raise MXBlock("MX_CFDI_INPUT_MISSING", "place of issue: not a c_CodigoPostal code valid today")
    attrs = found[1]
    winter, summer = attrs.get(_TZ_WINTER), attrs.get(_TZ_SUMMER)
    if winter is None or winter != summer:
        raise MXBlock("MX_CFDI_TIMEZONE_UNSUPPORTED",
                      f"the place of issue is in '{attrs.get(_TZ_NAME)}', whose UTC offset changes during the year — "
                      f"the change-over dates are not in the saved sources (S30)")
    utc = issued_utc if issued_utc.tzinfo else issued_utc.replace(tzinfo=timezone.utc)
    return (utc.astimezone(timezone.utc) + timedelta(hours=int(winter))).replace(tzinfo=None)


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
        perceptions.append({"key": c.get("code"), "satCode": code,
                            "concept": label or describe("c_TipoPercepcion", code),
                            "taxed": _d(c.get("isr_taxable")), "exempt": _d(c.get("isr_exempt"))})

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
