"""Malaysia applicability (ZP-MY-ENG-001 §1, §4, §6-§8; MY-004 / MY-007 / MY-008 / MY-026).

Determines, BEFORE any calculation, the coverage decision of every national
obligation — PCB, EPF, PERKESO (SOCSO), EIS, HRD — each with a reason code,
from the APPROVED worker profile and employer registration in force. Never one
"Malaysia covered" flag (MY-004). A missing or contradictory fact fails only
the affected obligation (MY-008): it is returned under ``blocked`` with its
code instead of raising. Whole-payslip problems (no profile / registration,
unsupported worker type or pay frequency) raise.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack, as_date, field, in_window, upper

_MALAYSIAN = ("CITIZEN", "PERMANENT_RESIDENT")


def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _active(record, on: date) -> bool:
    return (record is not None and upper(field(record, "status")) == "ACTIVE"
            and in_window(field(record, "effective_from"), field(record, "effective_to"), on))


def _decision(applies: bool, reason: str, **extra) -> dict:
    return {"applies": applies, "reason": reason, **extra}


def _blocked(code: str, reason: str) -> dict:
    return {"code": code, "reason": reason}


def _epf(pack: MyPack, profile, start: date, end: date):
    cls = upper(field(profile, "epf_member_class"))
    if not cls:
        return None, _blocked(E.keyed(E.FACT_MISSING, "epf_member_class"), "the EPF member class is not recorded")
    if cls == "NOT_COVERED":
        return _decision(False, "EPF_NOT_COVERED"), None
    citizenship = upper(field(profile, "citizenship"))
    if not citizenship:
        return None, _blocked(E.keyed(E.FACT_MISSING, "citizenship"), "citizenship decides the EPF branch")
    allowed = {"MY_PR_BELOW_60": _MALAYSIAN, "MY_60_PLUS": ("CITIZEN",),
               "PR_OR_PRE1998_NONMY_60_PLUS": ("PERMANENT_RESIDENT", "NON_CITIZEN"),
               "NONMY_POST_1998": ("NON_CITIZEN",)}[cls]
    if citizenship not in allowed:
        return None, _blocked(E.keyed(E.FACT_CONFLICT, "epf_member_class"),
                              f"member class {cls} does not fit citizenship {citizenship}")
    if cls == "NONMY_POST_1998":
        # MY-012: the mandatory non-Malaysian branch applies from its effective
        # wage month only; earlier wage months are never restated.
        if not pack.in_force("my_epf_rate_non_malaysian", on=end):
            return _decision(False, "EPF_NON_MALAYSIAN_BEFORE_EFFECTIVE_DATE"), None
        return _decision(True, "EPF_NON_MALAYSIAN_PART_F", memberClass=cls), None
    dob = as_date(field(profile, "date_of_birth"))
    if dob is None:
        return None, _blocked(E.keyed(E.FACT_MISSING, "date_of_birth"), "age decides the EPF class")
    threshold = pack.amount("my_epf_age_threshold")
    before, after = age_on(dob, start) >= threshold, age_on(dob, end) >= threshold
    if before != after:
        try:
            rule = pack.text("my_epf_age_transition_rule", content.EPF_AGE_TRANSITION_RULES)
        except E.MYCalculationBlockedError as exc:
            return None, _blocked(E.EPF_AGE_TRANSITION,
                                  f"the worker reaches the EPF age threshold in this wage month: {exc.reason}")
        over_60 = before if rule == "AGE_AT_WAGE_MONTH_START" else False
    else:
        over_60 = before
    if over_60 != (cls in ("MY_60_PLUS", "PR_OR_PRE1998_NONMY_60_PLUS")):
        return None, _blocked(E.keyed(E.FACT_CONFLICT, "epf_member_class"),
                              f"member class {cls} does not fit the worker's age")
    return _decision(True, f"EPF_{cls}", memberClass=cls), None


def _socso(profile):
    category = upper(field(profile, "socso_category"))
    if not category:
        return None, _blocked(E.keyed(E.FACT_MISSING, "socso_category"), "the PERKESO category is not recorded")
    if category == "NOT_COVERED":
        return _decision(False, "SOCSO_NOT_COVERED"), None
    citizenship = upper(field(profile, "citizenship"))
    if not citizenship:
        return None, _blocked(E.keyed(E.FACT_MISSING, "citizenship"), "citizenship decides the PERKESO schedule")
    if (category == "FOREIGN_WORKER") != (citizenship == "NON_CITIZEN"):
        return None, _blocked(E.keyed(E.FACT_CONFLICT, "socso_category"),
                              f"category {category} does not fit citizenship {citizenship} — foreign workers use "
                              "their own schedule, never the local one")
    rule = content.MY_FW_SOCSO_SCHEDULE_RULE if category == "FOREIGN_WORKER" else content.MY_SOCSO_SCHEDULE_RULE
    return _decision(True, f"SOCSO_{category}", category=category, schedule=rule), None


def _eis(pack: MyPack, profile, start: date, end: date):
    state = upper(field(profile, "eis_state"))
    if not state:
        return None, _blocked(E.keyed(E.FACT_MISSING, "eis_state"), "the EIS state is not recorded")
    citizenship = upper(field(profile, "citizenship"))
    if state != "COVERED":
        return _decision(False, f"EIS_{state}"), None
    if citizenship == "NON_CITIZEN":
        return None, _blocked(E.keyed(E.FACT_CONFLICT, "eis_state"), "foreign workers are excluded from EIS (spec §7)")
    if not citizenship:
        return None, _blocked(E.keyed(E.FACT_MISSING, "citizenship"), "citizenship decides EIS coverage")
    dob = as_date(field(profile, "date_of_birth"))
    if dob is None:
        return None, _blocked(E.keyed(E.FACT_MISSING, "date_of_birth"), "age decides EIS coverage")
    try:
        rule = pack.text("my_eis_age_rule", content.EIS_AGE_RULES)
        low, high = pack.amount("my_eis_min_age"), pack.amount("my_eis_max_age")
    except E.MYCalculationBlockedError as exc:
        return None, _blocked(exc.key, exc.reason)
    age = age_on(dob, start if rule == "AGE_AT_WAGE_MONTH_START" else end)
    if age < low or age > high:
        return None, _blocked(E.keyed(E.FACT_CONFLICT, "eis_state"), f"EIS is marked COVERED but the worker is {age}")
    return _decision(True, "EIS_COVERED"), None


def _hrd(pack: MyPack, registration, profile, end: date):
    category = upper(field(registration, "hrd_category"))
    if category == "NOT_REGISTERED":
        return _decision(False, "HRD_NOT_REGISTERED"), None
    if category not in content.HRD_CATEGORIES:
        return None, _blocked(E.keyed(E.FACT_MISSING, "hrd_category"), "the HRD category is not recorded")
    since = as_date(field(registration, "hrd_category_from"))
    if since is None or since > end:
        return None, _blocked(E.HRD_CATEGORY_NOT_IN_FORCE, "the HRD category is not in force for this wage month")
    if upper(field(profile, "citizenship")) == "NON_CITIZEN":
        try:
            rule = pack.text("my_hrd_non_malaysian_rule", content.HRD_NON_MALAYSIAN_RULES)
        except E.MYCalculationBlockedError as exc:
            return None, _blocked(exc.key, exc.reason)
        if rule == "MALAYSIAN_EMPLOYEES_ONLY":
            return _decision(False, "HRD_NON_MALAYSIAN_EXCLUDED"), None
    return _decision(True, f"HRD_{category}", category=category), None


def determine(ctx, pack: MyPack, pay_date: date, start: date, end: date) -> dict:
    """{"profile", "registration", "coverage": {obligation: decision},
    "blocked": {obligation: {code, reason}}} — whole-payslip problems raise."""
    org = getattr(ctx, "my_organization_id", None)
    profile = getattr(ctx, "my_profile", None)
    registration = getattr(ctx, "my_registration", None)
    if profile is None:
        raise E.MYCalculationBlockedError(E.PROFILE_MISSING, "no Malaysian worker profile is in force", org)
    if not _active(profile, pay_date):
        raise E.MYCalculationBlockedError(E.PROFILE_NOT_ACTIVE, "the worker profile is not ACTIVE on the pay date", org)
    if registration is None:
        raise E.MYCalculationBlockedError(E.REGISTRATION_MISSING, "no employer registration is in force", org)
    if not _active(registration, pay_date):
        raise E.MYCalculationBlockedError(E.REGISTRATION_NOT_ACTIVE,
                                          "the employer registration is not ACTIVE on the pay date", org)
    contract = upper(field(profile, "contract_type"))
    if contract == "DOMESTIC" or upper(field(profile, "socso_category")) == "UNSUPPORTED_DOMESTIC":
        raise E.MYCalculationBlockedError(E.UNSUPPORTED_DOMESTIC,
                                          "domestic workers are outside the certified scope (spec §1)", org)
    if contract not in pack.text_list("my_supported_contract_types"):
        raise E.MYCalculationBlockedError(E.keyed(E.UNSUPPORTED_CONTRACT, contract or "NONE"),
                                          "this worker type is outside the certified scope (spec §1)", org)
    frequency = upper(field(profile, "pay_frequency"))
    if frequency not in pack.text_list("my_supported_pay_frequencies"):
        raise E.MYCalculationBlockedError(E.keyed(E.PAY_FREQUENCY_UNSUPPORTED, frequency or "NONE"),
                                          "this pay frequency is not certified", org)
    coverage, blocked = {"PCB": _decision(True, "PCB_EMPLOYMENT_INCOME")}, {}
    for name, (decision, problem) in (("EPF", _epf(pack, profile, start, end)), ("SOCSO", _socso(profile)),
                                      ("EIS", _eis(pack, profile, start, end)),
                                      ("HRD", _hrd(pack, registration, profile, end))):
        if problem is not None:
            blocked[name] = problem
        else:
            coverage[name] = decision
    return {"profile": profile, "registration": registration, "coverage": coverage, "blocked": blocked,
            "contractType": contract, "payFrequency": frequency}


def residence(profile) -> Optional[str]:
    """The REVIEWED tax residence (MY-007); REVIEW_REQUIRED is not a decision."""
    value = upper(field(profile, "tax_residence"))
    return value if value in ("RESIDENT", "NON_RESIDENT") else None
