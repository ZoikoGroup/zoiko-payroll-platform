"""Belgium applicability, worker classification and Joint Committee resolver
(ZP-BE-ENG-001 §2, BE-001 / BE-002 / BE-003 / BE-020 / BE-022; Block A2).

"The resolver is the constitutional layer for Belgium": it evaluates the legal
employer, establishment unit, ONSS employer category, worker category and code,
special status, contract / pay frequency / pay basis, Joint Committee and
sub-committee, function class and seniority, and the working schedule BEFORE any
monetary rule executes.

Pure: no ORM query, no clock. The caller passes plain dicts (or rows) of the
records and a BePack scoped to the pay date. Unlike the engine's fail-fast
readers, ``resolve()`` COLLECTS every blocking reason (so the read-only resolve
endpoint can show them all); ``require()`` turns the first one into the
BECalculationBlockedError the engine raises.

Supported scope comes only from signed pack rows:
  be_onss_supported_employer_categories, be_onss_supported_worker_codes,
  be_supported_worker_categories, be_supported_contract_types,
  be_supported_pay_frequencies, be_supported_pay_bases,
  be_onss_manual_base_categories.
A missing, pending or NOT_SUPPORTED row blocks (never defaulted). A special
status (student, flexi, occasional, ...) never uses ordinary-worker rules: any
recorded special status blocks until its own regime is certified (spec §2, D6).
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

from app.modules.payroll.engine.countries import belgium_content as content
from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack, as_date, field, in_window, upper

RESOLVED, BLOCKED = "RESOLVED", "BLOCKED"
CONFIDENCE_FULL, CONFIDENCE_EXCEPTIONS, CONFIDENCE_NONE = "EVIDENCED", "EVIDENCED_WITH_EXCEPTIONS", "NONE"

# PayrollEmployee.pay_frequency / employment_type spellings -> vocabulary codes
# (spelling normalisation only; WHICH codes are supported is signed content).
_FREQUENCY_SPELLINGS = {"MONTHLY": "MONTHLY", "SEMIMONTHLY": "SEMI_MONTHLY", "FORTNIGHTLY": "FORTNIGHTLY",
                        "BIWEEKLY": "FORTNIGHTLY", "WEEKLY": "WEEKLY"}


def normalise_code(value) -> str:
    """'Full-time' -> 'FULL_TIME', 'Semi monthly' -> 'SEMI_MONTHLY' (spelling only)."""
    text = upper(value)
    for sep in ("-", " ", "/"):
        text = text.replace(sep, "_")
    return text


def normalise_frequency(value) -> str:
    """'Monthly' -> 'MONTHLY', 'Semi-monthly' -> 'SEMI_MONTHLY'; unknown spellings
    pass through unchanged (and are then refused by the signed list)."""
    code = normalise_code(value)
    return _FREQUENCY_SPELLINGS.get(code.replace("_", ""), code)


class _Collector:
    """Runs each check; a BECalculationBlockedError becomes one blocking reason."""

    def __init__(self):
        self.blocking: list = []
        self.exceptions: list = []

    def run(self, check: Callable, *args, **kwargs):
        try:
            return check(*args, **kwargs)
        except E.BECalculationBlockedError as blocked:
            self.blocking.append({"code": blocked.key, "reason": blocked.reason})
            return None

    def block(self, code: str, reason: str) -> None:
        self.blocking.append({"code": code, "reason": reason})

    def exception(self, code: str, reason: str) -> None:
        self.exceptions.append({"code": code, "reason": reason})


# A SUPERSEDED version was ACTIVE inside its own (truncated) window, so a past
# pay date still resolves to it; DRAFT / WITHDRAWN never count.
_IN_FORCE_STATUSES = ("ACTIVE", "SUPERSEDED")


def _active_in_force(record, on: date) -> bool:
    return (record is not None and upper(field(record, "status")) in _IN_FORCE_STATUSES
            and in_window(field(record, "effective_from"), field(record, "effective_to"), on))


def _evidence(kind: str, record) -> dict:
    start, end = as_date(field(record, "effective_from")), as_date(field(record, "effective_to"))
    return {"record": kind, "id": field(record, "id"), "status": field(record, "status"),
            "effectiveFrom": start.isoformat() if start else None, "effectiveTo": end.isoformat() if end else None,
            "evidenceRef": field(record, "evidence_ref")}


def _check_list(c: _Collector, pack: BePack, key: str, value: str, code: str, what: str) -> None:
    supported = c.run(pack.text_list, key)
    if supported is None:
        return
    if not value:
        c.block(E.keyed(E.FACT_MISSING, what), f"the {what.replace('_', ' ')} is not recorded")
    elif value not in supported:
        c.block(E.keyed(code, value), f"{what.replace('_', ' ')} {value} is not in the signed supported list ({key})")


def _employer(c: _Collector, pack: BePack, registration, on: date) -> Optional[dict]:
    if registration is None:
        c.block(E.REGISTRATION_MISSING, "no Belgian employer registration is on record for this employer")
        return None
    if not _active_in_force(registration, on):
        c.block(E.REGISTRATION_NOT_ACTIVE, "the employer registration is not ACTIVE on the pay date "
                                           "(four-eyes approval required)")
    if upper(field(registration, "verification_state")) != "VERIFIED":
        c.block(E.REGISTRATION_UNVERIFIED, "the employer registration has not been verified by a second person")
    category = upper(field(registration, "employer_category_code"))
    _check_list(c, pack, "be_onss_supported_employer_categories", category, E.EMPLOYER_CATEGORY_UNSUPPORTED,
                "employer_category")
    return {"registrationId": field(registration, "id"), "legalEntityId": field(registration, "legal_entity_id"),
            "employerCategory": category or None,
            "verificationState": upper(field(registration, "verification_state")) or None}


def _worker(c: _Collector, pack: BePack, profile, on: date, contract_type, pay_frequency, pay_basis) -> Optional[dict]:
    if profile is None:
        c.block(E.PROFILE_MISSING, "no Belgian worker statutory profile is on record")
        return None
    if not _active_in_force(profile, on):
        c.block(E.PROFILE_NOT_ACTIVE, "the worker profile is not ACTIVE on the pay date (four-eyes approval required)")
    category = upper(field(profile, "worker_category"))
    _check_list(c, pack, "be_supported_worker_categories", category, E.WORKER_CATEGORY_UNSUPPORTED,
                "worker_category")
    worker_code = upper(field(profile, "onss_worker_code"))
    _check_list(c, pack, "be_onss_supported_worker_codes", worker_code, E.WORKER_CODE_UNSUPPORTED, "worker_code")
    special = upper(field(profile, "special_status"))
    if special:
        c.block(E.keyed(E.SPECIAL_STATUS_UNSUPPORTED, special),
                "a special status (student, flexi, occasional, ...) cannot use ordinary-worker rules; "
                "its regime is not certified (spec §2, D6)")
    residency = upper(field(profile, "residency"))
    if not residency:
        c.block(E.keyed(E.FACT_MISSING, "residency"), "the tax residency is not recorded (spec §5 stage 1)")
    contract = normalise_code(contract_type)
    _check_list(c, pack, "be_supported_contract_types", contract, E.CONTRACT_UNSUPPORTED, "contract_type")
    frequency = normalise_frequency(pay_frequency)
    _check_list(c, pack, "be_supported_pay_frequencies", frequency, E.FREQUENCY_UNSUPPORTED, "pay_frequency")
    basis = normalise_code(pay_basis)
    _check_list(c, pack, "be_supported_pay_bases", basis, E.PAY_BASIS_UNSUPPORTED, "pay_basis")
    manual = c.run(pack.text_list, "be_onss_manual_base_categories")
    return {"profileId": field(profile, "id"), "workerCategory": category or None, "workerCode": worker_code or None,
            "specialStatus": special or None, "residency": residency or None, "taxStatus": field(profile, "tax_status"),
            "contractType": contract or None, "payFrequency": frequency or None, "payBasis": basis or None,
            "onssManualBase": None if manual is None else category in manual}


def _agreement(c: _Collector, agreement, classification, on: date, line: str) -> Optional[dict]:
    agreement_id = field(classification, "collective_agreement_id")
    if agreement_id is None:
        c.exception(E.keyed(E.SECTOR_AGREEMENT_MISSING, line),
                    "no Joint Committee agreement is linked: the sector minimum check cannot run and there is "
                    "no fallback to the interprofessional minimum while a committee applies (spec §2)")
        return None
    if agreement is None:
        c.block(E.keyed(E.AGREEMENT_INVALID, line), "the linked Joint Committee agreement does not exist")
        return None
    code = field(agreement, "agreement_code")
    try:
        committee, sub, version = content.parse_be_agreement_code(code)
    except ValueError:
        c.block(E.keyed(E.AGREEMENT_INVALID, line), "the linked agreement is not a Belgian Joint Committee pack")
        return None
    if upper(field(agreement, "jurisdiction_country")) != "BE":
        c.block(E.keyed(E.AGREEMENT_INVALID, line), "the linked agreement is not a Belgian agreement")
    if upper(field(agreement, "status")) != "ACTIVE" or not in_window(field(agreement, "effective_from"),
                                                                        field(agreement, "effective_to"), on):
        c.block(E.keyed(E.AGREEMENT_INVALID, line), "the linked Joint Committee agreement is not Active on the pay date")
    if committee != upper(field(classification, "joint_committee")) or (
            sub is not None and sub != upper(field(classification, "sub_committee"))):
        c.block(E.keyed(E.AGREEMENT_INVALID, line),
                "the linked agreement belongs to a different Joint Committee / sub-committee")
    return {"id": field(agreement, "id"), "agreementCode": code, "jointCommittee": committee,
            "subCommittee": sub, "codeVersion": version, "status": field(agreement, "status")}


def _unit(c: _Collector, unit, classification, registration, on: date, line: str) -> Optional[dict]:
    unit_id = field(classification, "establishment_unit_id")
    if unit_id is None:
        return None
    if unit is None or not _active_in_force(unit, on):
        c.block(E.keyed(E.UNIT_INVALID, line), "the establishment unit is not ACTIVE on the pay date")
        return None
    if registration is not None and field(unit, "registration_id") != field(registration, "id"):
        c.block(E.keyed(E.UNIT_INVALID, line), "the establishment unit belongs to another employer registration")
    return {"id": field(unit, "id"), "unitNumber": field(unit, "unit_number"), "region": field(unit, "region")}


def _schedule(c: _Collector, schedules: list, classification, on: date, line: str) -> Optional[dict]:
    in_force = [s for s in schedules if _active_in_force(s, on)]
    linked = field(classification, "work_schedule_id")
    if linked is not None:
        chosen = [s for s in in_force if field(s, "id") == linked]
        if not chosen:
            c.block(E.keyed(E.SCHEDULE_MISSING, line), "the linked work schedule is not ACTIVE on the pay date")
            return None
    elif len(in_force) == 1:
        chosen = in_force
    elif not in_force:
        c.block(E.keyed(E.SCHEDULE_MISSING, line), "no ACTIVE work schedule is in force on the pay date (BE-022)")
        return None
    else:
        c.block(E.keyed(E.SCHEDULE_AMBIGUOUS, line),
                "several work schedules are in force; link one to this employment line")
        return None
    s = chosen[0]
    return {"id": field(s, "id"), "regime": upper(field(s, "regime")),
            "weeklyHours": None if field(s, "weekly_hours") is None else str(field(s, "weekly_hours")),
            "referencePeriod": field(s, "reference_period")}


def _lines(c: _Collector, classifications: list, on: date, period_start: Optional[date]) -> dict:
    """{employment_line: the ACTIVE classification in force on the pay date};
    blocks a line whose classification changed inside the pay period."""
    by_line: dict = {}
    for row in classifications:
        by_line.setdefault(upper(field(row, "employment_line")), []).append(row)
    chosen = {}
    for line, rows in sorted(by_line.items()):
        active = [r for r in rows if _active_in_force(r, on)]
        if not active:
            continue
        chosen[line] = active[0]
        if period_start is not None:
            changed = [r for r in rows if r is not active[0] and _active_in_force(r, period_start)]
            if changed:
                c.block(E.keyed(E.MID_PERIOD_CHANGE, line),
                        "the classification changed inside the pay period; pro-rating across classifications "
                        "is not certified")
    return chosen


def resolve(pack: Optional[BePack], pay_date: date, *, registration=None, profile=None, classifications=(),
            schedules=(), units=None, agreements=None, declarations=(), contract_type=None, pay_frequency=None,
            pay_basis=None, period_start: Optional[date] = None) -> dict:
    """The resolved decision for one employee on one pay date (spec §2).

    ``units`` / ``agreements``: {id: row} of the rows the classifications link.
    ``declarations``: the employee's declarations (any status); only APPROVED
    ones in force on the pay date are used (spec §5 stage 5)."""
    c = _Collector()
    units, agreements = units or {}, agreements or {}
    if pack is None:
        c.block(E.PACK_MISSING, "no active Belgium rule pack is in force on the pay date")
        return _result(c, None, pay_date, None, None, [], {}, [])
    employer = _employer(c, pack, registration, pay_date)
    worker = _worker(c, pack, profile, pay_date, contract_type, pay_frequency, pay_basis)

    lines = []
    chosen = _lines(c, list(classifications), pay_date, period_start)
    if not chosen:
        c.block(E.CLASSIFICATION_MISSING, "no ACTIVE employment classification is in force on the pay date (BE-003)")
    for line, row in chosen.items():
        committee = upper(field(row, "joint_committee"))
        if not committee:
            c.block(E.keyed(E.JOINT_COMMITTEE_MISSING, line), "the employment line has no Joint Committee (BE-020)")
        if not field(row, "function_class") or field(row, "seniority_months") is None:
            c.exception(E.keyed(E.SCALE_INPUT_MISSING, line),
                        "function class or seniority is missing: the sector scale cannot be checked (spec §2)")
        agreement = agreements.get(field(row, "collective_agreement_id"))
        lines.append({
            "employmentLine": line, "classificationId": field(row, "id"), "jointCommittee": committee or None,
            "subCommittee": upper(field(row, "sub_committee")) or None, "functionClass": field(row, "function_class"),
            "seniorityMonths": field(row, "seniority_months"),
            "agreement": _agreement(c, agreement, row, pay_date, line) if committee else None,
            "unit": _unit(c, units.get(field(row, "establishment_unit_id")), row, registration, pay_date, line),
            "schedule": _schedule(c, list(schedules), row, pay_date, line),
            "evidence": _evidence("classification", row)})

    approved = {}
    for d in declarations:
        if upper(field(d, "status")) == "APPROVED" and in_window(field(d, "effective_from"),
                                                                 field(d, "effective_to"), pay_date):
            approved[upper(field(d, "declaration_type"))] = {
                "id": field(d, "id"), "value": field(d, "value"),
                "effectiveFrom": as_date(field(d, "effective_from")).isoformat()}
    evidence = [_evidence(kind, r) for kind, r in (("employer_registration", registration),
                                                   ("worker_profile", profile)) if r is not None]
    return _result(c, pack, pay_date, employer, worker, lines, approved, evidence)


def _result(c: _Collector, pack, pay_date: date, employer, worker, lines, declarations, evidence) -> dict:
    decision = BLOCKED if c.blocking else RESOLVED
    confidence = CONFIDENCE_NONE if c.blocking else (CONFIDENCE_EXCEPTIONS if c.exceptions else CONFIDENCE_FULL)
    return {"decision": decision, "confidence": confidence, "payDate": pay_date.isoformat(),
            "blocking": c.blocking, "exceptions": c.exceptions, "employer": employer, "worker": worker,
            "employmentLines": lines, "declarations": declarations, "evidence": evidence,
            "usedRows": pack.used() if pack is not None else []}


def require(result: dict, organization_id=None) -> dict:
    """Engine entry: the first blocking reason becomes the calculation block."""
    if result["blocking"]:
        first = result["blocking"][0]
        more = len(result["blocking"]) - 1
        reason = first["reason"] + (f" (and {more} more blocking reason(s))" if more else "")
        raise E.BECalculationBlockedError(first["code"], reason, organization_id)
    return result
