"""Belgium (ZP-BE-ENG-001): activation readiness report for a Belgian pack — READ-ONLY (Super Admin console).

What it answers, for one pack (e.g. BE-PAYROLL-2026):

  1. Can it be activated now?  The verdict is the governed activation gate itself
     (belgium_service.be_pack_activation_refusal) — the report can never disagree with what activation would do.
  2. Which rows block it, ALL the reasons per row (not only the first), the state of each row's source, and who or
     what clears each reason (Belgian specialist, a second Super Admin, a source reviewer, engineering, the owner).
  3. What would still block PAYROLL after activation: engine gaps (Block M), keys without a vocabulary, open owner /
     specialist decisions, unsourced 2026 amendments, the quarterly ONSS rate files. The release gates G1-G7 stay on
     the Overview (/readiness, aggregate class): this report reads pack content only, never worker records.

Nothing here writes, signs, approves or activates. The static maps below mirror docs/belgium/BELGIUM_GAPS_AND_
DECISIONS.md (Block M) and BELGIUM_SPECIALIST_PACK.md §4; the rest is derived from the database on every call.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.modules.payroll import belgium_service as be

# Who clears a reason.
SPECIALIST = "BELGIAN_SPECIALIST"
SIGNER = "SECOND_SUPER_ADMIN"
SOURCE_REVIEWER = "SOURCE_REVIEWER"
ENGINEERING = "ENGINEERING"
OWNER = "OWNER"
ACTIVATOR = "THIRD_SUPER_ADMIN"

# Row reasons that block ACTIVATION (exactly the gate's checks).
MISSING, UNSIGNED, EMPTY, UNSOURCED, SLAB_ROWS_INCOMPLETE = "MISSING", "UNSIGNED", "EMPTY", "UNSOURCED", "SLAB_ROWS"

_CLEARS = {
    MISSING: (ENGINEERING, "Re-seed the catalogue row (scripts.seed_belgium_canonical_packs or 'Create the Draft pack')."),
    EMPTY: (SPECIALIST, "Enter the value (console or content-workbook import) with its archived official source."),
    UNSOURCED: (SPECIALIST, "Attach the archived official source document the value comes from."),
    UNSIGNED: (SIGNER, "A Super Admin who did not enter or edit the row signs it (Signing status > sign / bulk "
                       "sign; four-eyes per row)."),
    SLAB_ROWS_INCOMPLETE: (SPECIALIST, "Add the band / formula / table rows for this key and have a second Super "
                                       "Admin sign every one of them."),
}

# Block M engine gaps (BELGIUM_GAPS_AND_DECISIONS.md): signing these rows today cannot give a correct calculation.
ENGINE_GAPS = {
    "be_bssc_pending": ("M-BSSC", "The special social security contribution is never computed; the scale needs a "
                                  "BSSC band key with a household dimension."),
    "be_red_social_work_bonus": ("M-WORKBONUS", "One band key with no employé / ouvrier split, read on the uplifted "
                                                "manual-worker base; the source has two tables (A + B) on the plain base."),
    "be_wht_annex3_regular_scale": ("M-WHT", "The engine taxes the monthly pay with one band; Annex III annualises, "
                                             "applies the annual scale and divides by 12."),
    "be_wht_family_reductions": ("M-WHT", "Annex III family reductions are annual amounts by household type."),
    "be_wht_fiscal_work_bonus": ("M-WHT", "Needs the social bonus split into components A and B (M-WORKBONUS)."),
    "be_wht_exceptional_rule": ("M-WHT", "Exceptional rates by annual normal gross pay with the children exemption "
                                         "and reduction tables."),
    "be_wht_holiday_pay_rule": ("M-WHT", "Holiday-pay rates by annual normal gross pay (Annex III n° 53)."),
    "be_wht_overtime_rule": ("M-WHT", "Overtime reduction on the premium hours within the yearly hour limits."),
    "be_onss_employer_base_rate": ("M-ECWC", "Structure built: sign the key RATE_TABLE and load, attest and sign the "
                                             "quarterly ONSS rate files (or enter EC x WC band rows)."),
    "be_onss_fund_contributions": ("M-ECWC", "As be_onss_employer_base_rate: from the attested rate files."),
}
# Open specialist questions / conflicts not held as decision records (BELGIUM_SPECIALIST_PACK.md §4, reviewer guide).
OPEN_QUESTIONS = {
    "be_wht_taxable_basis_rule": ("SQ-WHT-1 / SQ-WHT-2 (G-26)", "Is the BSSC deducted from the withholding base, and "
                                                                "how is employee ONSS split between regular and "
                                                                "exceptional pay?"),
    "be_onss_employer_base_rate": ("Employer base rate conflict", "the nominal private-sector rate (spec) vs the "
                                                                  "2026/3 rate-file rate for category 000 (reviewer "
                                                                  "guide): which category applies."),
}
# Content that depends on 2026 amendments not yet archived (DOWNLOAD_LIST A2 / A3).
AMENDMENTS_MISSING = {
    "be_wht_annex3_amendment_2026": "A2 (Royal Decree 24 Jul 2026, from 1 Aug) and A3 (27 Sep 2026, from 1 Nov)",
    "be_wht_fiscal_work_bonus": "A2 (change from 1 Aug 2026)",
    "be_wht_overtime_rule": "A2 (change from 1 Aug 2026)",
}


def _content():
    from app.modules.payroll.engine.countries import belgium_content

    return belgium_content


def _source_state(source) -> tuple:
    """(state, signable): the same test the signing gate applies (be_super_admin._source with verify)."""
    if source is None:
        return "NONE", False
    archived = bool(source.checksum_sha256 and source.file_path)
    if "[UNVERIFIED" in (source.title or "") or not archived:
        return "UNVERIFIED", False
    if not source.reviewer_id or source.reviewer_id == source.created_by_id:
        return "ARCHIVED_NOT_REVIEWED", False
    return "ARCHIVED_REVIEWED", True


def _has_vocabulary(content, key: str, kind: str) -> bool:
    if kind != content.KIND_TEXT:
        return True
    return key in content.LIST_VOCABULARIES or key in content.CHOICE_VOCABULARIES or key in content.CODE_LIST_KEYS


def _row_report(content, key, kind, group, row, slabs, sources) -> dict:
    blocks = []
    if row is None:
        blocks.append(MISSING)
    else:
        if content.PENDING_MARK in (row.label or ""):
            blocks.append(UNSIGNED)
        if be._row_empty(row, kind):
            blocks.append(EMPTY)
        if row.source_document_id is None:
            blocks.append(UNSOURCED)
        if kind in content.SLAB_KINDS and (row.text_value or "").upper() == content.SLAB_ROWS:
            mine = [s for s in slabs if s.rule_type == content.RULE_TYPES[key]]
            if not mine or any(content.PENDING_MARK in (s.rate_label or "") for s in mine):
                blocks.append(SLAB_ROWS_INCOMPLETE)
    source = sources.get(row.source_document_id) if row is not None and row.source_document_id else None
    state, signable = _source_state(source)
    cleared = [{"by": who, "action": what, "reason": b} for b in blocks for who, what in (_CLEARS[b],)]
    if UNSIGNED in blocks and not signable and row is not None and row.source_document_id is not None:
        cleared.append({"by": SOURCE_REVIEWER, "reason": "SOURCE_NOT_SIGNABLE",
                        "action": "Signing needs the source stored with its checksum and reviewed by a Super Admin "
                                  f"other than its uploader (now: {state})."})
    payroll = []
    if key in ENGINE_GAPS:
        item, detail = ENGINE_GAPS[key]
        payroll.append({"code": item, "by": ENGINEERING, "detail": detail})
    if not _has_vocabulary(content, key, kind):
        payroll.append({"code": "NO_VOCABULARY", "by": ENGINEERING,
                        "detail": "No vocabulary exists for this rule: it can only be signed NOT_SUPPORTED until "
                                  "engineering defines one."})
    if key in OPEN_QUESTIONS:
        ref, detail = OPEN_QUESTIONS[key]
        payroll.append({"code": ref, "by": SPECIALIST, "detail": detail})
    if key in AMENDMENTS_MISSING:
        payroll.append({"code": "SOURCE_NOT_ARCHIVED", "by": OWNER,
                        "detail": f"{AMENDMENTS_MISSING[key]} not yet in the source inbox."})
    return {"key": key, "group": group, "kind": kind, "rowId": getattr(row, "id", None),
            "label": (getattr(row, "label", None) or next(label for *_rest, label in (content.KEYS[key],))),
            "textValue": getattr(row, "text_value", None), "blocks": blocks,
            "source": {"id": getattr(source, "id", None), "reference": getattr(source, "form_number", None),
                       "state": state, "signable": signable},
            "clearedBy": cleared, "payrollBlockers": payroll}


def _quarters(start: Optional[date], end: Optional[date]) -> list:
    """The ONSS rate-file quarters ("YYYYQ") of a pack window."""
    from app.modules.payroll import belgium_onss_rates

    if start is None or end is None:
        return []
    out = []
    for year in range(start.year, end.year + 1):
        for q in "1234":
            key = f"{year}{q}"
            q_start, q_end = belgium_onss_rates._quarter_bounds(key)
            if q_end >= start and q_start <= end:
                out.append((key, q_start, q_end))
    return out


def _rate_files(db: Session, pack) -> list:
    m = be._models()
    F, R, C = m.PayrollBeOnssRateFile, m.PayrollBeOnssRate, m.PayrollBeOnssCodeCombination
    files = {f.quarter: f for f in db.query(F).filter(F.jurisdiction_pack_id == pack.id, F.status != "REJECTED")}
    out = []
    for key, q_start, q_end in _quarters(pack.effective_from, pack.effective_to):
        f = files.get(key)
        if f is None:
            out.append({"quarter": key, "from": q_start.isoformat(), "to": q_end.isoformat(), "state": "NO_FILE",
                        "by": OWNER, "action": "Download the quarter's ONSS DmfA rate ZIP, register it, have it "
                                               "attested, mark the supported codes live and sign them."})
            continue
        live = db.query(R).filter(R.rate_file_id == f.id, R.status != "REFERENCE").all()
        combos = db.query(C).filter(C.rate_file_id == f.id, C.status != "REFERENCE").all()
        unsigned = [x for x in live + combos if x.status != "SIGNED"]
        state = ("NOT_ATTESTED" if f.status != "ATTESTED" else "NO_LIVE_ROWS" if not live
                 else "ROWS_UNSIGNED" if unsigned else "READY")
        action = {"NOT_ATTESTED": (SIGNER, "A Super Admin other than the registrar attests the archived file."),
                  "NO_LIVE_ROWS": (SIGNER, "Mark the supported employer categories / worker codes live."),
                  "ROWS_UNSIGNED": (SIGNER, "A Super Admin other than the registrar / the one who made them live "
                                            "signs each live row and combination."),
                  "READY": (None, "")}[state]
        by, what = action
        out.append({"quarter": key, "from": q_start.isoformat(), "to": q_end.isoformat(), "state": state,
                    "fileId": f.id, "liveRows": len(live), "liveCombinations": len(combos),
                    "unsigned": len(unsigned), "by": by, "action": what})
    return out


def be_activation_readiness(db: Session, pack_row_id: int) -> dict:
    """The full read-only readiness report of one Belgian pack."""
    from app.modules.payroll import belgium_golden, belgium_governance, be_super_admin
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    content = _content()
    pack = db.get(JurisdictionPack, int(pack_row_id))
    if pack is None or (pack.jurisdiction_country or "").upper() != be.BE:
        raise NotFoundException("Belgian pack")
    rates = {r.component_key: r for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))}
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None)).all()
    source_ids = {r.source_document_id for r in rates.values() if r.source_document_id}
    sources = ({s.id: s for s in db.query(SourceArtifact).filter(SourceArtifact.id.in_(source_ids))}
               if source_ids else {})

    rows = [_row_report(content, key, kind, group, rates.get(key), slabs, sources)
            for key, (group, kind, _ref, _label) in content.KEYS.items()]
    blocking = [r for r in rows if r["blocks"]]
    classes = [s for s in slabs if s.rule_type == content.EARNING_CLASS_RULE]
    classes_unsigned = sum(1 for s in classes if content.PENDING_MARK in (s.rate_label or ""))
    classes_review = sum(1 for s in classes if s.assessment_basis == "REVIEW")

    refusal = be.be_pack_activation_refusal(db, pack)
    golden = belgium_golden.be_golden_refusal(db, pack)
    editors = sorted(be_super_admin.statutory_editors(db, pack))
    conditions = [
        {"code": "EARNING_CLASSES", "blocking": not classes or bool(classes_unsigned),
         "detail": f"{len(classes)} classification rows; {classes_unsigned} unsigned; {classes_review} still REVIEW",
         "by": SPECIALIST, "action": "Decide INCLUDED / EXCLUDED per component x obligation (earning-class patterns); "
                                     "a second Super Admin signs each row."},
        {"code": "GOLDEN_CERTIFICATION", "blocking": golden is not None, "detail": golden or "passed",
         "by": OWNER, "action": "Register official or independently prepared worked examples and pass the "
                                "certification run (G-34: FPS Finance calculator or a certified Belgian payroll "
                                "provider; the manual reviewer-guide examples cannot serve)."},
        {"code": "ACTIVATOR_FOUR_EYES", "blocking": False,
         "detail": f"{len(editors)} Super Admin(s) edited or signed rows of this version; none of them may activate.",
         "by": ACTIVATOR, "action": "A Super Admin who neither edited nor signed any row activates the pack."},
    ]

    decisions = []
    for gap, (question, keys) in belgium_governance.DECISION_GAPS.items():
        current = belgium_governance.be_current_decision(db, gap)
        decisions.append({"gap": gap, "question": question, "contentKeys": list(keys),
                          "state": "DECIDED" if current is not None else "OPEN",
                          "by": OWNER, "action": "Propose and decide it in Decision records (proposer != decider), "
                                                 "then sign the linked content rows."})

    reasons = Counter(b for r in blocking for b in r["blocks"])
    by_role = Counter(c["by"] for r in blocking for c in r["clearedBy"])
    payroll_codes = Counter(p["code"] for r in rows for p in r["payrollBlockers"])
    return {
        "pack": {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status,
                 "effectiveFrom": pack.effective_from.isoformat() if pack.effective_from else None,
                 "effectiveTo": pack.effective_to.isoformat() if pack.effective_to else None},
        "verdict": {"canActivate": refusal is None, "gateRefusal": refusal,
                    "blockingRows": len(blocking), "catalogueRows": len(rows),
                    "blockingConditions": sum(1 for c in conditions if c["blocking"])},
        "summary": {"byReason": dict(reasons), "byClearer": dict(by_role), "payrollBlockers": dict(payroll_codes)},
        "rows": [r for r in rows if r["blocks"] or r["payrollBlockers"]],
        "conditions": conditions,
        # The release gates G1-G7 are NOT recomputed here: they read worker records (counts, aggregate mode) and are
        # shown by the Overview from /compliance/belgium/readiness. This report reads pack content only (platform).
        "afterActivation": {"decisions": decisions, "rateFiles": _rate_files(db, pack),
                            "releaseGates": "see Overview > Release gates (GET /compliance/belgium/readiness)"},
    }
