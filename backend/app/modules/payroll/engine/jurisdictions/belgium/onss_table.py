"""Belgium ONSS employer contributions from the ONSS rate table (Block M-ECWC). Pure: no ORM, no clock.

The service (belgium_onss_rates.be_onss_rate_table_input) hands the engine ONE quarter of one rate file:

    {"quarter", "effectiveFrom", "effectiveTo", "fileId", "fileAttested",
     "rates":        [{"id", "employerClass", "codeKind", "code", "contributionType", "personalRate", "employerRate",
                       "moderationRate", "totalRate", "isFlat", "minimumFlat", "status"}],   # PENDING / SIGNED only
     "combinations": [{"id", "employerClass", "workerCode", "contributionCode", "status"}],
     "typeRules":    [{"id", "code", "payBasis", "closureFundSector", "workforceClass", "wageModeration",
                       "outcome", "effectiveFrom", "effectiveTo", "status"}]}

Rules (fail closed, nothing defaulted):
  * a row is used only when the file is ATTESTED authentic AND the row itself is SIGNED (four-eyes each);
  * the ContributionType of every code (DmfA zone 00083) comes from a SIGNED type rule matching the facts: the
    worker's ONSS pay basis (PAY_100 / PAY_108) and the employer's closure-fund sector, workforce class and
    wage-moderation status, each recorded with its evidence; no match, an ambiguous match or a pending rule blocks;
  * the base row is (employer category, worker code, type); every combined contribution code in use (a signed
    combination) adds its employer share and its wage moderation; a rule outcome NOT_DUE skips the code;
  * flat amounts, quarterly minimums and a personal share on a combined code are not calculated yet: they block.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from app.modules.payroll.engine.countries import belgium_content as content
from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec, field, in_window, upper

_PERCENT = Decimal("100")                    # a rate is a percentage (structural unit)
SIGNED = "SIGNED"
_BASE_KIND = "CONTRIBUTION"                  # the rate file lists ordinary worker codes as ContributionWorkerCode
_FACTS = (("closureFundSector", "closureFundSectorEvidence", "closure-fund sector"),
          ("workforceClass", "workforceClassEvidence", "workforce class"),
          ("wageModerationStatus", "wageModerationEvidence", "wage-moderation status"))


def be_onss_registration_facts(registration) -> dict:
    """The employer facts of the registration in force. Kept OUT of the applicability decision so the input hash of
    every existing payslip is unchanged (BE-010 replay); only the rate-table path reads them."""
    return {"closureFundSector": upper(field(registration, "closure_fund_sector")) or "UNKNOWN",
            "closureFundSectorEvidence": bool(field(registration, "closure_fund_sector_evidence_ref")),
            "workforceClass": upper(field(registration, "workforce_class")) or "UNKNOWN",
            "workforceClassEvidence": bool(field(registration, "workforce_class_evidence_ref")),
            "wageModerationStatus": upper(field(registration, "wage_moderation_status")) or "UNKNOWN",
            "wageModerationEvidence": bool(field(registration, "wage_moderation_evidence_ref"))}


def be_onss_table_facts(pack: BePack, decision: dict, employer: dict) -> dict:
    """The facts a type rule may test. A missing / UNKNOWN fact or a fact without its evidence blocks."""
    employer = employer or {}
    facts = {"payBasis": content.PAY_108 if decision["worker"].get("onssManualBase") is True else content.PAY_100}
    for name, evidence, label in _FACTS:
        value = upper(employer.get(name))
        if not value or value == "UNKNOWN":
            pack.block(E.ONSS_FACT_MISSING, name, f"the employer's {label} is not recorded (four-eyes, evidence "
                                                  "required) — the ContributionType cannot be selected")
        if not employer.get(evidence):
            pack.block(E.ONSS_FACT_MISSING, name, f"the employer's {label} has no evidence reference — a missing "
                                                  "evidence reference blocks like a missing value")
        facts[name] = value
    return facts


def _allows(condition, value: str) -> bool:
    text = upper(condition) or content.TYPE_RULE_ANY
    if text == content.TYPE_RULE_ANY:
        return True
    return value in {part.strip() for part in text.split(",") if part.strip()}


def be_onss_resolve_type(pack: BePack, table: dict, code: str, facts: dict) -> Optional[str]:
    """The ContributionType of `code` for these facts, or None when the signed rule says NOT_DUE."""
    matching = [r for r in table.get("typeRules") or ()
                if str(r.get("code")) == code
                and in_window(as_date(r.get("effectiveFrom")), as_date(r.get("effectiveTo")), pack.as_of)
                and _allows(r.get("payBasis"), facts["payBasis"])
                and _allows(r.get("closureFundSector"), facts["closureFundSector"])
                and _allows(r.get("workforceClass"), facts["workforceClass"])
                and _allows(r.get("wageModeration"), facts["wageModerationStatus"])]
    if any(upper(r.get("status")) != SIGNED for r in matching):
        pack.block(E.ONSS_RATE_UNSIGNED, f"type_rule:{code}", "a type rule matching these facts is not signed "
                                                              "(four-eyes)")
    outcomes = {upper(r.get("outcome")) for r in matching}
    if not outcomes:
        pack.block(E.ONSS_TYPE_UNRESOLVED, code, "no signed type rule matches the worker's pay basis and the "
                                                 "employer's facts — no ContributionType is ever assumed")
    outcome = outcomes.pop()
    if outcomes:                                                 # another distinct outcome remains
        pack.block(E.ONSS_TYPE_AMBIGUOUS, code, f"signed type rules disagree: {sorted(outcomes | {outcome})}")
    if outcome == content.TYPE_RULE_NOT_DUE:
        return None
    if not content.CONTRIBUTION_TYPE_PATTERN.fullmatch(outcome):
        pack.block(E.ONSS_TYPE_UNRESOLVED, code, f"type rule outcome {outcome!r} is not a one-digit type")
    return outcome


def be_onss_rate_row(pack: BePack, table: dict, employer_class: str, code: str, contribution_type: str) -> dict:
    """The live rate row (category, code, type): its file attested AND the row signed, or a block."""
    ident = f"{employer_class}:{code}:{contribution_type}"
    if table.get("fileAttested") is not True:
        pack.block(E.ONSS_RATE_FILE_UNATTESTED, ident, f"rate file {table.get('quarter')} is not attested as the "
                                                       "genuine ONSS publication (four-eyes)")
    rows = [r for r in table.get("rates") or ()
            if str(r.get("employerClass")) == employer_class and str(r.get("codeKind")) == _BASE_KIND
            and str(r.get("code")) == code and str(r.get("contributionType")) == contribution_type]
    if not rows:
        pack.block(E.ONSS_RATE_ROW_MISSING, ident, "no live rate row for this employer category, code and "
                                                   "ContributionType in the quarter's file")
    row = next(iter(rows))                       # (file, category, kind, code, type) is unique in the database
    if upper(row.get("status")) != SIGNED:
        pack.block(E.ONSS_RATE_UNSIGNED, ident, "the rate row is not signed (four-eyes) — a signed file does "
                                                "not sign its rows")
    if row.get("isFlat") is True or row.get("minimumFlat") not in (None, ""):
        pack.block(E.ONSS_RATE_FLAT_UNSUPPORTED, ident, "flat amounts and quarterly minimums are not calculated yet")
    return row


def be_onss_table_compute(pack: BePack, table: Optional[dict], decision: dict, employer_facts: dict,
                          employer_base: Decimal, rnd: Callable[[Decimal], Decimal]) -> dict:
    """{"lines": {"BASE", "WAGE_MODERATION"}, "funds": {"CODE_<code>": amount}, "used": [...], "types": {...}}."""
    if not table:
        pack.block(E.ONSS_RATE_TABLE_MISSING, "be_onss_employer_base_rate", "no ONSS rate file covers the pay "
                                                                            "date's quarter")
    if not in_window(as_date(table.get("effectiveFrom")), as_date(table.get("effectiveTo")), pack.as_of):
        pack.block(E.ONSS_RATE_TABLE_MISSING, "be_onss_employer_base_rate", "the rate file's quarter does not "
                                                                            "cover the pay date")
    employer_class = str((decision.get("employer") or {}).get("employerCategory") or "")
    worker_code = str(decision["worker"].get("workerCode") or "")
    facts = be_onss_table_facts(pack, decision, employer_facts)
    types, used = {}, []

    def share(amount: Decimal, rate) -> Decimal:
        return rnd(amount * dec(rate) / _PERCENT)

    base_type = be_onss_resolve_type(pack, table, worker_code, facts)
    if base_type is None:
        pack.block(E.ONSS_TYPE_UNRESOLVED, worker_code, "a worker code cannot be NOT_DUE")
    base = be_onss_rate_row(pack, table, employer_class, worker_code, base_type)
    types[worker_code] = base_type
    used.append(base.get("id"))
    lines = {"BASE": share(employer_base, base.get("employerRate")),
             "WAGE_MODERATION": share(employer_base, base.get("moderationRate"))}
    funds = {}
    for combo in table.get("combinations") or ():
        if str(combo.get("employerClass")) != employer_class or str(combo.get("workerCode")) != worker_code:
            continue
        code = str(combo.get("contributionCode"))
        if upper(combo.get("status")) != SIGNED:
            pack.block(E.ONSS_RATE_UNSIGNED, f"combination:{employer_class}:{worker_code}:{code}",
                       "a combination in use is not signed (four-eyes)")
        ctype = be_onss_resolve_type(pack, table, code, facts)
        types[code] = ctype
        if ctype is None:
            continue
        row = be_onss_rate_row(pack, table, employer_class, code, ctype)
        if dec(row.get("personalRate")) != ZERO:
            pack.block(E.ONSS_RATE_PERSONAL_UNSUPPORTED, f"{employer_class}:{code}:{ctype}",
                       "a combined contribution with a personal share is not calculated yet")
        used.append(row.get("id"))
        funds[f"CODE_{code}"] = share(employer_base, row.get("employerRate"))
        lines["WAGE_MODERATION"] += share(employer_base, row.get("moderationRate"))
    return {"lines": lines, "funds": funds, "used": used, "types": types, "facts": facts,
            "quarter": table.get("quarter"), "fileId": table.get("fileId")}
