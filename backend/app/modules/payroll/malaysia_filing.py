"""Malaysia filing records (ZP-MY-ENG-001 Phase 9; MY-021 / MY-022 / MY-028;
decision D-5).

  forms      monthly PCB_MONTHLY (HASiL e-PCB / CP39 dataset), EPF_MONTHLY,
             PERKESO_EIS_MONTHLY (SOCSO + EIS in one PERKESO file) and
             HRD_MONTHLY are built at PAID for every legal employer in the run,
             from the frozen PAID payslips of the pay-date month. EA (per
             employee) with FORM_E + CP8D (employer) are built on request for a
             CLOSED year, cross-checked against the year-to-date ledger. CP22 /
             CP22A / CP21 are built on request from a recorded employer event.
             EC (public sector) and EDATA_PRAISI (optional) are outside release
             1 and refused.
  payload    CANONICAL and schema-neutral: amounts as strings, identifiers as
             vault id + masked form only, never a raw NRIC / TIN (MY-029). The
             mapping onto an official authority layout happens only through
             content.MY_FORM_SCHEMA_CATALOG, which holds no archived layout yet:
             until it does, a filing can be generated and previewed but never
             approved or submitted.
  versions   a DRAFT is regenerated in place; an APPROVED one is SUPERSEDED by a
             new version; a SUBMITTED / ACCEPTED one is followed by a CORRECTION.
             Same payload -> nothing happens; every row carries a unique
             idempotency key and the payroll runs it came from (MY-028).
  transport  none (D-5): submission and the authority's receipt or rejection are
             recorded by hand; the same reference again is the same event.
  due date   PCB from the signed remittance day of the following month; EPF /
             PERKESO / HRD from their due rules (PENDING_G1 -> no due date); EA /
             Form E from the signed annual rules; events carry their own due
             date. No holiday shift is applied, and the payload says so.
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
from app.modules.payroll import malaysia_service as mys

ZERO = Decimal("0")
PAID_STATUSES = ("Paid", "Closed")
MONTHLY_FORMS = ("PCB_MONTHLY", "EPF_MONTHLY", "PERKESO_EIS_MONTHLY", "HRD_MONTHLY")
ANNUAL_FORMS = ("EA", "FORM_E", "CP8D")
EVENT_FORMS = ("CP22", "CP22A", "CP21")
OUT_OF_SCOPE_FORMS = {"EC": "public-sector EC forms are outside release 1",
                      "EDATA_PRAISI": "the optional e-Data Praisi file is outside release 1"}
NO_HOLIDAY_SHIFT = "NOMINAL_DAY_NO_HOLIDAY_SHIFT"
ANNUAL_DUE_MONTHS = {"END_FEBRUARY": 2, "END_MARCH": 3}
SUBMITTED_STATES = ("SUBMITTED", "ACCEPTED", "CORRECTED")


def _conflict(code: str, message: str):
    raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Malaysia ({code}): {message}")


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _s(value: Decimal) -> str:
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def period_key(on: date) -> str:
    return f"{on.year:04d}-{on.month:02d}"


def _month_bounds(key: str) -> tuple:
    year, month = int(key[:4]), int(key[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _next_month(on: date) -> tuple:
    return (on.year + 1, 1) if on.month == 12 else (on.year, on.month + 1)


# ── signed content ──────────────────────────────────────────────────────────
def signed_pack(db: Session, organization_id: int, on: date):
    return mys._signed_pack(db, organization_id, on)


def _signed(pack, kind: str, key: str):
    from app.modules.payroll.engine.jurisdictions.malaysia.errors import MYCalculationBlockedError

    if pack is None:
        return None
    try:
        return pack.text(key) if kind == "text" else pack.amount(key)
    except MYCalculationBlockedError:
        return None


def pcb_due_on(db: Session, organization_id: int, key: str) -> Optional[date]:
    """The signed PCB remittance day of the month after the deduction month."""
    start, _end = _month_bounds(key)
    year, month = _next_month(start)
    day = _signed(signed_pack(db, organization_id, date(year, month, 1)), "amount", "my_pcb_remittance_day")
    if day is None or day != day.to_integral_value() or not 1 <= int(day) <= calendar.monthrange(year, month)[1]:
        return None
    return date(year, month, int(day))


def annual_due_on(db: Session, organization_id: int, year: int, key: str) -> Optional[date]:
    rule = _signed(signed_pack(db, organization_id, date(year, 12, 31)), "text", key)
    month = ANNUAL_DUE_MONTHS.get(rule or "")
    if month is None:
        return None
    return date(year + 1, month, calendar.monthrange(year + 1, month)[1])


# ── schema catalogue (MY-022) ───────────────────────────────────────────────
def schema_version(form_code: str, on: date) -> Optional[str]:
    """The newest archived layout version of `form_code` in force on `on`;
    None while the catalogue holds none (the default)."""
    entry = mys._content().MY_FORM_SCHEMA_CATALOG.get(form_code) or {}
    best = None
    for version, meta in (entry.get("versions") or {}).items():
        start = date.fromisoformat(str((meta or {}).get("effective_from") or "9999-12-31"))
        end = (meta or {}).get("effective_to")
        if start <= on and (end is None or date.fromisoformat(str(end)) >= on):
            if best is None or start > best[0]:
                best = (start, str(version))
    return best[1] if best else None


def _authority(form_code: str) -> str:
    return mys._content().MY_FORM_SCHEMA_CATALOG[form_code]["authority"]


# ── identity blocks (masked only) ───────────────────────────────────────────
def _payer(registration) -> dict:
    if registration is None:
        return {"registrationId": None}
    return {"registrationId": registration.id, "legalName": registration.legal_name,
            "hasilEmployerNo": registration.hasil_employer_no, "epfEmployerNo": registration.epf_employer_no,
            "perkesoEmployerCode": registration.perkeso_employer_code, "hrdCategory": registration.hrd_category,
            "hrdRegistrationNo": registration.hrd_registration_no,
            "verificationState": registration.verification_state}


def _vault(db: Session, organization_id: int, employee_id: int, profile, kind: str, pointer: str) -> dict:
    vault_id = getattr(profile, pointer, None)
    V = mys._models().PayrollMyIdentifierVault
    if vault_id is None:
        row = (db.query(V).filter(V.organization_id == organization_id, V.employee_id == employee_id,
                                  V.identifier_type == kind, V.status == "ACTIVE").first())
    else:
        row = db.get(V, vault_id)
    if row is None or row.status != "ACTIVE":
        return {"id": None, "masked": None}
    view = mys.identifier_view(row)
    return {"id": view["id"], "masked": view["masked"]}


def _worker(db: Session, organization_id: int, employee, on: date) -> dict:
    m = mys._models()
    profile = mys._one_active(db, m.PayrollMyWorkerProfile, organization_id, employee.id, on, "worker profile")
    out = {"employeeId": employee.id, "citizenship": getattr(profile, "citizenship", None)}
    for kind, pointer, name in (("NRIC", "nric_vault_id", "nric"), ("TIN", "tin_vault_id", "tin"),
                                ("EPF_NO", "epf_vault_id", "epfNo"), ("SOCSO_NO", "socso_vault_id", "socsoNo")):
        ref = _vault(db, organization_id, employee.id, profile, kind, pointer)
        out[f"{name}VaultId"], out[f"{name}Masked"] = ref["id"], ref["masked"]
    passport = (getattr(employee, "compliance_fields", None) or {}).get("passport_number")
    out["passportOnFile"] = bool(passport) if out["nricVaultId"] is None else None
    return out


def _registration(db: Session, organization_id: int, legal_entity_id, on: date):
    return mys._one_active(db, mys._models().PayrollMyEmployerRegistration, organization_id, None, on,
                           "employer registration", legal_entity_id=legal_entity_id, entity_scoped=True)


# ── source payslips ─────────────────────────────────────────────────────────
def _paid_items(db: Session, organization_id: int, start: date, end: date, legal_entity_id, extra_run=None):
    """MY payslips of every PAID run whose pay date falls in [start, end] (plus
    the run being paid now) for one legal employer, sorted."""
    from app.modules.payroll.models import PayrollEmployee, PayrollRun

    runs = (db.query(PayrollRun).filter(PayrollRun.organization_id == organization_id,
                                        PayrollRun.pay_date >= start, PayrollRun.pay_date <= end).all())
    chosen = [r for r in runs if (extra_run is not None and r.id == extra_run.id)
              or str(getattr(r.status, "value", r.status)) in PAID_STATUSES]
    items = []
    for run in sorted(chosen, key=lambda r: r.id):
        for item in mys._run_items(db, run):
            employee = db.get(PayrollEmployee, item.employee_id)
            if getattr(employee, "legal_entity_id", None) == legal_entity_id:
                items.append((run, item, employee))
    return sorted({r.id for r, _i, _e in items}), items


def item_measures(item) -> dict:
    """Money lines of one frozen MY payslip (strings in, Decimals out)."""
    s = item.my_calculation_snapshot or {}
    bases = (s.get("trace") or {}).get("bases") or {}

    def side(name, which):
        return _dec((s.get(name) or {}).get(which))

    pcb, net, employee_total = _dec(s.get("my_pcb")), _dec(s.get("my_net")), _dec(s.get("my_employee_total"))
    return {"gross": net + pcb + employee_total, "net": net, "pcb": pcb, "employeeTotal": employee_total,
            "epfEmployee": side("my_epf", "employee"), "epfEmployer": side("my_epf", "employer"),
            "socsoEmployee": side("my_socso", "employee"), "socsoEmployer": side("my_socso", "employer"),
            "eisEmployee": side("my_eis", "employee"), "eisEmployer": side("my_eis", "employer"),
            "hrd": _dec(s.get("my_hrd")),
            "bases": {name: _dec((bases.get(name) or {}).get("base")) for name in
                      ("PCB_NORMAL", "PCB_ADDITIONAL", "EPF", "SOCSO", "EIS", "HRD")}}


# ── payloads ────────────────────────────────────────────────────────────────
def _monthly_payloads(db: Session, organization_id: int, key: str, legal_entity_id, items, registration) -> dict:
    end = _month_bounds(key)[1]
    per = {}
    for _run, item, employee in items:
        mm = item_measures(item)
        e = per.get(employee.id)
        if e is None:
            e = per[employee.id] = {**_worker(db, organization_id, employee, end), "payslipItemIds": [],
                                    "pcb": ZERO, "pcbBase": ZERO, "epfEmployee": ZERO, "epfEmployer": ZERO,
                                    "epfWage": ZERO, "socsoEmployee": ZERO, "socsoEmployer": ZERO, "socsoWage": ZERO,
                                    "eisEmployee": ZERO, "eisEmployer": ZERO, "eisWage": ZERO, "hrd": ZERO,
                                    "hrdBase": ZERO}
        e["payslipItemIds"].append(item.id)
        for name in ("pcb", "epfEmployee", "epfEmployer", "socsoEmployee", "socsoEmployer", "eisEmployee",
                     "eisEmployer", "hrd"):
            e[name] += mm[name]
        e["pcbBase"] += mm["bases"]["PCB_NORMAL"] + mm["bases"]["PCB_ADDITIONAL"]
        e["epfWage"] += mm["bases"]["EPF"]
        e["socsoWage"] += mm["bases"]["SOCSO"]
        e["eisWage"] += mm["bases"]["EIS"]
        e["hrdBase"] += mm["bases"]["HRD"]
    head = {"periodKey": key, "legalEntityId": legal_entity_id, "payer": _payer(registration), "canonical": True,
            "dueRule": NO_HOLIDAY_SHIFT}
    ids = ("employeeId", "payslipItemIds")
    rows = [per[k] for k in sorted(per)]

    def total(name):
        return _s(sum((r[name] for r in rows), ZERO))

    out = {}
    if any(r["pcb"] for r in rows):
        out["PCB_MONTHLY"] = {"form": "PCB_MONTHLY", **head, "total": total("pcb"), "employees": [
            {**{k: r[k] for k in ids + ("nricVaultId", "nricMasked", "tinVaultId", "tinMasked", "passportOnFile")},
             "pcbBase": _s(r["pcbBase"]), "pcb": _s(r["pcb"])} for r in rows if r["pcb"]]}
    if any(r["epfEmployee"] or r["epfEmployer"] for r in rows):
        out["EPF_MONTHLY"] = {"form": "EPF_MONTHLY", **head, "employeeTotal": total("epfEmployee"),
                              "employerTotal": total("epfEmployer"), "members": [
            {**{k: r[k] for k in ids + ("epfNoVaultId", "epfNoMasked", "nricVaultId", "nricMasked")},
             "wage": _s(r["epfWage"]), "employee": _s(r["epfEmployee"]), "employer": _s(r["epfEmployer"])}
            for r in rows if r["epfEmployee"] or r["epfEmployer"]]}
    if any(r["socsoEmployee"] or r["socsoEmployer"] or r["eisEmployee"] or r["eisEmployer"] for r in rows):
        out["PERKESO_EIS_MONTHLY"] = {
            "form": "PERKESO_EIS_MONTHLY", **head,
            "socso": {"employee": total("socsoEmployee"), "employer": total("socsoEmployer")},
            "eis": {"employee": total("eisEmployee"), "employer": total("eisEmployer")},
            "workers": [{**{k: r[k] for k in ids + ("socsoNoVaultId", "socsoNoMasked", "nricVaultId", "nricMasked")},
                         "socsoWage": _s(r["socsoWage"]), "socsoEmployee": _s(r["socsoEmployee"]),
                         "socsoEmployer": _s(r["socsoEmployer"]), "eisWage": _s(r["eisWage"]),
                         "eisEmployee": _s(r["eisEmployee"]), "eisEmployer": _s(r["eisEmployer"])}
                        for r in rows if r["socsoEmployee"] or r["socsoEmployer"] or r["eisEmployee"]
                        or r["eisEmployer"]]}
    if any(r["hrd"] for r in rows):
        out["HRD_MONTHLY"] = {"form": "HRD_MONTHLY", **head, "levyBase": total("hrdBase"), "levy": total("hrd"),
                              "employeeCount": sum(1 for r in rows if r["hrd"])}
    return out


# ── records ─────────────────────────────────────────────────────────────────
def _model():
    return mys._models().PayrollMyFiling


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
    mys._audit(db, actor_id, "generated", "my_filing", row.id,
               new={"form": form_code, "period": key, "kind": kind, "version": version, "hash": digest})
    return row


def _refresh_draft(db: Session, row, payload, run_ids, due_on, actor_id):
    digest = canonical_hash(payload)
    row.payload, row.payload_hash, row.run_ids, row.due_on = payload, digest, run_ids, due_on
    row.idempotency_key = _idempotency_key(row.organization_id, row.legal_entity_id, row.form_code, row.period_key,
                                           row.subject_key, row.kind, row.version, row.corrects_id, digest)
    row.updated_at = datetime.utcnow()
    db.flush()
    mys._audit(db, actor_id, "regenerated", "my_filing", row.id, new={"hash": digest})
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
        return latest                                                     # nothing changed
    if latest.status == "DRAFT":
        return _refresh_draft(db, latest, payload, run_ids, due_on, actor_id)
    if latest.status == "APPROVED":
        latest.status = "SUPERSEDED"
        mys._audit(db, actor_id, "superseded", "my_filing", latest.id, new={"status": "SUPERSEDED"})
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
        return latest                                                     # no duplicate correction
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
def _entities(db: Session, items) -> list:
    from app.modules.payroll.models import PayrollEmployee

    return sorted({getattr(db.get(PayrollEmployee, i.employee_id), "legal_entity_id", None) for i in items},
                  key=lambda x: (x is not None, x or 0))


def build_my_run_filings(db: Session, run, actor_id) -> list:
    """At PAID: (re)build the monthly PCB / EPF / PERKESO-EIS / HRD payloads of
    the pay-date month for every legal employer in the run."""
    items = mys._run_items(db, run)
    if not items:
        return []
    key = period_key(run.pay_date)
    start, end = _month_bounds(key)
    out = []
    for entity in _entities(db, items):
        run_ids, month_items = _paid_items(db, run.organization_id, start, end, entity, extra_run=run)
        registration = _registration(db, run.organization_id, entity, end)
        payloads = _monthly_payloads(db, run.organization_id, key, entity, month_items, registration)
        for form in MONTHLY_FORMS:
            if form in payloads:
                due = pcb_due_on(db, run.organization_id, key) if form == "PCB_MONTHLY" else None
                out.append(upsert_filing(db, run.organization_id, entity, form, key, payloads[form], run_ids, due,
                                         actor_id))
    return out


def build_my_annual_filings(db: Session, organization_id: int, year: int, legal_entity_id, actor_id,
                            today: Optional[date] = None) -> list:
    """EA per employee, FORM_E and CP8D for a CLOSED year, from the PAID
    payslips; refused when the year-to-date ledger disagrees."""
    year = int(year)
    if (today or date.today()) <= date(year, 12, 31):
        _conflict("MY_TAX_YEAR_OPEN", f"{year} is not closed; annual forms are built after 31 December.")
    mys._legal_entity(db, organization_id, legal_entity_id)
    run_ids, items = _paid_items(db, organization_id, date(year, 1, 1), date(year, 12, 31), legal_entity_id)
    if not items:
        _conflict("MY_NO_PAID_PAYSLIPS", f"no PAID Malaysia payslips in {year} for this employer.")
    registration = _registration(db, organization_id, legal_entity_id, date(year, 12, 31))
    Entry = mys._models().PayrollMyAccumulatorEntry
    per = {}
    for _run, item, employee in items:
        mm = item_measures(item)
        e = per.setdefault(employee, {"gross": ZERO, "pcb": ZERO, "epf": ZERO, "socso": ZERO, "eis": ZERO,
                                      "items": []})
        e["gross"] += mm["gross"]
        e["pcb"] += mm["pcb"]
        e["epf"] += mm["epfEmployee"]
        e["socso"] += mm["socsoEmployee"]
        e["eis"] += mm["eisEmployee"]
        e["items"].append(item.id)
    out, cp8d = [], []
    ea_due = annual_due_on(db, organization_id, year, "my_ea_due")
    for employee in sorted(per, key=lambda x: x.id):
        e = per[employee]
        ledger = {}
        for accumulator, amount in (db.query(Entry.accumulator, Entry.amount)
                                    .filter(Entry.organization_id == organization_id, Entry.employee_id == employee.id,
                                            Entry.year == year, Entry.entry_kind == "RUN").all()):
            ledger[accumulator] = ledger.get(accumulator, ZERO) + _dec(amount)
        if ledger.get("PCB_PAID", ZERO) != e["pcb"]:
            _conflict("MY_LEDGER_MISMATCH", f"employee #{employee.id}: ledger PCB {_s(ledger.get('PCB_PAID', ZERO))} "
                      f"differs from the PAID payslips {_s(e['pcb'])}.")
        worker = _worker(db, organization_id, employee, date(year, 12, 31))
        payload = {"form": "EA", "year": year, "legalEntityId": legal_entity_id, "payer": _payer(registration),
                   "canonical": True, **worker, "payslipItemIds": e["items"], "grossRemuneration": _s(e["gross"]),
                   "pcb": _s(e["pcb"]), "epfEmployee": _s(e["epf"]), "socsoEmployee": _s(e["socso"]),
                   "eisEmployee": _s(e["eis"])}
        out.append(upsert_filing(db, organization_id, legal_entity_id, "EA", str(year), payload, run_ids, ea_due,
                                 actor_id, subject=f"E{employee.id}"))
        cp8d.append({k: payload[k] for k in ("employeeId", "nricVaultId", "nricMasked", "tinVaultId", "tinMasked",
                                             "grossRemuneration", "pcb", "epfEmployee")})
    form_e_due = annual_due_on(db, organization_id, year, "my_form_e_due")
    form_e = {"form": "FORM_E", "year": year, "legalEntityId": legal_entity_id, "payer": _payer(registration),
              "canonical": True, "employeeCount": len(per),
              "totalRemuneration": _s(sum((e["gross"] for e in per.values()), ZERO)),
              "totalPcb": _s(sum((e["pcb"] for e in per.values()), ZERO))}
    out.append(upsert_filing(db, organization_id, legal_entity_id, "FORM_E", str(year), form_e, run_ids, form_e_due,
                             actor_id))
    out.append(upsert_filing(db, organization_id, legal_entity_id, "CP8D", str(year),
                             {"form": "CP8D", "year": year, "legalEntityId": legal_entity_id,
                              "payer": _payer(registration), "canonical": True, "employees": cp8d},
                             run_ids, form_e_due, actor_id))
    return out


def build_my_event_filing(db: Session, organization_id: int, event_id: int, actor_id):
    """CP22 / CP22A / CP21 from a recorded employer event (its due date)."""
    from app.modules.payroll.models import PayrollEmployee

    event = mys._event(db, organization_id, event_id)
    if event.event_type not in EVENT_FORMS:
        _conflict("MY_FORM_OUT_OF_SCOPE", f"{event.event_type} has no HASiL form in release 1.")
    if event.status == "CANCELLED":
        raise BadRequestException("The event has been cancelled.")
    employee = db.get(PayrollEmployee, event.employee_id)
    entity = getattr(employee, "legal_entity_id", None)
    registration = _registration(db, organization_id, entity, event.event_date)
    payload = {"form": event.event_type, "eventId": event.id, "eventDate": event.event_date.isoformat(),
               "legalEntityId": entity, "payer": _payer(registration), "canonical": True,
               **_worker(db, organization_id, employee, event.event_date),
               "clearanceRequired": bool(event.clearance_required)}
    return upsert_filing(db, organization_id, entity, event.event_type, period_key(event.event_date), payload, None,
                         event.due_date, actor_id, subject=f"EV{event.id}")


def refuse_out_of_scope(form_code: str) -> None:
    form = str(form_code or "").strip().upper()
    if form in OUT_OF_SCOPE_FORMS:
        _conflict("MY_FORM_OUT_OF_SCOPE", OUT_OF_SCOPE_FORMS[form])


# ── workflow ────────────────────────────────────────────────────────────────
def _filing(db: Session, organization_id: int, filing_id: int):
    F = _model()
    row = db.query(F).filter(F.id == filing_id, F.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Malaysia filing")
    return row


def _verify_hash(row) -> None:
    if canonical_hash(row.payload) != row.payload_hash:
        _conflict("PAYLOAD_CHANGED_AFTER_APPROVAL", "the stored payload no longer matches its hash.")


def _period_date(row) -> date:
    key = row.period_key
    if len(key) == 4:
        return date(int(key), 12, 31)
    return _month_bounds(key)[1]


def approve_my_filing(db: Session, organization_id: int, filing_id: int, actor_id):
    """A second person approves a DRAFT, and only against an archived layout
    version of the form (MY-022)."""
    from app.modules.payroll.service import require_four_eyes

    row = _filing(db, organization_id, filing_id)
    if row.status != "DRAFT":
        raise BadRequestException("Only a DRAFT Malaysia filing can be approved.")
    version = schema_version(row.form_code, _period_date(row))
    if version is None:
        _conflict("FILING_SCHEMA_MISMATCH", f"no archived {row.form_code} layout is in the form catalogue; the "
                  "canonical payload can be previewed but not approved.")
    _verify_hash(row)
    require_four_eyes(row.created_by_id, actor_id, "Approving a Malaysia filing", db=db, entity_type="my_filing",
                      entity_id=row.id, current_status=row.status)
    row.status, row.schema_version = "APPROVED", version
    row.approved_by_id, row.approved_at = actor_id, datetime.utcnow()
    db.flush()
    mys._audit(db, actor_id, "approved", "my_filing", row.id, new={"status": "APPROVED", "schema": version})
    return row


def record_my_filing_submission(db: Session, organization_id: int, filing_id: int, submission_ref, actor_id):
    """Record that the APPROVED payload was submitted outside the platform
    (D-5). The same reference again is the same submission."""
    ref = str(submission_ref or "").strip()[:100]
    if not ref:
        raise BadRequestException("submissionRef is required.")
    row = _filing(db, organization_id, filing_id)
    if row.status in SUBMITTED_STATES or row.status == "REJECTED":
        if row.submission_ref == ref:
            return row                                                    # idempotent retry
        _conflict("MY_FILING_ALREADY_SUBMITTED", "this filing was already submitted under another reference.")
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED Malaysia filing can be submitted.")
    if schema_version(row.form_code, _period_date(row)) != row.schema_version:
        _conflict("FILING_SCHEMA_MISMATCH", "the approved layout version is no longer in force; approve again.")
    _verify_hash(row)
    row.status, row.submission_ref = "SUBMITTED", ref
    row.submitted_by_id, row.submitted_at = actor_id, datetime.utcnow()
    db.flush()
    mys._audit(db, actor_id, "submitted", "my_filing", row.id, new={"status": "SUBMITTED", "ref": ref})
    return row


def record_my_filing_response(db: Session, organization_id: int, filing_id: int, payload: dict, actor_id):
    """ACCEPTED (with the receipt reference) or REJECTED (with structured error
    codes). Never touches a settlement; a rejection leaves payroll unchanged."""
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
        _conflict("MY_FILING_ALREADY_ANSWERED", "the authority's response is already recorded.")
    if row.status != "SUBMITTED":
        raise BadRequestException("Only a SUBMITTED Malaysia filing can receive the authority's response.")
    row.status, row.receipt_ref, row.responded_at = outcome, receipt, datetime.utcnow()
    row.rejection = {"codes": codes, "message": str(payload.get("message") or "")[:300] or None} if codes else None
    if outcome == "ACCEPTED" and row.kind == "CORRECTION" and row.corrects_id:
        original = db.get(_model(), row.corrects_id)
        if original is not None and original.status == "ACCEPTED":
            original.status = "CORRECTED"
    db.flush()
    mys._audit(db, actor_id, "responded", "my_filing", row.id, new={"status": outcome, "errors": codes})
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


def list_my_filings(db: Session, organization_id: int, period=None, form_code=None, status=None) -> list:
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


def get_my_filing(db: Session, organization_id: int, filing_id: int) -> dict:
    return filing_view(_filing(db, organization_id, filing_id), include_payload=True)
