"""
japan_readiness.py — Japan release gates G0-G8 (ZP-JP-ENG-001 §14; Phase 9).

Each gate passes only when (a) every code check on the CANONICAL Japan pack
(organisation-independent rows) is met and (b) its evidence artefact
``JP-GATE-<Gn>`` is recorded and reviewed by someone other than its uploader
(japan_service._jp_evidence). A pack row counts as signed only when it has
its value and no longer carries the "[PENDING G1]" label or a PENDING_G1
text. Nothing here changes data; Japan's service availability may move to
AVAILABLE only when every gate passes (japan_service hook).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

PENDING_SUFFIX = "[PENDING G1]"
GATES = (
    ("G0", "Scope: monthly pay, resident employees", "Engineering lead"),
    ("G1", "National withholding and year-end tables signed", "Payroll / tax lead"),
    ("G2", "Corrections and due-date policies", "Product + legal"),
    ("G3", "Social-insurance grades, rates and care rules", "Social-insurance specialist"),
    ("G4", "Labour: minimum wages, premiums, holidays", "Labour / HR lead"),
    ("G5", "Filing export schemas certified", "Compliance"),
    ("G6", "My Number security and redaction", "Security lead"),
    ("G7", "Parallel cycles accepted", "Payroll operations"),
    ("G8", "Product, compliance and engineering sign-off", "CTO"),
)
SIGNOFFS = ("PRODUCT", "COMPLIANCE", "ENGINEERING")


def _jp_content():
    from app.modules.payroll.engine.countries import japan_content

    return japan_content


def _jp_pack_rows(db: Session):
    """(pack, {key: ContributionRate}, [TaxSlab]) of the newest canonical JP tax pack."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == "JP", JurisdictionPack.pack_type == "tax")
            .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first())
    if pack is None:
        return None, {}, []
    rates = {r.component_key: r for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))}
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                     TaxSlab.organization_id.is_(None)).all()
    return pack, rates, slabs


def _jp_signed(rates: dict, key: str) -> tuple:
    row = rates.get(key)
    if row is None:
        return False, f"{key} is missing from the pack"
    if PENDING_SUFFIX in (row.label or ""):
        return False, f"{key} is still marked PENDING G1"
    has_value = any(getattr(row, f) is not None for f in
                    ("flat_amount", "employee_rate_pct", "employer_rate_pct")) or \
        (row.text_value not in (None, "", "PENDING_G1"))
    return (True, f"{key} signed") if has_value else (False, f"{key} has no value")


def _jp_table(slabs, rule_type: str, **filters) -> tuple:
    rows = [s for s in slabs if s.rule_type == rule_type
            and all(getattr(s, k) == v for k, v in filters.items())]
    pending = [s for s in rows if PENDING_SUFFIX in (s.rate_label or "")]
    if not rows:
        return False, f"{rule_type} is empty"
    if pending:
        return False, f"{len(pending)} {rule_type} row(s) still PENDING G1"
    return True, f"{len(rows)} {rule_type} row(s)"


def _jp_per_prefecture(slabs, rule_type: str, **filters) -> tuple:
    codes = {c for c, _ in _jp_content().JP_PREFECTURES}
    have = {str(s.jurisdiction_state) for s in slabs if s.rule_type == rule_type
            and all(getattr(s, k) == v for k, v in filters.items())
            and PENDING_SUFFIX not in (s.rate_label or "")}
    missing = sorted(codes - have)
    return (not missing, f"{len(codes) - len(missing)}/47 prefectures"
            + (f"; missing {', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}" if missing else ""))


def jp_code_checks(db: Session) -> dict:
    """{gate: [{key, ok, detail}]} — every check is re-derived from the data."""
    from app.config import settings
    from app.modules.payroll import japan_filing, japan_parallel

    content = _jp_content()
    pack, rates, slabs = _jp_pack_rows(db)
    checks = {g: [] for g, _l, _o in GATES}

    def add(gate, key, result):
        ok, detail = result
        checks[gate].append({"key": key, "ok": bool(ok), "detail": detail})

    add("G0", "pack_seeded", (pack is not None, f"{pack.pack_id} {pack.version} ({pack.status})" if pack
                              else "no canonical Japan tax pack is seeded"))
    add("G0", "monthly_only", (getattr(rates.get("jp_supported_pay_frequencies"), "text_value", None) == "MONTHLY",
                               "only MONTHLY pay is certified"))
    for key in ("jp_withholding_method", "jp_wht_rounding", "jp_wht_bonus_special_multiple",
                "jp_yea_income_limit", "jp_yea_taxable_rounding", "jp_yea_rounding", "jp_yea_earliest_month",
                "jp_reconstruction_surtax_pct", "jp_yea_earthquake_cap"):
        add("G1", key, _jp_signed(rates, key))
    for rule in ("JP_WHT_MONTHLY", "JP_WHT_BONUS", *content.JP_YEA_RULE_TYPES):
        add("G1", rule, _jp_table(slabs, rule))
    if getattr(rates.get("jp_withholding_method"), "text_value", None) == "COMPUTER_PRIMARY_TABLES_OTHERS":
        for rule in ("JP_WHT_CMP_EID", "JP_WHT_CMP_RATE"):
            add("G1", rule, _jp_table(slabs, rule))
        for key in ("jp_wht_cmp_basic_deduction", "jp_wht_cmp_dependant_deduction"):
            add("G1", key, _jp_signed(rates, key))
    for key in ("jp_correction_policy", "jp_wht_due_non_business_day_rule", "jp_resident_tax_remittance_due_day"):
        add("G2", key, _jp_signed(rates, key))
    for key in ("jp_care_split_rule", "jp_si_employee_share_rounding", "jp_ei_employee_share_rounding",
                "jp_smr_min_payment_base_days", "jp_smr_adhoc_grade_gap"):
        add("G3", key, _jp_signed(rates, key))
    add("G3", "JP_SMR_GRADE:HEALTH", _jp_table(slabs, "JP_SMR_GRADE", filing_status="HEALTH"))
    add("G3", "JP_SMR_GRADE:PENSION", _jp_table(slabs, "JP_SMR_GRADE", filing_status="PENSION"))
    add("G3", "JP_HEALTH_RATE:KYOKAI_KENPO", _jp_per_prefecture(slabs, "JP_HEALTH_RATE", tax_regime="KYOKAI_KENPO"))
    add("G4", "JP_MIN_WAGE", _jp_per_prefecture(slabs, "JP_MIN_WAGE"))
    add("G4", "JP_HOLIDAY", _jp_table(slabs, "JP_HOLIDAY"))
    for key in ("jp_premium_combination_rule", "jp_holiday_substitute_rule"):
        add("G4", key, _jp_signed(rates, key))
    missing_schemas = [d for d in japan_filing.DOCUMENTS if japan_filing.export_refusal(d)]
    add("G5", "export_schemas", (not missing_schemas, "all certified" if not missing_schemas
                                 else f"not certified: {', '.join(missing_schemas)}"))
    # Presence only — a key value is never read into a result.
    add("G6", "my_number_keyring", (bool(getattr(settings, "JP_MY_NUMBER_KEYRING", None)),
                                    "JP_MY_NUMBER_KEYRING is configured" if getattr(settings, "JP_MY_NUMBER_KEYRING", None)
                                    else "JP_MY_NUMBER_KEYRING is not configured"))
    add("G6", "my_number_fingerprint_key", (bool(getattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", None)),
                                            "JP_MY_NUMBER_FINGERPRINT_KEY is configured"
                                            if getattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", None)
                                            else "JP_MY_NUMBER_FINGERPRINT_KEY is not configured"))
    periods = sorted(japan_parallel.jp_accepted_parallel_periods(db))
    add("G7", "parallel_cycles", (len(periods) >= japan_parallel.MIN_ACCEPTED_CYCLES,
                                  f"{len(periods)} accepted cycle month(s): {', '.join(periods) or 'none'} "
                                  f"(needs {japan_parallel.MIN_ACCEPTED_CYCLES})"))
    return checks


def jp_readiness(db: Session) -> dict:
    from app.modules.payroll import japan_service

    checks = jp_code_checks(db)
    gates = []
    for key, label, owner in GATES:
        tags = [f"JP-GATE-{key}"] + ([f"JP-SIGNOFF-{s}" for s in SIGNOFFS] if key == "G8" else [])
        evidence = []
        for tag in tags:
            accepted, submitted = japan_service._jp_evidence(db, tag)
            evidence.append({"tag": tag, "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                             "artifactId": getattr(accepted, "id", None)})
        passed = all(c["ok"] for c in checks[key]) and all(e["state"] == "RECORDED" for e in evidence)
        gates.append({"gate": key, "label": label, "owner": owner, "checks": checks[key],
                      "evidence": evidence, "passed": passed,
                      "checklist": f"docs/japan/release-gates/{key}.md"})
    decisions = japan_service.owner_decisions(db)
    return {"jurisdiction": "JP", "gates": gates, "decisions": decisions,
            "allPassed": all(g["passed"] for g in gates) and all(d["state"] == "RECORDED" for d in decisions)}


def jp_unmet_requirements(db: Session) -> list:
    """[{key, label, detail}] for the service-registry AVAILABLE step."""
    state = jp_readiness(db)
    unmet = [{"key": g["gate"], "label": g["label"],
              "detail": "; ".join([c["detail"] for c in g["checks"] if not c["ok"]]
                                  + [f"{e['tag']} {e['state']}" for e in g["evidence"] if e["state"] != "RECORDED"])}
             for g in state["gates"] if not g["passed"]]
    unmet += [{"key": d["key"], "label": d["label"], "detail": f"owner decision {d['state']}"}
              for d in state["decisions"] if d["state"] != "RECORDED"]
    return unmet
