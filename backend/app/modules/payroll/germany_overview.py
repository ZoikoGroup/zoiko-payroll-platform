"""Germany Super Admin page: read-only views for the shared pack layout.

Two read-only views, built only from what already exists:

* the "Contributions" rows (germany_contribution_rows): the German
  statutory registries (health funds, contribution ceilings, PV
  configuration, Minijob/Midijob parameters) shaped like the shared
  ContributionRate rows, plus one row per fallback constant the engine reads
  from code (hardcoded_defaults.py). A constant's value is read from the
  constant itself, never retyped here.
* the section 32a EStG wage-tax tariff (germany_wage_tax_tariff): the zones
  of every version in engine/jurisdictions/germany/tax.py's _TARIFF_VERSIONS,
  read from that registry. It is an internal reference tariff, NOT
  BMF-certified; no PAP executor exists (pap/core.resolve_pap_executor).

Nothing here writes, computes payroll or changes what the engine reads.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

ENGINE_DEFAULTS_FILE = "backend/app/modules/payroll/hardcoded_defaults.py"
TARIFF_FILE = "backend/app/modules/payroll/engine/jurisdictions/germany/tax.py"
CHURCH_TAX_FILE = "backend/app/modules/payroll/engine/jurisdictions/germany/pap/core.py"

ENGINE_STATUS = "Built into engine, no data row"
UNCERTIFIED_TARIFF_WARNING = (
    "German wage tax is currently calculated by an internal reference tariff that is not "
    "BMF-certified. No PAP release is configured."
)

SECTIONS = [
    ("health", "Health insurance (GKV), health funds and employer levies"),
    ("pension", "Pension (RV), unemployment (ALV) and care insurance (PV)"),
    ("ceilings", "Contribution ceilings (Beitragsbemessungsgrenzen)"),
    ("minijob", "Minijob / Midijob parameters"),
]

# The fallback constants the Germany engine imports (engine/countries/germany.py),
# with where each one goes: (section, key, label, employee constant, employer
# constant, flat constant, factor constant, what overrides it, note).
# Only constant NAMES are listed; every value is read from hardcoded_defaults.
_ENGINE_CONSTANTS = [
    ("health", "gkv_general", "GKV general rate", "_DE_GKV_GENERAL_EMPLOYEE_RATE", "_DE_GKV_GENERAL_EMPLOYER_RATE",
     None, None, ("pack", "gkv_general"), None),
    ("health", "employer_insolvency_levy_rate", "Insolvency levy (U3)", None, "_DE_INSOLVENCY_LEVY_RATE",
     None, None, ("parameter", "employer_insolvency_levy_rate"), None),
    ("pension", "rv_pension", "Pension insurance (RV)", "_DE_RV_EMPLOYEE_RATE", "_DE_RV_EMPLOYER_RATE",
     None, None, ("pack", "rv_pension"), None),
    ("pension", "alv_unemployment", "Unemployment insurance (ALV)", "_DE_ALV_EMPLOYEE_RATE", "_DE_ALV_EMPLOYER_RATE",
     None, None, ("pack", "alv_unemployment"), None),
    ("pension", "midijob_pv_childless_surcharge_rate", "PV childless surcharge (Midijob path)",
     "_DE_PV_CHILDLESS_SURCHARGE_RATE", None, None, None, ("parameter", "midijob_pv_childless_surcharge_rate"), None),
    ("ceilings", "jaeg_annual_threshold", "Compulsory health-insurance threshold (JAEG), annual", None, None,
     "_DE_JAEG_ANNUAL_THRESHOLD", None, None, None),
    ("minijob", "minijob_upper_threshold", "Minijob upper threshold (monthly)", None, None,
     "_DE_MINIJOB_UPPER_THRESHOLD", None, ("parameter", "minijob_upper_threshold"), None),
    ("minijob", "midijob_upper_threshold", "Midijob upper threshold (monthly)", None, None,
     "_DE_MIDIJOB_UPPER_THRESHOLD", None, ("parameter", "midijob_upper_threshold"), None),
    ("minijob", "minijob_employer_health_rate", "Minijob employer health", None, "_DE_MINIJOB_EMPLOYER_HEALTH_RATE",
     None, None, ("parameter", "minijob_employer_health_rate"), None),
    ("minijob", "minijob_employer_pension_rate", "Minijob employer pension", None, "_DE_MINIJOB_EMPLOYER_PENSION_RATE",
     None, None, ("parameter", "minijob_employer_pension_rate"), None),
    ("minijob", "minijob_u1_rate", "Minijob U1 levy", None, "_DE_MINIJOB_U1_RATE",
     None, None, ("parameter", "minijob_u1_rate"), None),
    ("minijob", "minijob_u2_rate", "Minijob U2 levy", None, "_DE_MINIJOB_U2_RATE",
     None, None, ("parameter", "minijob_u2_rate"), None),
    ("minijob", "minijob_u3_rate", "Minijob U3 levy", None, "_DE_MINIJOB_U3_RATE",
     None, None, ("parameter", "minijob_u3_rate"), None),
    ("minijob", "minijob_employee_pension_topup_rate", "Minijob employee pension top-up",
     "_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE", None, None, None, ("parameter", "minijob_employee_pension_topup_rate"),
     "only when the employee has not opted out"),
    ("minijob", "minijob_flat_tax_rate", "Minijob flat tax (Pauschsteuer)", None, "_DE_MINIJOB_FLAT_TAX_RATE",
     None, None, ("parameter", "minijob_flat_tax_rate"), "a tax remitted by the employer"),
    ("minijob", "midijob_total_base_multiplier", "Midijob total base: multiplier", None, None, None,
     "_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER", ("parameter", "midijob_total_base_multiplier"), None),
    ("minijob", "midijob_total_base_subtrahend", "Midijob total base: subtrahend", None, None, None,
     "_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND", ("parameter", "midijob_total_base_subtrahend"), None),
    ("minijob", "midijob_employee_base_multiplier", "Midijob employee base: multiplier", None, None, None,
     "_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER", ("parameter", "midijob_employee_base_multiplier"), None),
    ("minijob", "midijob_employee_base_subtrahend", "Midijob employee base: subtrahend", None, None, None,
     "_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND", ("parameter", "midijob_employee_base_subtrahend"), None),
]

_HIDDEN_STATUSES = ("SUPERSEDED",)


def _s(value) -> Optional[str]:
    return None if value is None else str(value)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _row(row_id, section, key, label, *, employee=None, employer=None, total=None, flat=None, factor=None,
         effective_from=None, effective_to=None, status=None, origin="data", source_file=None, registry=None,
         linked=None, note=None, overridden_by=None) -> dict:
    return {
        "id": row_id, "section": section, "componentKey": key, "label": label,
        "employeeRatePct": _s(employee), "employerRatePct": _s(employer), "totalRatePct": _s(total),
        "flatAmount": _s(flat), "factor": _s(factor),
        "effectiveFrom": _iso(effective_from), "effectiveTo": _iso(effective_to),
        "status": status, "origin": origin, "sourceFile": source_file, "registry": registry,
        "linkedToPack": linked, "note": note, "overriddenBy": overridden_by,
    }


def _registry_rows(db: Session, model, pack) -> list:
    """Rows of `model` linked to `pack`, plus unlinked rows whose dates overlap
    the pack's window (the engine's fallback path); superseded rows excluded."""
    from sqlalchemy import and_, or_

    overlap = []
    if pack.effective_to is not None:
        overlap.append(model.effective_from <= pack.effective_to)
    if pack.effective_from is not None:
        overlap.append(or_(model.effective_to.is_(None), model.effective_to >= pack.effective_from))
    unlinked = and_(model.jurisdiction_pack_id.is_(None), *overlap)
    return (db.query(model).filter(model.status.notin_(_HIDDEN_STATUSES))
            .filter(or_(model.jurisdiction_pack_id == pack.id, unlinked))
            .order_by(model.effective_from.desc(), model.id.desc()).all())


def germany_contribution_rows(db: Session, pack) -> dict:
    """The Contributions view of a German pack: registry rows and the engine's
    fallback constants, grouped by section. Read-only."""
    from app.modules.payroll import hardcoded_defaults
    from app.modules.payroll.models import (
        ContributionRate, GermanyContributionCeiling, GermanyHealthFund, GermanyMinijobMidijobParameter,
        GermanyPvConfiguration,
    )

    rows: list = []
    for fund in _registry_rows(db, GermanyHealthFund, pack):
        levies = [f"{name} {value}%" for name, value in (("U1", fund.u1_rate_pct), ("U2", fund.u2_rate_pct)) if value is not None]
        rows.append(_row(f"hf-{fund.id}", "health", fund.health_fund_id, f"{fund.fund_name}: Zusatzbeitrag",
                         total=fund.supplementary_rate_pct, effective_from=fund.effective_from,
                         effective_to=fund.effective_to, status=fund.status, registry="health-funds",
                         linked=fund.jurisdiction_pack_id == pack.id,
                         note=("employer levies: " + " · ".join(levies)) if levies else None))
    for pv in _registry_rows(db, GermanyPvConfiguration, pack):
        saxony = bool(pv.is_saxony)
        rows.append(_row(f"pv-{pv.id}", "pension", f"pv_{(pv.child_category or '').lower()}",
                         f"Care insurance (PV): {pv.child_category}{' (Saxony)' if saxony else ''}",
                         employee=pv.saxony_employee_rate_pct if saxony else pv.standard_employee_rate_pct,
                         employer=pv.saxony_employer_rate_pct if saxony else pv.employer_rate_pct,
                         total=pv.total_rate_pct, effective_from=pv.effective_from, effective_to=pv.effective_to,
                         status=pv.status, registry="pv-configurations", linked=pv.jurisdiction_pack_id == pack.id))
    for ceiling in _registry_rows(db, GermanyContributionCeiling, pack):
        rows.append(_row(f"cc-{ceiling.id}", "ceilings", f"ceiling_{(ceiling.branch or '').lower()}",
                         f"Contribution ceiling: {ceiling.branch} (monthly)", flat=ceiling.monthly_ceiling,
                         effective_from=ceiling.effective_from, effective_to=ceiling.effective_to,
                         status=ceiling.status, registry="contribution-ceilings",
                         linked=ceiling.jurisdiction_pack_id == pack.id,
                         note=f"annual {ceiling.annual_ceiling}" if ceiling.annual_ceiling is not None else None))
    parameter_codes = set()
    church_overrides = []
    for param in _registry_rows(db, GermanyMinijobMidijobParameter, pack):
        kind = (param.value_type or "").upper()
        base = dict(effective_from=param.effective_from, effective_to=param.effective_to, status=param.status,
                    registry="minijob-midijob-parameters", linked=param.jurisdiction_pack_id == pack.id)
        if (param.parameter_code or "").startswith("church_tax_rate_"):
            church_overrides.append(_row(f"mp-{param.id}", "church", param.parameter_code,
                                         param.label or param.parameter_code, total=param.value, **base))
            continue
        parameter_codes.add(param.parameter_code)
        value = dict(total=param.value) if kind == "PERCENTAGE" else (
            dict(flat=param.value) if kind == "EUR_THRESHOLD" else dict(factor=param.value))
        rows.append(_row(f"mp-{param.id}", "minijob" if not param.parameter_code.startswith("employer_insolvency")
                         else "health", param.parameter_code, param.label or param.parameter_code, **value, **base))

    pack_keys = {r.component_key for r in db.query(ContributionRate)
                 .filter(ContributionRate.jurisdiction_pack_id == pack.id).all()}
    for section, key, label, emp, er, flat, factor, override, note in _ENGINE_CONSTANTS:
        overridden = None
        if override and override[0] == "pack" and override[1] in pack_keys:
            overridden = f"pack row {override[1]}"
        elif override and override[0] == "parameter" and override[1] in parameter_codes:
            overridden = f"registry parameter {override[1]}"
        rows.append(_row(f"engine-{key}", section, key, label,
                         employee=getattr(hardcoded_defaults, emp) if emp else None,
                         employer=getattr(hardcoded_defaults, er) if er else None,
                         flat=getattr(hardcoded_defaults, flat) if flat else None,
                         factor=getattr(hardcoded_defaults, factor) if factor else None,
                         status=ENGINE_STATUS, origin="engine", source_file=ENGINE_DEFAULTS_FILE,
                         note=note, overridden_by=overridden))
    return {
        "packId": pack.id,
        "sections": [{"key": key, "label": label, "rows": [r for r in rows if r["section"] == key]}
                     for key, label in SECTIONS],
        "churchTaxOverrides": church_overrides,
        "accidentInsurance": "Accident insurance (Berufsgenossenschaft) is managed by each organisation; "
                             "it is not part of the platform pack.",
        "engineSourceFile": ENGINE_DEFAULTS_FILE,
    }


def _pct(fraction: Decimal) -> str:
    return str(fraction * 100)


def _pack_reference_date(pack) -> tuple:
    """(date, basis) the tariff for `pack` is resolved on: 1 January of its tax
    year (Germany's tax year is the calendar year), else its effective-from
    date; (None, reason) when neither is usable."""
    year = (getattr(pack, "tax_year", None) or "").strip()[:4]
    if year.isdigit():
        return date(int(year), 1, 1), f"tax year {pack.tax_year}"
    if getattr(pack, "effective_from", None):
        return pack.effective_from, f"effective from {pack.effective_from.isoformat()} (tax year not a calendar year)"
    return None, "the pack has neither a calendar tax year nor an effective-from date"


def germany_wage_tax_tariff(today: Optional[date] = None, pack=None) -> dict:
    """Every section 32a EStG tariff version the engine holds, as zones read from
    tax._TARIFF_VERSIONS, plus the Soli fallback constants. With `pack`, marks
    the version that applies to it: the one tax.resolve_income_tax_tariff (the
    engine's own resolver, given a payslip's pay date) returns for the pack's
    tax year. Read-only."""
    from app.modules.payroll import hardcoded_defaults
    from app.modules.payroll.engine.jurisdictions.germany import tax

    today = today or date.today()
    applies, basis, pack_note = None, None, None
    if pack is not None:
        reference, basis = _pack_reference_date(pack)
        if reference is not None:
            try:
                applies = tax.resolve_income_tax_tariff(reference)
            except tax.GermanyInternalTariffNotAvailableError as exc:
                pack_note = str(getattr(exc, "message", exc))
        else:
            pack_note = basis
    versions = []
    for v in tax._TARIFF_VERSIONS:
        gfb, z2, z3, z4 = v["grundfreibetrag"], v["zone2_upper"], v["zone3_upper"], v["zone4_upper"]
        zones = [
            {"zone": 1, "minAmount": None, "maxAmount": _s(gfb), "ratePct": "0",
             "formula": "no tax", "label": "Basic allowance (Grundfreibetrag)"},
            {"zone": 2, "minAmount": _s(gfb), "maxAmount": _s(z2), "ratePct": None,
             "formula": f"({v['zone2_a']} · y + {v['zone2_b']}) · y, y = (zvE − {gfb}) / 10000",
             "label": "First progression zone"},
            {"zone": 3, "minAmount": _s(z2), "maxAmount": _s(z3), "ratePct": None,
             "formula": f"({v['zone3_a']} · z + {v['zone3_b']}) · z + {v['zone3_c']}, z = (zvE − {z2}) / 10000",
             "label": "Second progression zone"},
            {"zone": 4, "minAmount": _s(z3), "maxAmount": _s(z4), "ratePct": _pct(v["zone4_rate"]),
             "formula": f"{v['zone4_rate']} · zvE − {v['zone4_sub']}", "label": "Proportional zone"},
            {"zone": 5, "minAmount": _s(z4), "maxAmount": None, "ratePct": _pct(v["zone5_rate"]),
             "formula": f"{v['zone5_rate']} · zvE − {v['zone5_sub']}", "label": "Top rate zone"},
        ]
        in_force = v["effective_from"] <= today and (v["effective_to"] is None or today < v["effective_to"])
        versions.append({
            "taxYear": v["tax_year"], "effectiveFrom": _iso(v["effective_from"]),
            # tax.py's effective_to is exclusive (the day the next version starts).
            "effectiveToExclusive": _iso(v["effective_to"]), "inForceToday": in_force,
            "appliesToPack": (v is applies) if pack is not None else None,
            "endsBeforePack": bool(pack is not None and applies is not None and v["effective_to"] is not None
                                   and v["effective_to"] <= applies["effective_from"]),
            "source": v["source"], "zones": zones,
            "parameters": [
                {"key": "grundfreibetrag", "label": "Grundfreibetrag (annual)", "value": _s(gfb)},
                {"key": "kinderfreibetrag_plus_bea", "label": "Child allowance incl. BEA (annual)",
                 "value": _s(v["kinderfreibetrag_plus_bea"])},
                {"key": "soli_threshold_single", "label": "Soli exemption threshold, single (annual)",
                 "value": _s(v["soli_threshold_single"])},
            ],
        })
    return {
        "certified": False,
        "warning": UNCERTIFIED_TARIFF_WARNING,
        "status": "Built into engine (tax.py), not BMF-certified",
        # tax.py's module constant; it still names 2023 although payslips record the
        # resolved version's year (InternalGermanyWageTaxCalculator.execute).
        "provenanceConstant": tax.PROVENANCE_VERSION,
        "pack": None if pack is None else {
            "packId": pack.pack_id, "version": pack.version, "taxYear": pack.tax_year, "basis": basis,
            "appliesTaxYear": applies["tax_year"] if applies else None, "note": pack_note},
        "sourceFile": TARIFF_FILE,
        "note": "zvE = taxable income (zu versteuerndes Einkommen), annual, rounded down to the euro. "
                "Zone bounds: a zone applies above its lower bound up to and including its upper bound.",
        "versions": versions,
        "engineParameters": [
            {"key": "_DE_SOLI_RATE", "label": "Solidarity surcharge rate (%)", "value": _s(hardcoded_defaults._DE_SOLI_RATE),
             "sourceFile": ENGINE_DEFAULTS_FILE, "status": ENGINE_STATUS},
            {"key": "_DE_SOLI_THRESHOLD", "label": "Soli threshold fallback (annual)",
             "value": _s(hardcoded_defaults._DE_SOLI_THRESHOLD), "sourceFile": ENGINE_DEFAULTS_FILE,
             "status": ENGINE_STATUS},
            {"key": "SOLI_MILDERUNGSZONE_RATE", "label": "Soli transition-zone rate (%)",
             "value": _s(tax.SOLI_MILDERUNGSZONE_RATE), "sourceFile": TARIFF_FILE, "status": ENGINE_STATUS},
            {"key": "ARBEITNEHMER_PAUSCHBETRAG", "label": "Employee lump sum (annual)",
             "value": _s(tax.ARBEITNEHMER_PAUSCHBETRAG), "sourceFile": TARIFF_FILE, "status": ENGINE_STATUS},
            {"key": "SONDERAUSGABEN_PAUSCHBETRAG", "label": "Special-expenses lump sum (annual)",
             "value": _s(tax.SONDERAUSGABEN_PAUSCHBETRAG), "sourceFile": TARIFF_FILE, "status": ENGINE_STATUS},
        ],
    }
