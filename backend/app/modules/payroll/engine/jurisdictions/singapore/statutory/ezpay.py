"""
engine/jurisdictions/singapore/statutory/ezpay.py
-------------------------------------------------
CPF EZPay (FTP) contribution file — CPF Board "CPF EZPay (FTP) File
Specifications (effective from 16 January 2025)", FTPSPEC/FILESPEC, last
updated Jan 2025, 7 pages (retrieved 2026-09-24, sha256 1ddd242b7893d37b…).
Every layout rule below cites that document's page.

The file is PREPARED here and submitted by the employer through CPF EZPay
(Corppass) — ZP-SG-ENG-001 SG-028: no direct API is claimed. Pure: no
database; service.py assembles the inputs and persists only a masked
summary plus the file's SHA-256 (the file itself carries full CPF account
numbers, as the format requires, and is rebuilt on an authorised download).

Layout (p1): fixed-length 150-byte records. One payment advice =
  1 Employer Header record (p2), 1+ Employer Contribution Summary records
  (p3), 0+ Employer Contribution Detail records (p4–5), 1 Employer Trailer
  record (p6). Filename "<CSN><Month Paid><Advice Code>.DTL", e.g.
  "234567891APTE01JAN202201.DTL" (p1).
Notes (p6): no negative amounts; the characters _+$<>:;?!=[]`^|"~ are not
allowed; unused numeric fields zero-padded; CPF account numbers begin with
S or T.
"""

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

RECORD_LENGTH = 150
FORBIDDEN_CHARACTERS = set('_+$<>:;?!=[]`^|"~')
_Z = Decimal("0")

# p3 — payment codes of the Contribution Summary record.
PAYMENT_CODES = {
    "CPF": "01", "MBMF": "02", "SINDA": "03", "CDAC": "04", "ECF": "05",
    "CPF_PENALTY_INTEREST": "07", "COMMUNITY_CHEST": "10", "SDL": "11",
}
SHG_PAYMENT_CODES = {"MBMF": "02", "SINDA": "03", "CDAC": "04", "ECF": "05"}
# p3 — donor count is populated only for these codes; zero otherwise.
_DONOR_COUNT_CODES = {"02", "03", "04", "05", "10"}
# p3 — voluntary-contribution CSNs are rejected if they carry 02–11.
VOLUNTARY_PAYMENT_TYPES = ("VCT", "AMS", "MSE")
EMPLOYMENT_STATUSES = ("E", "L", "N", "O")      # p5


class EzpayValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def _num(amount, int_digits, dec_digits=2) -> str:
    """9(n)V99 — implied decimal, zero-padded, no sign (p4, p6 note 3)."""
    value = Decimal(str(amount or 0)).quantize(Decimal(1).scaleb(-dec_digits), rounding=ROUND_HALF_UP)
    if value < 0:
        raise EzpayValidationError([f"negative amount {value} (CPF EZPay spec p6 note 2)"])
    digits = str(int(value.scaleb(dec_digits)))
    if len(digits) > int_digits + dec_digits:
        raise EzpayValidationError([f"amount {value} exceeds 9({int_digits})V9{dec_digits}"])
    return digits.rjust(int_digits + dec_digits, "0")


def _x(value, length) -> str:
    """X(n) — left-justified, space-padded."""
    text = "" if value is None else str(value)
    if len(text) > length:
        raise EzpayValidationError([f"value {text!r} longer than X({length})"])
    return text.ljust(length)


def _prefix(record_type, csn, advice_code) -> str:
    """Columns 1–20 common to every record: submission mode F (file
    transfer), record type, UEN/NRIC/FIN X(10), payment type X(3), Sno
    X(2), filler, advice code X(2)."""
    uen, payment_type, sno = csn
    return "F" + record_type + _x(uen, 10) + _x(payment_type, 3) + _x(sno, 2) + " " + _x(advice_code, 2)


def month_paid_label(relevant_month: str) -> str:
    """'2026-05' → 'MAY2026' (filename 'Month Paid', p1 example JAN2022)."""
    year, month = relevant_month.split("-")
    return datetime(int(year), int(month), 1).strftime("%b%Y").upper()


def filename(csn, relevant_month: str, advice_code: str) -> str:
    uen, payment_type, sno = csn
    return f"{uen}{payment_type}{sno}{month_paid_label(relevant_month)}{advice_code}.DTL"


def employment_status(date_of_joining, date_of_leaving, month_start, month_end) -> str:
    """p5: E existing (or leaves and re-joins in the month), L leaver, N new
    joiner, O joins and leaves in the same month."""
    joined = date_of_joining is not None and month_start <= date_of_joining <= month_end
    left = date_of_leaving is not None and month_start <= date_of_leaving <= month_end
    if joined and left:
        return "O" if date_of_joining <= date_of_leaving else "E"
    return "N" if joined else ("L" if left else "E")


def build_file(csn, advice_code: str, relevant_month: str, created_at: datetime, employees: list, sdl_total) -> dict:
    """employees: [{account_no, name, cpf_total, ordinary_wages,
    additional_wages, employment_status, shg: {fund: amount}}]. Returns
    {"filename", "content", "records", "summary": {code: {amount, donors}},
    "total"} or raises EzpayValidationError with every problem found."""
    errors = []
    uen, payment_type, sno = csn
    if payment_type in VOLUNTARY_PAYMENT_TYPES:
        errors.append(f"CSN payment type {payment_type} is a voluntary-contribution CSN — SHG/SDL cannot be paid "
                      "with it (spec p3); use the mandatory CSN")
    if not re.fullmatch(r"\d{2}", advice_code or "") or advice_code == "00":
        errors.append("advice code must be 01–99 (spec p2)")
    if not re.fullmatch(r"\d{4}-\d{2}", relevant_month or ""):
        errors.append("relevant month must be YYYY-MM")
    yyyymm = (relevant_month or "").replace("-", "")

    details, summary = [], {}

    def add_summary(code, amount, donor=False):
        entry = summary.setdefault(code, {"amount": _Z, "donors": 0})
        entry["amount"] += Decimal(str(amount))
        entry["donors"] += 1 if donor else 0

    add_summary(PAYMENT_CODES["CPF"], _Z)
    for e in employees:
        who = e.get("employee_ref") or "employee"
        acct = (e.get("account_no") or "").strip().upper()
        name = (e.get("name") or "").strip().upper()
        if not re.fullmatch(r"[ST]\d{7}[A-Z]", acct):
            errors.append(f"{who}: CPF account number must be 9 characters beginning with S or T (spec p4, note 4)")
        if not name:
            errors.append(f"{who}: employee name is required (spec p5)")
        elif len(name) > 66:
            errors.append(f"{who}: name longer than 66 characters (X(66), spec p5) — never truncated silently")
        if FORBIDDEN_CHARACTERS & set(name):
            errors.append(f"{who}: name contains a character not allowed in the file (spec p6 note 2)")
        status = e.get("employment_status")
        if status not in EMPLOYMENT_STATUSES:
            errors.append(f"{who}: employment status must be E/L/N/O (spec p5)")
        for field in ("cpf_total", "ordinary_wages", "additional_wages"):
            if Decimal(str(e.get(field) or 0)) < 0:
                errors.append(f"{who}: negative {field} is not allowed (spec p5, p6 note 2)")
        cpf_total = Decimal(str(e.get("cpf_total") or 0))
        if cpf_total > 0:
            details.append(("01", acct, cpf_total, e.get("ordinary_wages"), e.get("additional_wages"), status, name))
            add_summary("01", cpf_total)
        for fund, amount in sorted((e.get("shg") or {}).items()):
            amount = Decimal(str(amount or 0))
            if amount <= 0:
                continue
            code = SHG_PAYMENT_CODES.get(fund)
            if code is None:
                errors.append(f"{who}: unknown SHG fund {fund!r}")
                continue
            # p4–5: SHG detail records carry zero wages and a space status.
            details.append((code, acct, amount, _Z, _Z, " ", name))
            add_summary(code, amount, donor=True)
    sdl_total = Decimal(str(sdl_total or 0))
    if sdl_total < 0:
        errors.append("negative SDL total")
    add_summary(PAYMENT_CODES["SDL"], sdl_total)
    # Community Chest (10) is not collected by this payroll; the zero summary
    # record mirrors the specification's own sample layout (p7).
    add_summary(PAYMENT_CODES["COMMUNITY_CHEST"], _Z)
    if errors:
        raise EzpayValidationError(errors)

    try:
        records = [_prefix(" ", csn, advice_code) + created_at.strftime("%Y%m%d") + created_at.strftime("%H%M%S")
                   + _x("FTP.DTL", 13) + " " * 103]                                       # p2 header
        for code in sorted(summary):                                                      # p3 summaries
            entry = summary[code]
            donors = entry["donors"] if code in _DONOR_COUNT_CODES else 0
            records.append(_prefix("0", csn, advice_code) + yyyymm + code + _num(entry["amount"], 10)
                           + str(donors).rjust(7, "0") + " " * 103)
        for code, acct, amount, ow, aw, status, name in sorted(details, key=lambda d: (d[1], d[0])):   # p4–5 details
            records.append(_prefix("1", csn, advice_code) + yyyymm + code + _x(acct, 9) + _num(amount, 10)
                           + _num(ow, 8) + _num(aw, 8) + _x(status, 1) + _x(name, 66) + " " * 14)
        total = sum((e["amount"] for e in summary.values()), _Z)
        records.append(_prefix("9", csn, advice_code) + str(len(records) + 1).rjust(7, "0")
                       + _num(total, 13) + " " * 108)                                     # p6 trailer
    except EzpayValidationError:
        raise
    problems = validate_records(records)
    if problems:
        raise EzpayValidationError(problems)
    return {
        "filename": filename(csn, relevant_month, advice_code),
        "content": "\r\n".join(records) + "\r\n",
        "records": len(records),
        "summary": {code: {"amount": str(v["amount"]), "donors": v["donors"] if code in _DONOR_COUNT_CODES else 0}
                    for code, v in sorted(summary.items())},
        "total": str(total),
        "detailRecords": len(details),
    }


def validate_records(records: list) -> list:
    """Independent structural check of a built file (spec p1–p6)."""
    problems = []
    if not records or records[0][1] != " " or records[-1][1] != "9":
        problems.append("file must start with an Employer Header and end with an Employer Trailer record")
    for n, r in enumerate(records, start=1):
        if len(r) != RECORD_LENGTH:
            problems.append(f"record {n}: length {len(r)} ≠ {RECORD_LENGTH}")
        if r[0] != "F":
            problems.append(f"record {n}: submission mode must be F")
        if FORBIDDEN_CHARACTERS & set(r):
            problems.append(f"record {n}: contains a forbidden character")
    if records and records[-1][1] == "9":
        trailer = records[-1]
        if int(trailer[20:27]) != len(records):
            problems.append("trailer record count does not equal the number of records")
        summary_total = sum(int(r[28:40]) for r in records if r[1] == "0")
        if int(trailer[27:42]) != summary_total:
            problems.append("trailer contribution amount does not equal the sum of the summary records")
    return problems
