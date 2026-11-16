"""Belgium (ZP-BE-ENG-001) Block M-ECWC: the ONSS rate table — governed by Super Admins, read by the engine.

Owner decisions (2026-11-16):
  * storage: payroll_be_onss_rates + payroll_be_onss_code_combinations (+ the rate file and the type rules);
  * signing is hybrid: a reviewer ATTESTS that the archived quarterly ZIP (checksum-bound) is the genuine ONSS
    publication (authenticity, not values); real four-eyes SIGNING applies to the rows of the supported subset only.
    The engine uses a row only when BOTH the file is attested AND the row is signed;
  * scope: the whole file is loaded as REFERENCE data (cross-checking, future expansion — never read by the engine);
    only the subset marked live (supported employer categories / worker codes + the combined codes in use) becomes
    signable content;
  * ContributionType (DmfA glossary zone 00083) is selected per code by SIGNED type rules over the employer facts
    (closure-fund sector, workforce class, wage-moderation status — each with evidence) and the worker's 100 / 108 %
    pay basis — never a default in code.

Lifecycle: register (reads the ARCHIVED source file, verifies its checksum, loads every record as REFERENCE) →
attest (another Super Admin) → mark the supported subset live (PENDING) → sign each row / combination (another
Super Admin than the one who marked it live and the registrar). Type rules: add (PENDING) → sign (another person).
Every code is TEXT ("000", "015"), never a number. Only Draft packs take new rate files and rules.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as be

_CODE = re.compile(r"^[0-9]{3}$")              # ONSS employer category / worker / contribution code shape (text)
_QUARTER = re.compile(r"^[0-9]{5}$")           # rate file header <Quarter>, e.g. 20263
_KINDS = {"WorkerCode": "WORKER", "ContributionWorkerCode": "CONTRIBUTION", "UnrelatedWorkerCode": "UNRELATED"}
LIVE, SIGNED, REFERENCE = "PENDING", "SIGNED", "REFERENCE"


def _models():
    from app.modules.payroll import models

    return models


def _content():
    from app.modules.payroll.engine.countries import belgium_content

    return belgium_content


def _reason(reason) -> str:
    text = " ".join(str(reason or "").split())
    if not text:
        raise BadRequestException("A reason is required.")
    return text[:300]


def _day(value, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        raise BadRequestException(f"{name} must be an ISO date (YYYY-MM-DD).")


def _draft_belgian_pack(db: Session, pack_row_id: int):
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, int(pack_row_id))
    if pack is None or str(pack.jurisdiction_country or "").upper() not in ("BE", "BELGIUM"):
        raise NotFoundException("Belgian pack")
    if pack.status != "Draft":
        raise BadRequestException(f"{pack.pack_id} is {pack.status}: rate files and type rules are added to a Draft "
                                  "pack only.")
    return pack


# ── the official file (parsed read-only; never unpacked to disk) ──────────────
def _xml(data: bytes):
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
    return etree.fromstring(data, parser)


def _decimal(text) -> Optional[Decimal]:
    if text in (None, ""):
        return None
    try:
        return Decimal(str(text))
    except InvalidOperation:
        raise BadRequestException(f"the rate file holds a malformed number: {str(text)[:20]!r}")


def be_onss_parse_rate_zip(data: bytes) -> dict:
    """{"quarter", "rates": [...], "combinations": [...]} from an ONSS DmfA rate ZIP (NOSSContributionRate_*.xml and
    NOSSWorkerAndContributionComb_*.xml). Codes stay text exactly as published."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BadRequestException("The source is not an ONSS rate ZIP.")
    names = {n.split("_")[0]: n for n in archive.namelist() if n.lower().endswith(".xml")}
    if "NOSSContributionRate" not in names or "NOSSWorkerAndContributionComb" not in names:
        raise BadRequestException("The ZIP lacks NOSSContributionRate / NOSSWorkerAndContributionComb XML files.")
    rates_root = _xml(archive.read(names["NOSSContributionRate"]))
    comb_root = _xml(archive.read(names["NOSSWorkerAndContributionComb"]))
    quarter = (rates_root.findtext("Header/Quarter") or "").strip()
    if not _QUARTER.fullmatch(quarter) or (comb_root.findtext("Header/Quarter") or "").strip() != quarter:
        raise BadRequestException("The rate files do not carry one consistent <Quarter> header.")
    rates = []
    for rec in rates_root.findall("ContributionRate"):
        code_el = next((c for c in rec if c.tag in _KINDS), None)
        ec, ctype = (rec.findtext("EmployerClass") or "").strip(), (rec.findtext("ContributionType") or "").strip()
        if code_el is None or not _CODE.fullmatch(ec) or not _CODE.fullmatch((code_el.text or "").strip()) \
                or not _content().CONTRIBUTION_TYPE_PATTERN.fullmatch(ctype):
            raise BadRequestException("A ContributionRate record does not have the published code shapes.")
        rates.append({"employerClass": ec, "codeKind": _KINDS[code_el.tag], "code": code_el.text.strip(),
                      "contributionType": ctype, "personalRate": _decimal(rec.findtext("PersonalRate")),
                      "employerRate": _decimal(rec.findtext("EmployerRate")),
                      "moderationRate": _decimal(rec.findtext("SalaryModerationRate")),
                      "totalRate": _decimal(rec.findtext("TotalRate")),
                      "isFlat": (rec.findtext("IsFlatRate") or "").strip().lower() == "true",
                      "minimumFlat": _decimal(rec.findtext("MinimumFlatRate")),
                      "fileStatus": (rec.findtext("Status") or "").strip() or None})
    combinations = []
    for rec in comb_root.findall("WorkerAndContributionComb"):
        ec, wc = (rec.findtext("EmployerClass") or "").strip(), (rec.findtext("WorkerCode") or "").strip()
        cc = (rec.findtext("ContributionWorkerCode") or "").strip()
        if not (_CODE.fullmatch(ec) and _CODE.fullmatch(wc) and _CODE.fullmatch(cc)):
            raise BadRequestException("A WorkerAndContributionComb record does not have the published code shapes.")
        combinations.append({"employerClass": ec, "workerCode": wc, "contributionCode": cc,
                             "owednessCode": (rec.findtext("OwednessCode") or "").strip() or None})
    return {"quarter": quarter, "rates": rates, "combinations": combinations}


def _archived_bytes(source) -> bytes:
    """The archived file's bytes, verified against the source's own checksum (fail closed)."""
    if not source.checksum_sha256 or not source.file_path:
        raise BadRequestException("The source is not ARCHIVED (stored file + checksum); register the official file "
                                  "first.")
    path = Path(source.file_path)
    if not path.is_file():
        raise BadRequestException("The archived source file is not readable on this server.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != source.checksum_sha256:
        raise BadRequestException("The archived file no longer matches its recorded checksum.")
    return data


# ── rate files ────────────────────────────────────────────────────────────────
def be_onss_register_rate_file(db: Session, pack_row_id: int, data: dict, actor_id) -> object:
    """Register one archived quarterly rate file and load EVERY record as REFERENCE (never read by the engine)."""
    from app.modules.payroll.models import SourceArtifact

    m = _models()
    pack = _draft_belgian_pack(db, pack_row_id)
    data = dict(data or {})
    reason = _reason(data.get("reason"))
    source = db.get(SourceArtifact, int(data.get("sourceDocumentId") or 0))
    if source is None:
        raise BadRequestException("sourceDocumentId must be the archived ONSS rate ZIP.")
    start, end = _day(data.get("effectiveFrom"), "effectiveFrom"), _day(data.get("effectiveTo"), "effectiveTo")
    if end < start:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")
    parsed = be_onss_parse_rate_zip(_archived_bytes(source))
    if db.query(m.PayrollBeOnssRateFile).filter_by(jurisdiction_pack_id=pack.id, quarter=parsed["quarter"]).first():
        raise BadRequestException(f"A rate file for quarter {parsed['quarter']} is already registered on this pack.")
    row = m.PayrollBeOnssRateFile(jurisdiction_pack_id=pack.id, quarter=parsed["quarter"], effective_from=start,
                                  effective_to=end, source_document_id=source.id,
                                  checksum_sha256=source.checksum_sha256, reference_rows=len(parsed["rates"]),
                                  status="PENDING", registered_by_id=actor_id)
    db.add(row)
    db.flush()
    db.bulk_insert_mappings(m.PayrollBeOnssRate, [
        {"rate_file_id": row.id, "employer_class": r["employerClass"], "code_kind": r["codeKind"], "code": r["code"],
         "contribution_type": r["contributionType"], "personal_rate": r["personalRate"],
         "employer_rate": r["employerRate"], "moderation_rate": r["moderationRate"], "total_rate": r["totalRate"],
         "is_flat": r["isFlat"], "minimum_flat": r["minimumFlat"], "file_status": r["fileStatus"],
         "status": REFERENCE} for r in parsed["rates"]])
    db.bulk_insert_mappings(m.PayrollBeOnssCodeCombination, [
        {"rate_file_id": row.id, "employer_class": c["employerClass"], "worker_code": c["workerCode"],
         "contribution_code": c["contributionCode"], "owedness_code": c["owednessCode"], "status": REFERENCE}
        for c in parsed["combinations"]])
    db.flush()
    be._audit(db, actor_id, "registered", "be_onss_rate_file", row.id,
              new={"quarter": row.quarter, "source": source.id, "rows": row.reference_rows,
                   "combinations": len(parsed["combinations"]), "reason": reason})
    return row


def _file(db: Session, file_id: int):
    row = db.get(_models().PayrollBeOnssRateFile, int(file_id))
    if row is None:
        raise NotFoundException("Belgian ONSS rate file")
    return row


def be_onss_attest_rate_file(db: Session, file_id: int, reason, actor_id) -> object:
    """Authenticity attestation (not a value review) by someone other than the registrar; the archived file must
    still match the checksum it was registered with."""
    from app.modules.payroll.models import SourceArtifact

    row = _file(db, file_id)
    reason = _reason(reason)
    if row.status != "PENDING":
        raise BadRequestException(f"The rate file is already {row.status}.")
    if actor_id is not None and actor_id == row.registered_by_id:
        raise BadRequestException("Four-eyes: the Super Admin who registered the rate file cannot attest it.")
    source = db.get(SourceArtifact, row.source_document_id)
    if source is None or hashlib.sha256(_archived_bytes(source)).hexdigest() != row.checksum_sha256:
        raise BadRequestException("The archived file does not match the checksum the rate file was registered with.")
    row.status, row.attested_by_id, row.attested_at, row.attestation_reason = "ATTESTED", actor_id, \
        datetime.utcnow(), reason
    db.flush()
    be._audit(db, actor_id, "attested", "be_onss_rate_file", row.id, new={"quarter": row.quarter, "reason": reason})
    return row


def _supported(db: Session, pack_row_id: int, key: str) -> set:
    from app.modules.payroll.models import ContributionRate

    row = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack_row_id,
                                             ContributionRate.organization_id.is_(None),
                                             ContributionRate.component_key == key).first())
    return {p.strip() for p in str(getattr(row, "text_value", None) or "").split(",") if p.strip()}


def _codes(values, name: str) -> list:
    codes = [str(v).strip() for v in (values or []) if str(v).strip()]
    bad = [c for c in codes if not _CODE.fullmatch(c)]
    if bad:
        raise BadRequestException(f"{name}: codes are three characters of text (e.g. \"000\", \"015\"); bad: {bad}.")
    return codes


def be_onss_mark_live(db: Session, file_id: int, data: dict, actor_id) -> dict:
    """Make the supported subset signable: the base rows of the supported employer categories x worker codes and
    the rows + combinations of the contribution codes in use. Everything else stays REFERENCE."""
    m = _models()
    row = _file(db, file_id)
    _draft_belgian_pack(db, row.jurisdiction_pack_id)
    data = dict(data or {})
    reason = _reason(data.get("reason"))
    ecs = _codes(data.get("employerClasses"), "employerClasses")
    wcs = _codes(data.get("workerCodes"), "workerCodes")
    ccs = _codes(data.get("contributionCodes"), "contributionCodes")
    if not ecs or not wcs:
        raise BadRequestException("employerClasses and workerCodes are required.")
    for key, codes in (("be_onss_supported_employer_categories", ecs), ("be_onss_supported_worker_codes", wcs)):
        missing = sorted(set(codes) - _supported(db, row.jurisdiction_pack_id, key))
        if missing:
            raise BadRequestException(f"{missing} not in the pack's {key} list: only the supported codes go live.")
    now = datetime.utcnow()
    R, C = m.PayrollBeOnssRate, m.PayrollBeOnssCodeCombination
    rates = (db.query(R).filter(R.rate_file_id == row.id, R.code_kind == "CONTRIBUTION", R.employer_class.in_(ecs),
                                R.code.in_(wcs + ccs), R.status == REFERENCE).all())
    combs = (db.query(C).filter(C.rate_file_id == row.id, C.employer_class.in_(ecs), C.worker_code.in_(wcs),
                                C.contribution_code.in_(ccs or [""]), C.status == REFERENCE).all())
    if not rates:
        raise BadRequestException("No REFERENCE rate row matches the supported codes in this file.")
    found = {c.contribution_code for c in combs}
    absent = sorted(set(ccs) - found)
    if absent:
        raise BadRequestException(f"contribution codes {absent} do not combine with the supported worker codes in "
                                  "this file.")
    for item in rates + combs:
        item.status, item.marked_live_by_id, item.marked_live_at = LIVE, actor_id, now
    db.flush()
    be._audit(db, actor_id, "marked_live", "be_onss_rate_file", row.id,
              new={"rates": len(rates), "combinations": len(combs), "employerClasses": ecs, "workerCodes": wcs,
                   "contributionCodes": ccs, "reason": reason})
    return {"rates": len(rates), "combinations": len(combs)}


def _sign(db: Session, model, item_id: int, reason, actor_id, label: str):
    item = db.get(model, int(item_id))
    if item is None:
        raise NotFoundException(label)
    reason = _reason(reason)
    if item.status != LIVE:
        raise BadRequestException(f"Only a live (PENDING) {label} can be signed; this one is {item.status}.")
    registrar = _file(db, item.rate_file_id).registered_by_id
    if actor_id is not None and actor_id in (item.marked_live_by_id, registrar):
        raise BadRequestException(f"Four-eyes: the Super Admin who registered the file or made the {label} live "
                                  "cannot sign it.")
    item.status, item.signed_by_id, item.signed_at, item.sign_reason = SIGNED, actor_id, datetime.utcnow(), reason
    db.flush()
    be._audit(db, actor_id, "signed", label.replace(" ", "_"), item.id, new={"reason": reason})
    return item


def be_onss_sign_rate(db: Session, rate_id: int, reason, actor_id):
    return _sign(db, _models().PayrollBeOnssRate, rate_id, reason, actor_id, "be onss rate")


def be_onss_sign_combination(db: Session, combination_id: int, reason, actor_id):
    return _sign(db, _models().PayrollBeOnssCodeCombination, combination_id, reason, actor_id,
                 "be onss combination")


# ── type rules (DmfA glossary annex 3) ─────────────────────────────────────────
def _condition(value, vocabulary, name: str) -> str:
    text = str(value or "").strip().upper() or _content().TYPE_RULE_ANY
    if text == _content().TYPE_RULE_ANY:
        return text
    parts = [p.strip() for p in text.split(",") if p.strip()]
    bad = [p for p in parts if p not in vocabulary or p == "UNKNOWN"]
    if bad or not parts:
        raise BadRequestException(f"{name}: ANY or a comma list of {', '.join(v for v in vocabulary if v != 'UNKNOWN')}"
                                  f"; bad: {bad}.")
    return ",".join(parts)


def be_onss_add_type_rule(db: Session, pack_row_id: int, data: dict, actor_id) -> object:
    c = _content()
    pack = _draft_belgian_pack(db, pack_row_id)
    data = dict(data or {})
    reason = _reason(data.get("reason"))
    code = str(data.get("code") or "").strip()
    if not _CODE.fullmatch(code):
        raise BadRequestException("code is three characters of text (e.g. \"809\").")
    outcome = str(data.get("outcome") or "").strip().upper()
    if outcome != c.TYPE_RULE_NOT_DUE and not c.CONTRIBUTION_TYPE_PATTERN.fullmatch(outcome):
        raise BadRequestException("outcome is a one-digit ContributionType or NOT_DUE.")
    source_id = data.get("sourceDocumentId")
    if source_id not in (None, ""):
        from app.modules.payroll.models import SourceArtifact

        if db.get(SourceArtifact, int(source_id)) is None:
            raise BadRequestException("sourceDocumentId does not exist.")
    end = _day(data["effectiveTo"], "effectiveTo") if data.get("effectiveTo") else None
    start = _day(data.get("effectiveFrom"), "effectiveFrom")
    if end is not None and end < start:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")
    rule = _models().PayrollBeOnssTypeRule(
        jurisdiction_pack_id=pack.id, code=code, outcome=outcome, effective_from=start, effective_to=end,
        pay_basis=_condition(data.get("payBasis"), c.ONSS_PAY_BASES, "payBasis"),
        closure_fund_sector=_condition(data.get("closureFundSector"), c.CLOSURE_FUND_SECTORS, "closureFundSector"),
        workforce_class=_condition(data.get("workforceClass"), c.WORKFORCE_CLASSES, "workforceClass"),
        wage_moderation=_condition(data.get("wageModeration"), c.WAGE_MODERATION_STATUSES, "wageModeration"),
        source_document_id=int(source_id) if source_id not in (None, "") else None,
        note=(" ".join(str(data.get("note") or "").split())[:300] or None), status="PENDING", created_by_id=actor_id)
    db.add(rule)
    db.flush()
    be._audit(db, actor_id, "added", "be_onss_type_rule", rule.id,
              new={"code": code, "outcome": outcome, "reason": reason})
    return rule


def be_onss_sign_type_rule(db: Session, rule_id: int, reason, actor_id) -> object:
    rule = db.get(_models().PayrollBeOnssTypeRule, int(rule_id))
    if rule is None:
        raise NotFoundException("Belgian ONSS type rule")
    reason = _reason(reason)
    if rule.status != "PENDING":
        raise BadRequestException("The type rule is already signed.")
    if actor_id is not None and actor_id == rule.created_by_id:
        raise BadRequestException("Four-eyes: the Super Admin who added the type rule cannot sign it.")
    rule.status, rule.signed_by_id, rule.signed_at, rule.sign_reason = SIGNED, actor_id, datetime.utcnow(), reason
    db.flush()
    be._audit(db, actor_id, "signed", "be_onss_type_rule", rule.id, new={"reason": reason})
    return rule


# ── views and the engine input ─────────────────────────────────────────────────
def _s(value) -> Optional[str]:
    return None if value is None else str(value)


def be_onss_rate_file_view(row) -> dict:
    return {"id": row.id, "packRowId": row.jurisdiction_pack_id, "quarter": row.quarter,
            "effectiveFrom": _s(row.effective_from), "effectiveTo": _s(row.effective_to),
            "sourceDocumentId": row.source_document_id, "checksum": row.checksum_sha256,
            "referenceRows": row.reference_rows, "status": row.status, "registeredById": row.registered_by_id,
            "attestedById": row.attested_by_id, "attestedAt": _s(row.attested_at)}


def be_onss_list_rate_files(db: Session, pack_row_id: int) -> list:
    F = _models().PayrollBeOnssRateFile
    return [be_onss_rate_file_view(r) for r in
            db.query(F).filter(F.jurisdiction_pack_id == int(pack_row_id)).order_by(F.effective_from).all()]


def _rate_view(r) -> dict:
    return {"id": r.id, "employerClass": r.employer_class, "codeKind": r.code_kind, "code": r.code,
            "contributionType": r.contribution_type, "personalRate": _s(r.personal_rate),
            "employerRate": _s(r.employer_rate), "moderationRate": _s(r.moderation_rate),
            "totalRate": _s(r.total_rate), "isFlat": bool(r.is_flat), "minimumFlat": _s(r.minimum_flat),
            "status": r.status}


def _comb_view(c) -> dict:
    return {"id": c.id, "employerClass": c.employer_class, "workerCode": c.worker_code,
            "contributionCode": c.contribution_code, "owednessCode": c.owedness_code, "status": c.status}


def _rule_view(r) -> dict:
    return {"id": r.id, "code": r.code, "payBasis": r.pay_basis, "closureFundSector": r.closure_fund_sector,
            "workforceClass": r.workforce_class, "wageModeration": r.wage_moderation, "outcome": r.outcome,
            "effectiveFrom": _s(r.effective_from), "effectiveTo": _s(r.effective_to), "status": r.status,
            "sourceDocumentId": r.source_document_id, "note": r.note}


def be_onss_live_rows(db: Session, file_id: int) -> dict:
    """The rows and combinations in active use (PENDING / SIGNED) of one file — the Super Admin signing view."""
    m = _models()
    row = _file(db, file_id)
    R, C = m.PayrollBeOnssRate, m.PayrollBeOnssCodeCombination
    rates = db.query(R).filter(R.rate_file_id == row.id, R.status != REFERENCE).order_by(R.code, R.id).all()
    combs = db.query(C).filter(C.rate_file_id == row.id, C.status != REFERENCE).order_by(C.id).all()
    return {"file": be_onss_rate_file_view(row), "rates": [_rate_view(r) for r in rates],
            "combinations": [_comb_view(c) for c in combs]}


def be_onss_list_type_rules(db: Session, pack_row_id: int) -> list:
    T = _models().PayrollBeOnssTypeRule
    return [_rule_view(r) for r in
            db.query(T).filter(T.jurisdiction_pack_id == int(pack_row_id)).order_by(T.code, T.id).all()]


def be_onss_rate_table_input(db: Session, pack_row_id: int, pay_date: date) -> Optional[dict]:
    """One quarter of the table for the engine (JSON-safe; frozen with the payslip): the file covering the pay date,
    its live rows / combinations with their status, and the pack's type rules. REFERENCE rows are never included."""
    m = _models()
    F = m.PayrollBeOnssRateFile
    files = (db.query(F).filter(F.jurisdiction_pack_id == int(pack_row_id), F.status != "REJECTED",
                                F.effective_from <= pay_date, F.effective_to >= pay_date).all())
    if not files:
        return None
    if len(files) != len(files[:1]):
        raise BadRequestException("Several ONSS rate files cover this pay date.")
    row = files[0]
    live = be_onss_live_rows(db, row.id)
    return {"quarter": row.quarter, "effectiveFrom": _s(row.effective_from), "effectiveTo": _s(row.effective_to),
            "fileId": row.id, "fileAttested": row.status == "ATTESTED", "rates": live["rates"],
            "combinations": live["combinations"], "typeRules": be_onss_list_type_rules(db, pack_row_id)}
