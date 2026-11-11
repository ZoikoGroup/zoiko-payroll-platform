"""Poland filing records (ZP-PL-ENG-001 Phase 8; spec §10, PL-019 / PL-020 /
PL-021; decision D5).

  forms      monthly ZUS DRA (payer summary), RCA (contributions per insured
             person) and RSA (employer sick pay, only when there is some) are
             built at PAID for every legal employer in the run, from the frozen
             PAID payslips of the pay-date month (PL-003). ZUA / ZZA / ZWUA are
             built on request from the worker profile in force on the event
             date. PIT-11 (per employee) and PIT-4R (payer) are built on request
             for a CLOSED tax year, from the PAID payslips, cross-checked
             against the year-to-date ledger. RPA (health-only titles) and
             PIT-8AR (flat-rate income) are outside the first release (D2) and
             are refused.
  payload    CANONICAL and schema-neutral: amounts as strings, identifiers as
             vault id + masked form only, never a raw PESEL / NIP (PL-025). The
             mapping onto an official ZUS KEDU / e-Deklaracje schema happens
             only through content.PL_FORM_SCHEMA_CATALOG, which holds no
             archived schema yet (PL-019): until it does, a filing can be
             generated and previewed but never approved or submitted.
  versions   a DRAFT is regenerated in place; an APPROVED one is SUPERSEDED by a
             new version; a REJECTED one is followed by a new ORIGINAL version;
             a SUBMITTED / ACCEPTED one is followed by a CORRECTION (and becomes
             CORRECTED when the correction is accepted). Same payload -> nothing
             happens; every row carries a unique idempotency key (PL-020).
  transport  none (PL-021): submission and the authority's receipt or rejection
             are recorded by hand; a repeated record with the same reference is
             the same event (idempotent retry), a different one is refused.
  due date   the ZUS day from the employer's verified deadline class when the
             signed day list contains it; PIT-11 / PIT-4R from the signed annual
             rule. No holiday shift is applied (the spec requires
             authority-verified calendar logic that is not supplied) and the
             payload says so; registration forms carry no due date.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import poland_service as pls

ZERO = Decimal("0")
PAID_STATUSES = ("Paid", "Closed")
MONTHLY_FORMS = ("DRA", "RCA", "RSA")
REGISTRATION_FORMS = ("ZUA", "ZZA", "ZWUA")
ANNUAL_FORMS = ("PIT11", "PIT4R")
OUT_OF_SCOPE_FORMS = {"RPA": "health-only insurance titles are outside the first release (D2)",
                      "PIT8AR": "flat-rate (non-scale) income is outside the first release (D2)"}
NO_HOLIDAY_SHIFT = "NOMINAL_DAY_NO_HOLIDAY_SHIFT"
ANNUAL_DUE_RULES = {"END_JANUARY": 1, "END_FEBRUARY": 2}
SUBMITTED_STATES = ("SUBMITTED", "ACCEPTED", "CORRECTED")


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Poland ({code}): {message}")


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _s(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def period_key(on: date) -> str:
    return f"{on.year:04d}-{on.month:02d}"


def _month_bounds(key: str) -> tuple:
    year, month = int(key[:4]), int(key[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _next_month(on: date) -> tuple:
    return (on.year + 1, 1) if on.month == 12 else (on.year, on.month + 1)


# ── signed content ──────────────────────────────────────────────────────────
def signed_pack(db: Session, organization_id: int, on: date):
    """The pack in force on `on` as a PlPack, or None when there is none."""
    from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        rates, slabs, pack = resolve_tax_configuration(db, pls.PL, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack"; the caller treats it as unsigned
        return None
    if pack is None:
        return None
    return PlPack({r.component_key: r for r in rates}, slabs, organization_id, on)


def signed_text(pack, key: str) -> Optional[str]:
    from app.modules.payroll.engine.jurisdictions.poland.errors import PLCalculationBlockedError

    if pack is None:
        return None
    try:
        return pack.text(key)
    except PLCalculationBlockedError:
        return None


def signed_amount(pack, key: str) -> Optional[Decimal]:
    from app.modules.payroll.engine.jurisdictions.poland.errors import PLCalculationBlockedError

    if pack is None:
        return None
    try:
        return pack.amount(key)
    except PLCalculationBlockedError:
        return None


def zus_due_on(db: Session, organization_id: int, key: str, registration) -> Optional[date]:
    """The nominal ZUS day of the following month for the employer's deadline
    class, only when the signed day list contains that day."""
    if registration is None or not registration.zus_deadline_class:
        return None
    day = registration.zus_deadline_class.split("_", 1)[-1]
    start, _end = _month_bounds(key)
    year, month = _next_month(start)
    pack = signed_pack(db, organization_id, date(year, month, 1))
    allowed = signed_text(pack, "pl_zus_due_day_classes")
    if allowed is None or day not in [part.strip() for part in allowed.split(",")]:
        return None
    return date(year, month, int(day))


def annual_due_on(db: Session, organization_id: int, year: int, key: str) -> Optional[date]:
    pack = signed_pack(db, organization_id, date(year, 12, 31))
    rule = signed_text(pack, key)
    month = ANNUAL_DUE_RULES.get(rule or "")
    if month is None:
        return None
    return date(year + 1, month, calendar.monthrange(year + 1, month)[1])


# ── schema catalogue (PL-019) ───────────────────────────────────────────────
def schema_version(form_code: str, on: date) -> Optional[str]:
    """The newest archived schema version of `form_code` in force on `on`;
    None while the catalogue holds none (the default)."""
    entry = pls._content().PL_FORM_SCHEMA_CATALOG.get(form_code) or {}
    best = None
    for version, meta in (entry.get("versions") or {}).items():
        start = date.fromisoformat(str((meta or {}).get("effective_from") or "9999-12-31"))
        end = (meta or {}).get("effective_to")
        if start <= on and (end is None or date.fromisoformat(str(end)) >= on):
            if best is None or start > best[0]:
                best = (start, str(version))
    return best[1] if best else None


def _authority(form_code: str) -> str:
    return pls._content().PL_FORM_SCHEMA_CATALOG[form_code]["authority"]


# ── identity blocks (masked only) ───────────────────────────────────────────
def _payer(registration) -> dict:
    if registration is None:
        return {"registrationId": None}
    return {"registrationId": registration.id, "legalName": registration.legal_name, "nip": registration.nip,
            "regon": registration.regon, "zusDeadlineClass": registration.zus_deadline_class,
            "verificationState": registration.verification_state}


def _vault_view(db: Session, vault_id) -> dict:
    if vault_id is None:
        return {"id": None, "masked": None}
    row = db.get(pls._models().PayrollPlIdentifierVault, vault_id)
    if row is None:
        return {"id": None, "masked": None}
    view = pls.identifier_view(row)
    return {"id": view["id"], "masked": view["masked"]}


def _pesel_vault_id(db: Session, organization_id: int, employee_id: int, profile):
    """The employee's ACTIVE PESEL in the vault (the profile pointer when set)."""
    if getattr(profile, "pesel_vault_id", None) is not None:
        return profile.pesel_vault_id
    V = pls._models().PayrollPlIdentifierVault
    row = (db.query(V.id).filter(V.organization_id == organization_id, V.employee_id == employee_id,
                                 V.identifier_type == "PESEL", V.status == "ACTIVE").first())
    return row[0] if row else None


def _insured(db: Session, organization_id: int, employee, on: date) -> dict:
    m = pls._models()
    profile = pls._one_active(db, m.PayrollPlWorkerProfile, organization_id, employee.id, on, "worker profile")
    pesel = _vault_view(db, _pesel_vault_id(db, organization_id, employee.id, profile))
    passport = (getattr(employee, "compliance_fields", None) or {}).get("passport_number")
    return {"employeeId": employee.id, "peselVaultId": pesel["id"], "peselMasked": pesel["masked"],
            "passportOnFile": bool(passport) if pesel["id"] is None else None,
            "insuranceTitleCode": getattr(profile, "insurance_title_code", None)}


def _registration(db: Session, organization_id: int, legal_entity_id, on: date):
    return pls._one_active(db, pls._models().PayrollPlEmployerRegistration, organization_id, None, on,
                           "employer registration", legal_entity_id=legal_entity_id, entity_scoped=True)


# ── source payslips ─────────────────────────────────────────────────────────
def _paid_items(db: Session, organization_id: int, start: date, end: date, legal_entity_id, extra_run=None):
    """PL payslips of every PAID run whose pay date falls in [start, end] (plus
    the run being paid now) for one legal employer, sorted."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun

    runs = (db.query(PayrollRun).filter(PayrollRun.organization_id == organization_id,
                                        PayrollRun.pay_date >= start, PayrollRun.pay_date <= end).all())
    chosen = [r for r in runs if (extra_run is not None and r.id == extra_run.id)
              or str(getattr(r.status, "value", r.status)) in PAID_STATUSES]
    items = []
    for run in sorted(chosen, key=lambda r: r.id):
        for item in pls._run_items(db, run):
            employee = db.get(PayrollEmployee, item.employee_id)
            if getattr(employee, "legal_entity_id", None) == legal_entity_id:
                items.append((run, item, employee))
    return sorted({r.id for r, _i, _e in items}), items


def item_measures(item) -> dict:
    """Money lines of one frozen PL payslip (strings in, Decimals out)."""
    s = item.pl_calculation_snapshot or {}
    zus_ee = {k: _dec(v) for k, v in (s.get("pl_zus_employee") or {}).items()}
    zus_er = {k: _dec(v) for k, v in (s.get("pl_zus_employer") or {}).items()}
    ppk_ee = sum((_dec(v) for v in (s.get("pl_ppk_employee") or {}).values()), ZERO)
    ppk_er = sum((_dec(v) for v in (s.get("pl_ppk_employer") or {}).values()), ZERO)
    funds = {k: _dec(v) for k, v in (s.get("pl_funds") or {}).items()}
    net, pit, employee_total = _dec(s.get("pl_net")), _dec(s.get("pl_pit_advance")), _dec(s.get("pl_employee_total"))
    sickness = ((s.get("trace") or {}).get("sickness") or {})
    zus_trace = ((s.get("trace") or {}).get("zus") or {})
    return {"gross": net + pit + employee_total, "net": net, "pit": pit, "pitBase": _dec(s.get("pl_pit_base")),
            "zusEmployee": zus_ee, "zusEmployer": zus_er, "health": _dec(s.get("pl_health")),
            "healthBase": _dec(s.get("pl_health_base")), "ppkEmployee": ppk_ee, "ppkEmployer": ppk_er,
            "funds": funds, "employeeTotal": employee_total,
            "pensionBase": _dec((zus_trace.get("pension") or {}).get("assessed")),
            "disabilityBase": _dec((zus_trace.get("disability") or {}).get("assessed")),
            "sicknessBase": _dec(zus_trace.get("sicknessBase")), "accidentBase": _dec(zus_trace.get("accidentBase")),
            "sickEmployerDays": int(sickness.get("employerDays") or 0) if sickness.get("status") == "CALCULATED"
            else 0,
            "sickEmployerAmount": _dec(sickness.get("amount")) if sickness.get("status") == "CALCULATED" else ZERO}


def _sum_dicts(target: dict, source: dict) -> None:
    for k, v in source.items():
        target[k] = target.get(k, ZERO) + v


def _strs(values: dict) -> dict:
    return {k: _s(v) for k, v in sorted(values.items())}


# ── payloads ────────────────────────────────────────────────────────────────
def _monthly_payloads(db: Session, organization_id: int, key: str, legal_entity_id, items, registration) -> dict:
    per, totals = {}, {"zusEmployee": {}, "zusEmployer": {}, "funds": {}, "health": ZERO, "ppk": ZERO}
    for _run, item, employee in items:
        mm = item_measures(item)
        entry = per.get(employee.id)
        if entry is None:
            entry = per[employee.id] = {**_insured(db, organization_id, employee, _month_bounds(key)[1]),
                                        "payslipItemIds": [], "zusEmployee": {}, "zusEmployer": {},
                                        "bases": {}, "health": ZERO, "healthBase": ZERO,
                                        "sickEmployerDays": 0, "sickEmployerAmount": ZERO}
        entry["payslipItemIds"].append(item.id)
        _sum_dicts(entry["zusEmployee"], mm["zusEmployee"])
        _sum_dicts(entry["zusEmployer"], mm["zusEmployer"])
        _sum_dicts(entry["bases"], {"EMERYTALNE": mm["pensionBase"], "RENTOWE": mm["disabilityBase"],
                                    "CHOROBOWE": mm["sicknessBase"], "WYPADKOWE": mm["accidentBase"]})
        entry["health"] += mm["health"]
        entry["healthBase"] += mm["healthBase"]
        entry["sickEmployerDays"] += mm["sickEmployerDays"]
        entry["sickEmployerAmount"] += mm["sickEmployerAmount"]
        _sum_dicts(totals["zusEmployee"], mm["zusEmployee"])
        _sum_dicts(totals["zusEmployer"], mm["zusEmployer"])
        _sum_dicts(totals["funds"], mm["funds"])
        totals["health"] += mm["health"]
        totals["ppk"] += mm["ppkEmployee"] + mm["ppkEmployer"]
    head = {"periodKey": key, "legalEntityId": legal_entity_id, "payer": _payer(registration),
            "canonical": True, "dueRule": NO_HOLIDAY_SHIFT}
    insured = []
    for employee_id in sorted(per):
        e = per[employee_id]
        insured.append({**{k: e[k] for k in ("employeeId", "peselVaultId", "peselMasked", "passportOnFile",
                                              "insuranceTitleCode", "payslipItemIds")},
                        "bases": _strs(e["bases"]), "zusEmployee": _strs(e["zusEmployee"]),
                        "zusEmployer": _strs(e["zusEmployer"]), "health": _s(e["health"]),
                        "healthBase": _s(e["healthBase"]),
                        "_sick": (e["sickEmployerDays"], e["sickEmployerAmount"])})
    rca = {"form": "RCA", **head, "insured": [{k: v for k, v in i.items() if k != "_sick"} for i in insured]}
    zus_total = (sum(totals["zusEmployee"].values(), ZERO) + sum(totals["zusEmployer"].values(), ZERO)
                 + totals["health"] + sum(totals["funds"].values(), ZERO))
    dra = {"form": "DRA", **head, "insuredCount": len(insured), "zusEmployee": _strs(totals["zusEmployee"]),
           "zusEmployer": _strs(totals["zusEmployer"]), "health": _s(totals["health"]),
           "funds": _strs(totals["funds"]), "totalDue": _s(zus_total)}
    sick = [{k: i[k] for k in ("employeeId", "peselVaultId", "peselMasked", "insuranceTitleCode")}
            | {"employerDays": i["_sick"][0], "employerSickPay": _s(i["_sick"][1])}
            for i in insured if i["_sick"][0] > 0]
    out = {"DRA": dra, "RCA": rca}
    if sick:
        out["RSA"] = {"form": "RSA", **head, "insured": sick}
    return out


# ── records ─────────────────────────────────────────────────────────────────
def _model():
    return pls._models().PayrollPlFiling


def _idempotency_key(organization_id, legal_entity_id, form_code, key, subject, kind, version, corrects_id,
                     digest) -> str:
    raw = "|".join(str(x) for x in (organization_id, legal_entity_id, form_code, key, subject, kind, version,
                                    corrects_id, digest))
    return hashlib.sha256(raw.encode()).hexdigest()


def _latest(db: Session, organization_id, legal_entity_id, form_code, key, subject, kind="ORIGINAL"):
    F = _model()
    query = db.query(F).filter(F.organization_id == organization_id, F.form_code == form_code,
                               F.period_key == key, F.kind == kind)
    query = query.filter(F.legal_entity_id.is_(None) if legal_entity_id is None else F.legal_entity_id == legal_entity_id)
    query = query.filter(F.subject_key.is_(None) if subject is None else F.subject_key == subject)
    return query.order_by(F.version.desc(), F.id.desc()).first()


def _new_row(db: Session, organization_id, legal_entity_id, form_code, key, subject, kind, version, payload,
             run_ids, due_on, actor_id, corrects_id=None, previous_id=None):
    F = _model()
    digest = canonical_hash(payload)
    row = F(organization_id=organization_id, legal_entity_id=legal_entity_id, authority=_authority(form_code),
            form_code=form_code, period_key=key, subject_key=subject, kind=kind, version=version,
            run_ids=run_ids, payload=payload, payload_hash=digest,
            idempotency_key=_idempotency_key(organization_id, legal_entity_id, form_code, key, subject, kind,
                                             version, corrects_id, digest),
            due_on=due_on, status="DRAFT", corrects_id=corrects_id, previous_version_id=previous_id,
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    pls._audit(db, actor_id, "generated", "pl_filing", row.id,
               new={"form": form_code, "period": key, "kind": kind, "version": version, "hash": digest})
    return row


def _refresh_draft(db: Session, row, payload, run_ids, due_on, actor_id):
    digest = canonical_hash(payload)
    row.payload, row.payload_hash, row.run_ids, row.due_on = payload, digest, run_ids, due_on
    row.idempotency_key = _idempotency_key(row.organization_id, row.legal_entity_id, row.form_code, row.period_key,
                                           row.subject_key, row.kind, row.version, row.corrects_id, digest)
    row.updated_at = datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "regenerated", "pl_filing", row.id, new={"hash": digest})
    return row


def upsert_filing(db: Session, organization_id: int, legal_entity_id, form_code: str, key: str, payload: dict,
                  run_ids, due_on, actor_id, subject: Optional[str] = None):
    """Store `payload` for (employer, form, period, subject) under the
    versioning rules; the same payload again returns the existing row."""
    digest = canonical_hash(payload)
    latest = _latest(db, organization_id, legal_entity_id, form_code, key, subject)
    if latest is None:
        return _new_row(db, organization_id, legal_entity_id, form_code, key, subject, "ORIGINAL", 1, payload,
                        run_ids, due_on, actor_id)
    if latest.status in SUBMITTED_STATES:
        return _correction(db, latest, payload, run_ids, actor_id)
    if latest.payload_hash == digest and latest.status != "SUPERSEDED":
        return latest                                                     # PL-020: nothing changed
    if latest.status == "DRAFT":
        return _refresh_draft(db, latest, payload, run_ids, due_on, actor_id)
    if latest.status == "APPROVED":
        latest.status = "SUPERSEDED"
        pls._audit(db, actor_id, "superseded", "pl_filing", latest.id, new={"status": "SUPERSEDED"})
    return _new_row(db, organization_id, legal_entity_id, form_code, key, subject, "ORIGINAL", latest.version + 1,
                    payload, run_ids, due_on, actor_id, previous_id=latest.id)


def _correction(db: Session, original, payload: dict, run_ids, actor_id):
    F = _model()
    digest = canonical_hash(payload)
    if original.payload_hash == digest:
        return original
    rows = (db.query(F).filter(F.corrects_id == original.id, F.kind == "CORRECTION")
            .order_by(F.version.desc(), F.id.desc()).all())
    latest = rows[0] if rows else None
    if latest is not None and latest.payload_hash == digest and latest.status != "SUPERSEDED":
        return latest                                                     # PL-020: no duplicate correction
    corrected = {**payload, "correction": True, "corrects": original.id}
    if latest is not None and latest.status == "DRAFT":
        return _refresh_draft(db, latest, corrected, run_ids, None, actor_id)
    if latest is not None and latest.status == "APPROVED":
        latest.status = "SUPERSEDED"
    return _new_row(db, original.organization_id, original.legal_entity_id, original.form_code,
                    original.period_key, original.subject_key, "CORRECTION", (latest.version + 1) if latest else 1,
                    corrected, run_ids, None, actor_id, corrects_id=original.id,
                    previous_id=getattr(latest, "id", None))


# ── builders ────────────────────────────────────────────────────────────────
def build_pl_run_filings(db: Session, run, actor_id) -> list:
    """At PAID: (re)build DRA / RCA (/ RSA) of the pay-date month for every
    legal employer in the run."""
    from app.modules.payroll.models import PayrollEmployee

    items = pls._run_items(db, run)
    if not items:
        return []
    key = period_key(run.pay_date)
    start, end = _month_bounds(key)
    entities = sorted({getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items},
                      key=lambda x: (x is not None, x or 0))
    out = []
    for entity in entities:
        run_ids, month_items = _paid_items(db, run.organization_id, start, end, entity, extra_run=run)
        registration = _registration(db, run.organization_id, entity, end)
        due = zus_due_on(db, run.organization_id, key, registration)
        payloads = _monthly_payloads(db, run.organization_id, key, entity, month_items, registration)
        for form in MONTHLY_FORMS:
            if form in payloads:
                out.append(upsert_filing(db, run.organization_id, entity, form, key, payloads[form], run_ids, due,
                                         actor_id))
    return out


def build_pl_annual_filings(db: Session, organization_id: int, year: int, legal_entity_id, actor_id,
                            today: Optional[date] = None) -> list:
    """PIT-11 per employee and PIT-4R for a CLOSED tax year, from the PAID
    payslips; refused when the year-to-date ledger disagrees."""
    year = int(year)
    if (today or date.today()) <= date(year, 12, 31):
        _conflict("PL_TAX_YEAR_OPEN", f"{year} is not closed; annual returns are built after 31 December.")
    pls._legal_entity(db, organization_id, legal_entity_id)
    run_ids, items = _paid_items(db, organization_id, date(year, 1, 1), date(year, 12, 31), legal_entity_id)
    if not items:
        _conflict("PL_NO_PAID_PAYSLIPS", f"no PAID Poland payslips in {year} for this employer.")
    registration = _registration(db, organization_id, legal_entity_id, date(year, 12, 31))
    Entry = pls._models().PayrollPlAccumulatorEntry
    per, months = {}, {}
    for run, item, employee in items:
        mm = item_measures(item)
        e = per.setdefault(employee, {"gross": ZERO, "zusEmployee": ZERO, "health": ZERO, "pitBase": ZERO,
                                      "pit": ZERO, "ppkEmployerTaxable": ZERO, "items": []})
        e["gross"] += mm["gross"]
        e["zusEmployee"] += sum(mm["zusEmployee"].values(), ZERO)
        e["health"] += mm["health"]
        e["pitBase"] += mm["pitBase"]
        e["pit"] += mm["pit"]
        e["items"].append(item.id)
        month = period_key(run.pay_date)
        months[month] = months.get(month, ZERO) + mm["pit"]
    out = []
    pit11_due = annual_due_on(db, organization_id, year, "pl_pit11_authority_due")
    for employee in sorted(per, key=lambda x: x.id):
        e = per[employee]
        ledger = {}
        for accumulator, amount in (db.query(Entry.accumulator, Entry.amount)
                                    .filter(Entry.organization_id == organization_id,
                                            Entry.employee_id == employee.id, Entry.year == year).all()):
            ledger[accumulator] = ledger.get(accumulator, ZERO) + _dec(amount)
        if ledger.get("PIT_ADVANCE", ZERO) != e["pit"]:
            _conflict("PL_LEDGER_MISMATCH", f"employee #{employee.id}: ledger PIT advance "
                      f"{_s(ledger.get('PIT_ADVANCE', ZERO))} differs from the PAID payslips {_s(e['pit'])}.")
        payload = {"form": "PIT11", "taxYear": year, "legalEntityId": legal_entity_id, "payer": _payer(registration),
                   "canonical": True, **_insured(db, organization_id, employee, date(year, 12, 31)),
                   "payslipItemIds": e["items"], "grossRevenue": _s(e["gross"]),
                   "costsUsed": _s(ledger.get("PIT_COSTS_USED", ZERO)), "zusEmployeeDeducted": _s(e["zusEmployee"]),
                   "healthContribution": _s(e["health"]), "pitBase": _s(e["pitBase"]), "pitAdvance": _s(e["pit"]),
                   "pit0Exempt": {k: _s(v) for k, v in sorted(ledger.items()) if k.startswith("PIT0_EXEMPT_")}}
        out.append(upsert_filing(db, organization_id, legal_entity_id, "PIT11", str(year), payload, run_ids,
                                 pit11_due, actor_id, subject=f"E{employee.id}"))
    pit4r = {"form": "PIT4R", "taxYear": year, "legalEntityId": legal_entity_id, "payer": _payer(registration),
             "canonical": True, "monthlyAdvances": _strs(months), "total": _s(sum(months.values(), ZERO)),
             "employeeCount": len(per)}
    out.append(upsert_filing(db, organization_id, legal_entity_id, "PIT4R", str(year), pit4r, run_ids,
                             annual_due_on(db, organization_id, year, "pl_pit4r_due"), actor_id))
    return out


def build_pl_registration_filing(db: Session, organization_id: int, employee_id: int, form_code: str,
                                 event_date, actor_id, reason_code: Optional[str] = None):
    """ZUA (full insurance) / ZZA (health only) / ZWUA (deregistration) from
    the worker profile in force on the event date."""
    form_code = str(form_code or "").strip().upper()
    if form_code in OUT_OF_SCOPE_FORMS:
        _conflict("PL_FORM_OUT_OF_SCOPE", OUT_OF_SCOPE_FORMS[form_code])
    if form_code not in REGISTRATION_FORMS:
        raise BadRequestException(f"form must be one of: {', '.join(REGISTRATION_FORMS)}.")
    on = pls._as_date(event_date, "eventDate")
    employee = pls._employee(db, organization_id, employee_id)
    m = pls._models()
    profile = pls._one_active(db, m.PayrollPlWorkerProfile, organization_id, employee.id, on, "worker profile")
    if profile is None:
        _conflict("PL_PROFILE_MISSING", "no ACTIVE Poland worker profile is in force on the event date.")
    if form_code == "ZWUA" and not (reason_code or "").strip():
        raise BadRequestException("A deregistration reason code is required for ZWUA.")
    entity = getattr(employee, "legal_entity_id", None)
    registration = _registration(db, organization_id, entity, on)
    payload = {"form": form_code, "eventDate": on.isoformat(), "legalEntityId": entity, "payer": _payer(registration),
               "canonical": True, **_insured(db, organization_id, employee, on),
               "coverage": {"pension": profile.cov_pension, "disability": profile.cov_disability,
                            "sickness": profile.cov_sickness, "accident": profile.cov_accident,
                            "health": profile.cov_health}}
    if form_code == "ZWUA":
        payload["reasonCode"] = str(reason_code).strip().upper()[:10]
    return upsert_filing(db, organization_id, entity, form_code, period_key(on), payload, None, None, actor_id,
                         subject=f"E{employee.id}:{on.isoformat()}")


# ── workflow ────────────────────────────────────────────────────────────────
def _filing(db: Session, organization_id: int, filing_id: int):
    F = _model()
    row = db.query(F).filter(F.id == filing_id, F.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Poland filing")
    return row


def _verify_hash(row) -> None:
    if canonical_hash(row.payload) != row.payload_hash:
        _conflict("PAYLOAD_CHANGED_AFTER_APPROVAL", "the stored payload no longer matches its hash.")


def _period_date(row) -> date:
    key = row.period_key
    if len(key) == 4:
        return date(int(key), 12, 31)
    return _month_bounds(key)[1]


def approve_pl_filing(db: Session, organization_id: int, filing_id: int, actor_id):
    """A second person approves a DRAFT, and only against an archived schema
    version of the form (PL-019)."""
    from app.modules.payroll.service import require_four_eyes

    row = _filing(db, organization_id, filing_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT Poland filing can be approved.")
    version = schema_version(row.form_code, _period_date(row))
    if version is None:
        _conflict("FILING_SCHEMA_MISMATCH", f"no archived {row.form_code} schema is in the form catalogue "
                  "(PL-019); the canonical payload can be previewed but not approved.")
    _verify_hash(row)
    require_four_eyes(row.created_by_id, actor_id, "Approving a Poland filing", db=db, entity_type="pl_filing",
                      entity_id=row.id, current_status=row.status)
    row.status, row.schema_version = "APPROVED", version
    row.approved_by_id, row.approved_at = actor_id, datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "approved", "pl_filing", row.id, new={"status": "APPROVED", "schema": version})
    return row


def record_pl_filing_submission(db: Session, organization_id: int, filing_id: int, submission_ref, actor_id):
    """Record that the APPROVED payload was submitted outside the platform
    (PL-021). The same reference again is the same submission (PL-020)."""
    ref = str(submission_ref or "").strip()[:100]
    if not ref:
        raise BadRequestException("submissionRef is required.")
    row = _filing(db, organization_id, filing_id)
    if row.status in SUBMITTED_STATES or row.status == "REJECTED":
        if row.submission_ref == ref:
            return row                                                    # idempotent retry
        _conflict("PL_FILING_ALREADY_SUBMITTED", "this filing was already submitted under another reference.")
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED Poland filing can be submitted.")
    if schema_version(row.form_code, _period_date(row)) != row.schema_version:
        _conflict("FILING_SCHEMA_MISMATCH", "the approved schema version is no longer in force; approve again.")
    _verify_hash(row)
    row.status, row.submission_ref = "SUBMITTED", ref
    row.submitted_by_id, row.submitted_at = actor_id, datetime.utcnow()
    db.flush()
    pls._audit(db, actor_id, "submitted", "pl_filing", row.id, new={"status": "SUBMITTED", "ref": ref})
    return row


def record_pl_filing_response(db: Session, organization_id: int, filing_id: int, payload: dict, actor_id):
    """ACCEPTED (with the receipt reference) or REJECTED (with structured
    error codes). Never touches a settlement; a rejection leaves payroll
    unchanged. An accepted correction marks its original CORRECTED."""
    payload = dict(payload or {})
    outcome = str(payload.get("outcome") or "").strip().upper()
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise BadRequestException("outcome must be ACCEPTED or REJECTED.")
    receipt = str(payload.get("receiptRef") or "").strip()[:100] or None
    codes = [str(c).strip().upper()[:40] for c in (payload.get("errorCodes") or []) if str(c).strip()]
    if outcome == "ACCEPTED" and not receipt:
        raise BadRequestException("receiptRef is required for an ACCEPTED filing.")
    if outcome == "REJECTED" and not codes:
        raise BadRequestException("errorCodes are required for a REJECTED filing.")
    row = _filing(db, organization_id, filing_id)
    if row.status in ("ACCEPTED", "REJECTED", "CORRECTED"):
        same = (row.status == outcome or (row.status == "CORRECTED" and outcome == "ACCEPTED"))
        if same and row.receipt_ref == receipt and (outcome == "ACCEPTED" or (row.rejection or {}).get("codes") == codes):
            return row                                                    # idempotent retry
        _conflict("PL_FILING_ALREADY_ANSWERED", "the authority's response is already recorded.")
    if row.status != "SUBMITTED":
        raise BadRequestException("Only a SUBMITTED Poland filing can receive the authority's response.")
    row.status, row.receipt_ref, row.responded_at = outcome, receipt, datetime.utcnow()
    row.rejection = {"codes": codes, "message": str(payload.get("message") or "")[:300] or None} if codes else None
    if outcome == "ACCEPTED" and row.kind == "CORRECTION" and row.corrects_id:
        original = db.get(_model(), row.corrects_id)
        if original is not None and original.status == "ACCEPTED":
            original.status = "CORRECTED"
    db.flush()
    pls._audit(db, actor_id, "responded", "pl_filing", row.id, new={"status": outcome, "errors": codes})
    return row


def filing_view(row, include_payload: bool = False) -> dict:
    out = {"id": row.id, "legalEntityId": row.legal_entity_id, "authority": row.authority, "formCode": row.form_code,
           "periodKey": row.period_key, "subjectKey": row.subject_key, "kind": row.kind, "version": row.version,
           "schemaVersion": row.schema_version, "schemaArchived": schema_version(row.form_code, _period_date(row))
           is not None, "runIds": row.run_ids, "payloadHash": row.payload_hash,
           "idempotencyKey": row.idempotency_key, "dueOn": row.due_on.isoformat() if row.due_on else None,
           "status": row.status, "correctsId": row.corrects_id, "previousVersionId": row.previous_version_id,
           "submissionRef": row.submission_ref, "receiptRef": row.receipt_ref, "rejection": row.rejection,
           "createdById": row.created_by_id, "approvedById": row.approved_by_id}
    if include_payload:
        out["payload"] = row.payload                                       # masked identifiers only
    return out


def list_pl_filings(db: Session, organization_id: int, period=None, form_code=None, status=None) -> list:
    F = _model()
    query = db.query(F).filter(F.organization_id == organization_id)
    if period:
        query = query.filter(F.period_key == str(period).strip())
    if form_code:
        query = query.filter(F.form_code == str(form_code).strip().upper())
    if status:
        query = query.filter(F.status == str(status).strip().upper())
    return [filing_view(r) for r in query.order_by(F.period_key.desc(), F.form_code, F.kind, F.version.desc(),
                                                   F.id.desc())]


def get_pl_filing(db: Session, organization_id: int, filing_id: int) -> dict:
    return filing_view(_filing(db, organization_id, filing_id), include_payload=True)
