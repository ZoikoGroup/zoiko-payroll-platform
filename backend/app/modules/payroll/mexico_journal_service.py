"""
modules/payroll/mexico_journal_service.py
-----------------------------------------
Mexico Phase 10b (docs/mexico/MEXICO_PHASE_10_PLAN.md D6): the payroll journal.

  * the JOURNAL of a committed Mexican run, built from the committed payslip
    snapshots only (the same amounts the Phase 8 authority ledger trusts):
    gross wages by earning kind, the employer's IMSS / INFONAVIT / ISN cost,
    and every liability — net pay, SAT ISR, IMSS employee and employer,
    INFONAVIT housing and credit, ISN per state — each on its OWN line, never
    netted against another (§20). A CORRECTION run journals its deltas
    (corrected − original), so a negative line flips to the other side.
  * it must BALANCE: total debits = total credits. Employee deductions Zoiko
    does not compute (gross − net − ISR − employee side > 0) go to
    OTHER_DEDUCTIONS_PAYABLE; anything that cannot balance refuses the export
    (MX_JOURNAL_UNBALANCED) — never a plug line.
  * the ACCOUNT MAPPING is the employer's own chart of accounts: versioned,
    approved by someone other than its maker (four-eyes); approving a version
    supersedes the previous one. A line type without an account refuses the
    export (MX_JOURNAL_ACCOUNT_UNMAPPED).
  * the EXPORT is a CSV built on request and recorded (mapping version, totals,
    hash); nothing is posted to any ledger or ERP. It aggregates by line type
    and registration / state — no worker appears in it.
  * a CURRENT export refuses the run's reset (it may already be in the
    employer's ledger): void it first, with a reason, once it is reversed or
    was never posted. A reset is not how a committed run is fixed anyway — a
    correction run is.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.engine.countries.mexico import MXBlock

_ZERO = Decimal("0")
_CENT = Decimal("0.01")
JOURNAL_BANNER = "ZOIKO PAYROLL JOURNAL - NOT POSTED TO ANY LEDGER - import or key it into your accounting system"

# (line type, natural side, what it carries). The order is the export order.
LINE_TYPES = (
    ("WAGES_EXPENSE", "DEBIT", "Gross earnings, by earning kind"),
    ("IMSS_EMPLOYER_EXPENSE", "DEBIT", "Employer IMSS contributions (incl. CEAV), by registration"),
    ("INFONAVIT_EMPLOYER_EXPENSE", "DEBIT", "Employer INFONAVIT housing contribution, by registration"),
    ("ISN_EXPENSE", "DEBIT", "State payroll tax (ISN), by state"),
    ("NET_PAY_PAYABLE", "CREDIT", "Net pay owed to workers"),
    ("ISR_PAYABLE", "CREDIT", "ISR withheld, owed to SAT"),
    ("IMSS_EMPLOYEE_PAYABLE", "CREDIT", "Worker IMSS contributions withheld, by registration"),
    ("IMSS_EMPLOYER_PAYABLE", "CREDIT", "Employer IMSS contributions owed, by registration"),
    ("INFONAVIT_EMPLOYER_PAYABLE", "CREDIT", "Employer INFONAVIT housing owed, by registration"),
    ("INFONAVIT_CREDIT_PAYABLE", "CREDIT", "INFONAVIT credit withheld from workers, by registration"),
    ("ISN_PAYABLE", "CREDIT", "State payroll tax (ISN) owed, by state"),
    ("OTHER_DEDUCTIONS_PAYABLE", "CREDIT", "Other employee deductions (not computed by the Mexican engine)"),
)
_SIDE = {code: side for code, side, _ in LINE_TYPES}
_ORDER = {code: n for n, (code, _, _) in enumerate(LINE_TYPES)}
_ACCOUNT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,39}$")
_KIND = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")


def _journal_models():
    from app.modules.payroll import models as m

    return m


def _jdec(value) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _journal_audit(db, **kw):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, **kw)


def _journal_guard(db: Session, org_id: int) -> None:
    from app.modules.payroll import mexico_filing_service

    mexico_filing_service.guard(db, org_id)


# ── the account mapping (versioned, four-eyes) ──────────────────────────────

def line_types() -> list:
    return [{"code": c, "side": s, "description": d} for c, s, d in LINE_TYPES]


def _clean_accounts(raw) -> dict:
    """{line type (or WAGES_EXPENSE:<KIND>): account code}. Unknown keys and
    malformed codes are refused; blanks are dropped."""
    if not isinstance(raw, dict) or not raw:
        raise BadRequestException("accounts must map line types to account codes")
    out, bad = {}, []
    for key, value in raw.items():
        key, code = str(key).strip(), str(value or "").strip()
        if not code:
            continue
        base, _, kind = key.partition(":")
        if base not in _SIDE or (kind and (base != "WAGES_EXPENSE" or not _KIND.match(kind))):
            bad.append(f"unknown line type {key!r}")
        elif not _ACCOUNT.match(code):
            bad.append(f"{key}: account code {code!r} (1-40 letters, digits, space . _ : / -)")
        else:
            out[key] = code
    if bad:
        raise BadRequestException("; ".join(bad))
    if not out:
        raise BadRequestException("the mapping has no account")
    return out


def _journal_mapping(db: Session, org_id: int, mapping_id: int):
    row = db.get(_journal_models().PayrollMxJournalMapping, mapping_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Journal mapping {mapping_id} not found")
    return row


def approved_mapping(db: Session, org_id: int):
    M = _journal_models().PayrollMxJournalMapping
    return (db.query(M).filter(M.organization_id == org_id, M.status == "APPROVED")
            .order_by(M.version.desc()).first())


def create_mapping(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    _journal_guard(db, org_id)
    M = _journal_models().PayrollMxJournalMapping
    accounts = _clean_accounts((data or {}).get("accounts"))
    if db.query(M).filter(M.organization_id == org_id, M.status == "DRAFT").first() is not None:
        raise BadRequestException("a draft mapping already exists — approve or withdraw it first")
    last = db.query(M).filter(M.organization_id == org_id).order_by(M.version.desc()).first()
    row = M(organization_id=org_id, version=(last.version + 1) if last else 1, status="DRAFT", accounts=accounts,
            note=((data or {}).get("note") or "").strip()[:300] or None, maker_id=actor_id)
    db.add(row)
    db.flush()
    _journal_audit(db, actor_id=actor_id, action="create_journal_mapping", entity_type="mx_journal_mapping",
                   entity_id=row.id, new={"version": row.version, "accounts": len(accounts)})
    db.commit()
    return journal_mapping_view(row)


def approve_mapping(db: Session, org_id: int, mapping_id: int, actor_id: Optional[int]) -> dict:
    _journal_guard(db, org_id)
    row = _journal_mapping(db, org_id, mapping_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT mapping can be approved (this one is {row.status})")
    if actor_id is not None and actor_id == row.maker_id:
        raise MXBlock("MX_FOUR_EYES_REQUIRED", "a journal mapping must be approved by someone other than its maker",
                      org_id)
    previous = approved_mapping(db, org_id)
    if previous is not None:
        previous.status = "SUPERSEDED"
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.now(timezone.utc)
    _journal_audit(db, actor_id=actor_id, action="approve_journal_mapping", entity_type="mx_journal_mapping",
                   entity_id=row.id, new={"version": row.version,
                                          "supersedes": previous.version if previous is not None else None})
    db.commit()
    return journal_mapping_view(row)


def withdraw_mapping(db: Session, org_id: int, mapping_id: int, actor_id: Optional[int]) -> dict:
    _journal_guard(db, org_id)
    row = _journal_mapping(db, org_id, mapping_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT mapping can be withdrawn (this one is {row.status})")
    row.status = "WITHDRAWN"
    _journal_audit(db, actor_id=actor_id, action="withdraw_journal_mapping", entity_type="mx_journal_mapping",
                   entity_id=row.id, new={"version": row.version})
    db.commit()
    return journal_mapping_view(row)


def list_mappings(db: Session, org_id: int) -> list:
    _journal_guard(db, org_id)
    M = _journal_models().PayrollMxJournalMapping
    return [journal_mapping_view(r) for r in
            db.query(M).filter(M.organization_id == org_id).order_by(M.version.desc())]


def account_for(accounts: dict, line_type: str, dimension: str) -> Optional[str]:
    if line_type == "WAGES_EXPENSE" and dimension:
        override = accounts.get(f"WAGES_EXPENSE:{dimension}")
        if override:
            return override
    return accounts.get(line_type)


# ── the journal of a run ────────────────────────────────────────────────────

def _journal_run(db: Session, org_id: int, run_id: int):
    run = db.get(_journal_models().PayrollRun, run_id)
    if run is None or run.organization_id != org_id:
        raise NotFoundException(f"Payroll run {run_id} not found")
    if not (run.mx_approval_fingerprint or {}).get("committedAt"):
        raise BadRequestException("Only a committed (approved) run has a journal")
    return run


def _registration_label(db: Session, employee_id: int, on) -> str:
    from app.modules.payroll import mexico_filing_service

    reg = mexico_filing_service.registration_for(db, employee_id, on)
    return reg.registro_patronal if reg is not None else "NO-REGISTRATION"


def _payslip_amounts(res: dict, net) -> dict:
    """The journal figures of one committed snapshot (unsigned, as charged)."""
    kinds = defaultdict(lambda: _ZERO)
    for c in res.get("concepts") or []:
        kinds[str(c.get("kind") or "OTHER")] += _jdec(c.get("gross"))
    isn = res.get("isn") or {}
    return {"gross": _jdec(res.get("gross")), "kinds": kinds, "net": _jdec(net),
            "isr": _jdec(res.get("isr_withheld")), "imss_ee": _jdec(res.get("imss_employee")),
            "imss_er": _jdec(res.get("imss_employer")), "housing": _jdec(res.get("infonavit_employer")),
            "credit": _jdec(res.get("infonavit_credit")), "isn": _jdec(isn.get("amount")),
            "state": str(isn.get("state") or "NO-STATE")}


def _post_payslip(acc: dict, amounts: dict, reg: str, sign: int, item_id: int) -> None:
    """Add one payslip's figures (sign -1 removes an original's) to `acc`."""
    a = amounts
    if sum(a["kinds"].values(), _ZERO) != a["gross"]:
        raise MXBlock("MX_JOURNAL_UNBALANCED",
                      f"payslip {item_id}: its earning lines do not add up to its gross {a['gross']}")
    for kind, amount in a["kinds"].items():
        acc[("WAGES_EXPENSE", kind)] += sign * amount
    acc[("IMSS_EMPLOYER_EXPENSE", reg)] += sign * a["imss_er"]
    acc[("IMSS_EMPLOYER_PAYABLE", reg)] += sign * a["imss_er"]
    acc[("INFONAVIT_EMPLOYER_EXPENSE", reg)] += sign * a["housing"]
    acc[("INFONAVIT_EMPLOYER_PAYABLE", reg)] += sign * a["housing"]
    acc[("ISN_EXPENSE", a["state"])] += sign * a["isn"]
    acc[("ISN_PAYABLE", a["state"])] += sign * a["isn"]
    acc[("NET_PAY_PAYABLE", "")] += sign * a["net"]
    acc[("ISR_PAYABLE", "")] += sign * a["isr"]
    acc[("IMSS_EMPLOYEE_PAYABLE", reg)] += sign * a["imss_ee"]
    acc[("INFONAVIT_CREDIT_PAYABLE", reg)] += sign * a["credit"]
    other = a["gross"] - a["net"] - a["isr"] - a["imss_ee"] - a["credit"]
    if other < 0:
        raise MXBlock("MX_JOURNAL_UNBALANCED",
                      f"payslip {item_id}: net pay {a['net']} is more than gross less its deductions — the journal "
                      f"cannot balance", None)
    acc[("OTHER_DEDUCTIONS_PAYABLE", "")] += sign * other


def journal_lines(db: Session, run) -> list:
    """[{lineType, dimension, side, amount}] of a committed run, aggregated;
    zero lines dropped. A CORRECTION run posts corrected − original."""
    from app.modules.payroll import mexico_correction_service as corrections
    from app.modules.payroll import mexico_run_service

    is_correction = (run.mx_run_type or "ORDINARY") == "CORRECTION"
    acc = defaultdict(lambda: _ZERO)
    for item in mexico_run_service._mx_items(db, run):
        snap = item.mx_calculation_snapshot or {}
        if snap.get("blocked") or not snap.get("result"):
            raise MXBlock("MX_JOURNAL_BLOCKED_ITEM", f"payslip {item.id} has no committed calculation",
                          run.organization_id)
        reg = _registration_label(db, item.employee_id, run.pay_date)
        _post_payslip(acc, _payslip_amounts(corrections.result_of(item), item.net_pay), reg, 1, item.id)
        if is_correction:
            original = corrections.original_item_for(db, item)
            if original is None:
                raise MXBlock("MX_JOURNAL_BLOCKED_ITEM", f"correction payslip {item.id} has no original",
                              run.organization_id)
            _post_payslip(acc, _payslip_amounts(corrections.result_of(original), original.net_pay), reg, -1,
                          original.id)
    out = []
    for (line_type, dimension), amount in acc.items():
        amount = _cents(amount)
        if amount == 0:
            continue
        side = _SIDE[line_type]
        if amount < 0:                       # a negative delta reverses the line's natural side
            side, amount = ("CREDIT" if side == "DEBIT" else "DEBIT"), -amount
        out.append({"lineType": line_type, "dimension": dimension, "side": side, "amount": amount})
    out.sort(key=lambda r: (_ORDER[r["lineType"]], r["dimension"]))
    return out


def _totals(lines: list) -> tuple:
    debit = sum((l["amount"] for l in lines if l["side"] == "DEBIT"), _ZERO)
    credit = sum((l["amount"] for l in lines if l["side"] == "CREDIT"), _ZERO)
    return debit, credit


def run_journal(db: Session, org_id: int, run_id: int) -> dict:
    """The preview: every line with its account under the APPROVED mapping (or
    None), the totals, and what would refuse the export."""
    _journal_guard(db, org_id)
    run = _journal_run(db, org_id, run_id)
    lines = journal_lines(db, run)
    mapping = approved_mapping(db, org_id)
    accounts = mapping.accounts if mapping is not None else {}
    debit, credit = _totals(lines)
    unmapped = sorted({l["lineType"] for l in lines if not account_for(accounts, l["lineType"], l["dimension"])})
    problems = []
    if mapping is None:
        problems.append({"code": "MX_JOURNAL_MAPPING_MISSING", "message": "no approved account mapping"})
    elif unmapped:
        problems.append({"code": "MX_JOURNAL_ACCOUNT_UNMAPPED", "message": "no account for " + ", ".join(unmapped)})
    if debit != credit:
        problems.append({"code": "MX_JOURNAL_UNBALANCED", "message": f"debits {debit} ≠ credits {credit}"})
    E = _journal_models().PayrollMxJournalExport
    exports = db.query(E).filter(E.payroll_run_id == run.id).order_by(E.id.desc()).all()
    return {"runId": run.id, "runType": run.mx_run_type or "ORDINARY", "periodLabel": run.period_label,
            "payDate": run.pay_date.isoformat() if run.pay_date else None,
            "mappingId": mapping.id if mapping is not None else None,
            "mappingVersion": mapping.version if mapping is not None else None,
            "lines": [{**l, "amount": str(l["amount"]),
                       "account": account_for(accounts, l["lineType"], l["dimension"])} for l in lines],
            "debitTotal": str(debit), "creditTotal": str(credit), "balanced": debit == credit,
            "problems": problems, "exports": [journal_export_view(e) for e in exports]}


def export_journal(db: Session, org_id: int, run_id: int, actor_id: Optional[int]) -> dict:
    """The CSV of a committed run under the APPROVED mapping, recorded with its
    hash. Refused unless every line has an account and the journal balances."""
    _journal_guard(db, org_id)
    run = _journal_run(db, org_id, run_id)
    mapping = approved_mapping(db, org_id)
    if mapping is None:
        raise MXBlock("MX_JOURNAL_MAPPING_MISSING", "approve an account mapping before exporting a journal", org_id)
    lines = journal_lines(db, run)
    if not lines:
        raise BadRequestException("the run has no amount to journal")
    unmapped = sorted({l["lineType"] for l in lines if not account_for(mapping.accounts, l["lineType"],
                                                                       l["dimension"])})
    if unmapped:
        raise MXBlock("MX_JOURNAL_ACCOUNT_UNMAPPED",
                      f"mapping v{mapping.version} has no account for {', '.join(unmapped)}", org_id)
    debit, credit = _totals(lines)
    if debit != credit:
        raise MXBlock("MX_JOURNAL_UNBALANCED", f"debits {debit} ≠ credits {credit}", org_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    from app.modules.payroll import mexico_pilot_service

    w.writerow([mexico_pilot_service.PILOT_JOURNAL_BANNER if mexico_pilot_service.run_is_pilot(run) else JOURNAL_BANNER])
    w.writerow([f"run {run.id}", run.mx_run_type or "ORDINARY", run.period_label or "",
                run.pay_date.isoformat() if run.pay_date else "", f"mapping v{mapping.version}", "MXN"])
    w.writerow(["line_type", "dimension", "account", "debit", "credit"])
    for l in lines:
        amount = str(l["amount"])
        w.writerow([l["lineType"], l["dimension"], account_for(mapping.accounts, l["lineType"], l["dimension"]),
                    amount if l["side"] == "DEBIT" else "", amount if l["side"] == "CREDIT" else ""])
    w.writerow(["TOTAL", "", "", str(debit), str(credit)])
    content = buf.getvalue()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    E = _journal_models().PayrollMxJournalExport
    row = E(organization_id=org_id, payroll_run_id=run.id, mapping_id=mapping.id, status="CURRENT",
            line_count=len(lines), debit_total=debit, credit_total=credit, file_sha256=digest, created_by_id=actor_id)
    db.add(row)
    db.flush()
    _journal_audit(db, actor_id=actor_id, action="export_journal", entity_type="mx_journal_export", entity_id=row.id,
                   new={"runId": run.id, "mappingVersion": mapping.version, "sha256": digest, "lines": len(lines)})
    db.commit()
    return {"id": row.id, "filename": f"zoiko-mx-journal-run-{run.id}-v{mapping.version}.csv", "content": content,
            "sha256": digest}


def void_export(db: Session, org_id: int, export_id: int, reason: str, actor_id: Optional[int]) -> dict:
    _journal_guard(db, org_id)
    row = db.get(_journal_models().PayrollMxJournalExport, export_id)
    if row is None or row.organization_id != org_id:
        raise NotFoundException(f"Journal export {export_id} not found")
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("Voiding a journal export needs a reason (e.g. reversed in the ledger)")
    if row.status != "CURRENT":
        raise BadRequestException(f"the export is already {row.status}")
    row.status, row.voided_reason, row.voided_by_id = "VOIDED", text[:300], actor_id
    _journal_audit(db, actor_id=actor_id, action="void_journal_export", entity_type="mx_journal_export",
                   entity_id=row.id, reason=text[:300])
    db.commit()
    return journal_export_view(row)


# ── the run's reset (Phase 6 rule) ──────────────────────────────────────────

def downstream_reasons(db: Session, run) -> list:
    """A CURRENT journal export refuses the run's reset — void it first."""
    E = _journal_models().PayrollMxJournalExport
    return [f"journal export {e.id} is CURRENT (void it once reversed in the ledger)" for e in
            db.query(E).filter(E.payroll_run_id == run.id, E.status == "CURRENT").order_by(E.id)]


# ── views ───────────────────────────────────────────────────────────────────

def journal_mapping_view(row) -> dict:
    return {"id": row.id, "version": row.version, "status": row.status, "accounts": dict(row.accounts or {}),
            "note": row.note, "makerId": row.maker_id, "approvedById": row.approved_by_id,
            "approvedAt": row.approved_at.isoformat() if row.approved_at else None}


def journal_export_view(row) -> dict:
    return {"id": row.id, "runId": row.payroll_run_id, "mappingId": row.mapping_id, "status": row.status,
            "lineCount": row.line_count, "debitTotal": str(row.debit_total), "creditTotal": str(row.credit_total),
            "sha256": row.file_sha256, "createdById": row.created_by_id,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "voidedReason": row.voided_reason}
