"""
payroll/mexico_service.py
-------------------------
Mexico (ZP-MX-ENG-001) jurisdiction module — the statutory workflows the
shared payroll service reaches through jurisdiction_hooks (one-way
dependency: platform <- this module <- engine).

Phase 0 (scaffolding): every hook exists and fails CLOSED for Mexico only —
pack / template activation and the registry's move to AVAILABLE are refused,
calculation inputs and run approval BLOCK, a Mexican statutory profile cannot
be saved. Hooks the shared service reaches for every jurisdiction module
(retention_settings via retention_service._report_country) return an inert,
valid answer instead of raising, so no other country is affected.

Each hook is replaced by its real implementation in the phase that builds it
(see docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md).

Phase 2: pack activation is a gate-based check (content exact, evidence
linked, G1 human review by a non-activator, pack-bound golden PASS) on top
of the shared four-eyes / transition-graph / evidence / golden-run gates;
plus read-only content views, ISN states, earning classifications and CFDI
schema releases.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll import retention_service, service
from app.modules.payroll.engine.countries.mexico import ENGINE_VERSION, MXBlock
from app.modules.payroll.engine.countries.mexico_content import GATES, SPEC
from app.modules.payroll.models import (
    EmployeeStatutoryProfile, PayrollEmployee, PayrollRun, PayrollStatus, PayslipItem,
)

MX = "MX"
_NOT_BUILT = "not built yet (ZP-MX-ENG-001 Phase 0 scaffolding)"


def _employee(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = service.get_employee_by_id(db, employee_id, organization_id)  # 404s outside the tenant
    if service._normalize_country(employee.country_code or "") != MX:
        raise BadRequestException(f"employee #{employee_id} is not a Mexico employee")
    return employee


# ---- Readiness (spec §22) ----

def gate_states(db: Session) -> list:
    """G1–G8. Nothing is evidenced at Phase 0, so every gate is OPEN; gate
    evidence review arrives with Phase 10."""
    return [{"gate": key, "label": label, "state": "OPEN"} for key, label in GATES]


def statutory_summary(db: Session) -> dict:
    return {"jurisdiction": MX, "spec": SPEC, "available": False, "engineVersion": ENGINE_VERSION,
            "phase": 2, "gates": gate_states(db),
            "note": "Live Mexican payroll stays gated until G1–G8 are signed (ZP-MX-ENG-001 §22); "
                    "the Mexico engine is not built yet, so every Mexican calculation is BLOCKED."}


# ---- Governance hooks ----

def transition_mx_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """PLANNED <-> AVAILABLE. AVAILABLE is refused until every gate G1–G8 is
    signed (spec §22: approval of the build is not approval of live payroll)."""
    def readiness():
        unmet = [{"key": f"mx_gate_{g['gate'].lower()}", "label": f"Gate {g['gate']} — {g['label']}",
                  "detail": f"gate {g['gate']} is {g['state']}", "met": False}
                 for g in gate_states(db) if g["state"] != "SIGNED"]
        return unmet, {u["key"]: u["detail"] for u in unmet}

    return service.transition_service_registry(
        db, MX, target, reason, actor_id, label="Mexico", readiness=readiness,
        invalid_target_message=lambda t: (
            f"Mexico availability can only be {service.SERVICE_REGISTRY_OPEN} or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Mexico registry row — seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Mexico is {a}; only PLANNED moves to AVAILABLE.")


def mx_activation_evidence_refusal(db: Session, pack, actor_id: Optional[int] = None) -> Optional[str]:
    """Phase 2 gate-based activation check (beyond the shared four-eyes,
    transition-graph, evidence and country golden-PASS gates in
    service._set_jurisdiction_pack_status): the first unmet condition refuses.
    Runs on the normal AND the hotfix path."""
    failed = [c for c in activation_checks(db, pack, actor_id) if not c["met"]]
    return f"Mexico pack activation is refused: {failed[0]['detail']}" if failed else None


def mx_pack_approval_refusal(db: Session, pack, actor_id: Optional[int] = None) -> Optional[str]:
    """Approving a Mexico pack (Phase 2, open item 5) requires the pack to be
    in QA — the transition graph's last step before Approved, so the shared
    Draft -> Approved auto-advance can never fire for Mexico — and activation
    gates 1 (content exact) and 2 (every row source-linked) to hold already."""
    if pack.status != "QA":
        return (f"Mexico pack approval is refused: {pack.pack_id} v{pack.version} is {pack.status} — move it through "
                "In Review to QA first (Draft → In Review → QA → Approved).")
    for check in activation_checks(db, pack, actor_id)[:2]:          # gate 1 (content), gate 2 (evidence)
        if not check["met"]:
            return f"Mexico pack approval is refused: {check['detail']}"
    return None


def statutory_editors(db: Session, pack) -> set:
    """Every Super Admin who edited a statutory row of this pack version (from
    the immutable audit trail) — none may approve it (maker-checker)."""
    from app.modules.payroll.models import TaxConfigurationAudit

    rows = (db.query(TaxConfigurationAudit.actor_id)
            .filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id,
                    TaxConfigurationAudit.entity_type.in_(("contribution_rate", "tax_slab")),
                    TaxConfigurationAudit.action != "seed",
                    TaxConfigurationAudit.actor_id.isnot(None)).distinct().all())
    return {r[0] for r in rows}


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    return ("Mexico report-template activation is refused: Mexico templates are seeded Draft in Phase 2 and go live "
            "only with the outputs they describe (Phases 6–10).")


# ---- Calculation and run hooks ----

def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None) -> dict:
    raise MXBlock("MX_ENGINE_NOT_IMPLEMENTED",
                  f"Mexico calculation inputs are {_NOT_BUILT}; no Mexican payroll is calculated until then",
                  getattr(employee, "organization_id", None))


def _mx_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """Reached only for a run with Mexican payslips (service.advance_payroll_run_
    status). None can be approved, authorized or paid before Phase 6 (approval
    fingerprint, MX-040); moving back (Draft / Review) is not blocked."""
    if next_status in (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        raise MXBlock("MX_RUN_NOT_SUPPORTED",
                      f"Mexico payroll-run approval is {_NOT_BUILT}; a run with Mexican payslips cannot be "
                      f"{getattr(next_status, 'value', next_status)}",
                      getattr(run, "organization_id", None))


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """No MX payment hold at this phase (bank settlement lifecycle is Phase 10)."""
    return {}


def _mx_pack_holidays(db: Session, year: int) -> list:
    """Mexican mandatory rest days are not seeded from a reviewed source yet —
    none is invented here."""
    return []


def _mx_statutory_profile_errors(data) -> list:
    return [f"Mexico statutory profiles are {_NOT_BUILT} (Phase 4); no Mexican profile can be saved yet."]


def _mx_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


def _mx_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    return None


# ---- Records governance (retention_service) ----
# retention_service._report_country asks EVERY jurisdiction module for its
# settings on each report download, so this must answer (never raise). No
# record category and no owner decision exist yet: retention stays
# BLOCKED_UNDECIDED for Mexico, and only Mexico's own reports match.

def _decision_state(db: Session, key: str) -> str:
    return "OPEN"


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return db.query(EmployeeStatutoryProfile.id).filter(EmployeeStatutoryProfile.employee_id == employee_id,
                                                        EmployeeStatutoryProfile.country_code == MX).first() is not None


def is_mx_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == MX
                                        or str(getattr(report, "report_type", "") or "").startswith("MX_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=MX, label="Mexico", categories=(),
        period_decision="MX-D-RETENTION-PERIOD", end_decision="MX-D-RETENTION-END",
        decision_reference="MX-DECISION-RETENTION", decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _employee(db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_mx_report, audit_spec=SPEC)


JURISDICTION_HOOKS = {
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_mx_service_registry",
    "statutory_summary": "statutory_summary",
    "pack_activation_refusal": "mx_activation_evidence_refusal",
    "pack_approval_refusal": "mx_pack_approval_refusal",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "calc_inputs": "calc_inputs",
    "payment_treatment": "payment_treatment",
    "before_run_transition": "_mx_before_run_transition",
    "pack_holidays": "_mx_pack_holidays",
    "statutory_profile_errors": "_mx_statutory_profile_errors",
    "statutory_profile_values": "_mx_profile_values",
    "payslip_hold_view": "_mx_payslip_hold_view",
}


# ══════════════════════════════════════════════════════════════════════════
# Phase 2 — activation readiness, read-only content, ISN states,
# earning classifications (MX-005/MX-006), CFDI schema releases (MX-015)
# ══════════════════════════════════════════════════════════════════════════

import hashlib as _hashlib
import json as _json
from collections import Counter as _Counter
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone

from app.core.exceptions import NotFoundException
from app.modules.payroll.engine.countries import mexico_content as _content

_GOLDEN_DIR = "mx_golden"


def _iso(value):
    return value.isoformat() if value is not None else None


def _plain(value):
    from decimal import Decimal

    return str(value) if isinstance(value, Decimal) else value


def _pack_rows(db: Session, pack):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None))
             .order_by(ContributionRate.sort_order, ContributionRate.id).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.sort_order, TaxSlab.id).all())
    return rates, slabs


def _db_signatures(rates, slabs) -> list:
    out = [_content.rate_signature(r.component_key, r.employee_rate_pct, r.employer_rate_pct, r.flat_amount,
                                   r.text_value, r.effective_from, r.effective_to) for r in rates]
    out += [_content.slab_signature(s.rule_type, s.filing_status, s.min_amount, s.max_amount, s.flat_amount,
                                    s.rate_pct, s.effective_from, s.effective_to, s.tax_table_number) for s in slabs]
    return out


def _content_check(pack, rates, slabs) -> tuple:
    """Gate 1b-1 (review change 3): the pack carries EXACTLY the rows the
    content module defines for its window — every expected row, 11 Art. 96
    brackets per payment period, no extras."""
    start, end = pack.effective_from, pack.effective_to
    if start is None or end is None:
        return False, "the pack has no effective window to compare its content against"
    if pack.jurisdiction_state:
        expected = _content.expected_state_signatures(pack.jurisdiction_state, start, end)
        if not expected:
            return False, f"no transcribed ISN content exists for {pack.jurisdiction_state} (mexico_content is empty)"
        if "mx_isn_rate_pct" not in {sig[1] for sig in expected}:
            return False, f"the {pack.jurisdiction_state} ISN content has no mx_isn_rate_pct row"
    else:
        expected = _content.expected_national_signatures(start, end)
        if not expected:
            return False, "no transcribed national content exists (mexico_content is empty — awaiting transcription)"
        keys = {sig[1] for sig in expected if sig[0] == "RATE"}
        required = {k for k, (kind, _label, scope) in _content.MX_PARAMETER_KEYS.items()
                    if scope == "national" and kind != "text"}
        if required - keys:
            return False, f"the content lacks required parameters: {', '.join(sorted(required - keys)[:6])}"
        per_period = _Counter(sig[2] for sig in expected if sig[0] == "SLAB" and sig[1] == _content.MX_ISR_TARIFF_RULE)
        short = [p for p in _content.MX_ISR_PERIODS if per_period.get(p, 0) != _content.MX_ISR_BRACKETS_PER_PERIOD]
        if short:
            return False, (f"the ISR content does not have exactly {_content.MX_ISR_BRACKETS_PER_PERIOD} brackets for "
                           f"{', '.join(short)}")
    actual = _Counter(_db_signatures(rates, slabs))
    wanted = _Counter(expected)
    missing, extra = wanted - actual, actual - wanted
    if missing or extra:
        return False, (f"the pack's rows differ from mexico_content: {sum(missing.values())} expected row(s) "
                       f"missing, {sum(extra.values())} unexpected row(s) present — re-seed the Draft")
    return True, f"{sum(actual.values())} rows match mexico_content exactly"


def _cited_artifacts(db: Session, rates, slabs) -> tuple:
    from app.modules.payroll.models import SourceArtifact

    ids = {r.source_document_id for r in list(rates) + list(slabs)}
    unlinked = None in ids
    ids.discard(None)
    artifacts = db.query(SourceArtifact).filter(SourceArtifact.id.in_(ids or {-1})).all()
    return artifacts, unlinked


def pack_golden_check(db: Session, pack) -> dict:
    """Every Mexico golden vector whose pay date is inside the pack window,
    re-run with the fixture's statutory rows REPLACED by this pack's rows
    (shared run_pack_golden_vectors, the SG/HK precedent)."""
    rows_on: dict = {}

    def bind(context, pay_date):
        if pay_date not in rows_on:
            rows_on[pay_date] = service.pack_rows_for_golden(db, pack, pay_date)
        rate_map, slabs = rows_on[pay_date]
        return {"rate_map": rate_map, "slabs": slabs}

    return service.run_pack_golden_vectors(db, pack, _GOLDEN_DIR, bind)


def activation_checks(db: Session, pack, actor_id: Optional[int] = None) -> list:
    """The Phase 2 activation conditions in order, each met / unmet with its
    reason (shown in the activation-readiness panel)."""
    rates, slabs = _pack_rows(db, pack)
    checks = []
    ok, detail = _content_check(pack, rates, slabs)
    checks.append({"key": "content", "label": "Content present and exact", "met": ok, "detail": detail})

    artifacts, unlinked = _cited_artifacts(db, rates, slabs)
    incomplete = [a.id for a in artifacts if not (a.source_url and a.checksum_sha256 and a.file_path)]
    if not rates and not slabs:
        ev = (False, "the pack has no rows, so no source evidence is linked")
    elif unlinked:
        ev = (False, "a row has no source_document_id")
    elif incomplete:
        ev = (False, f"source artifact(s) {incomplete[:5]} lack a URL, SHA-256 or saved file")
    else:
        ev = (True, f"every row links one of {len(artifacts)} hashed source file(s)")
    checks.append({"key": "evidence", "label": "Every row linked to a hashed source", "met": ev[0], "detail": ev[1]})

    unreviewed = [a.id for a in artifacts if a.reviewer_approved_at is None or a.reviewer_id is None]
    self_reviewed = [a.id for a in artifacts if actor_id is not None and a.reviewer_id == actor_id]
    if not artifacts:
        g1 = (False, "no cited source artifact exists to review (gate G1)")
    elif unreviewed:
        g1 = (False, f"G1 human review is missing on source artifact(s) {unreviewed[:5]}")
    elif self_reviewed:
        g1 = (False, f"you reviewed source artifact(s) {self_reviewed[:5]} — the G1 reviewer may not be the activator")
    else:
        g1 = (True, "every cited source is G1-reviewed by a Super Admin other than the activator")
    checks.append({"key": "g1_review", "label": "G1 human review by a non-activator", "met": g1[0], "detail": g1[1]})

    golden = pack_golden_check(db, pack)
    if not golden["casesInWindow"]:
        gd = (False, f"no Mexico golden vector falls inside {pack.pack_id} v{pack.version}'s window "
                     f"(tests/fixtures/{_GOLDEN_DIR}/)")
    elif golden["failures"]:
        gd = (False, f"{pack.pack_id} v{pack.version}'s own rows do not reproduce {len(golden['failures'])} of "
                     f"{golden['casesInWindow']} golden vector(s): "
                     + ", ".join(f["case"] for f in golden["failures"][:5]))
    else:
        gd = (True, f"the pack's own rows reproduce all {golden['casesInWindow']} golden vector(s) in its window")
    checks.append({"key": "golden", "label": "Pack-bound golden PASS", "met": gd[0], "detail": gd[1]})
    return checks


def activation_readiness(db: Session, pack_row_id: int, actor_id: Optional[int] = None) -> dict:
    from app.modules.payroll.models import JurisdictionPack

    pack = db.get(JurisdictionPack, pack_row_id)
    if pack is None or pack.jurisdiction_country != MX:
        raise NotFoundException("Mexico pack", pack_row_id)
    rates, _slabs = _pack_rows(db, pack)
    warnings = []
    pending = sorted({r.component_key for r in rates if r.component_key in _content.MX_PENDING_G2_KEYS
                      or _content.PENDING_G2 in (r.label or "")})
    if pending:
        # Q2 (b) dropped: a [PENDING G2] parameter never blocks activation —
        # the engine blocks only the affected ZLFN employees (decision 4).
        warnings.append({"key": "pending_g2", "detail": f"{', '.join(pending)} is [PENDING G2]: until SUA "
                         "reconciliation confirms it, the engine BLOCKS only ZLFN employees whose SBC falls in the "
                         "CEAV lowest band; everyone else is calculated."})
    checks = activation_checks(db, pack, actor_id)
    return {"pack": _pack_view(db, pack), "checks": checks, "warnings": warnings,
            "activatable": all(c["met"] for c in checks),
            "note": "The shared gates also apply: four-eyes (approver may not activate, editor may not approve), the "
                    "transition graph, a linked pack source and the latest MX golden-certification run PASS."}


# ---- packs and read-only content ----

def _pack_view(db: Session, pack) -> dict:
    rates, slabs = _pack_rows(db, pack)
    return {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status,
            "state": pack.jurisdiction_state, "parentPackId": pack.parent_pack_id,
            "effectiveFrom": _iso(pack.effective_from), "effectiveTo": _iso(pack.effective_to),
            "contributionRates": len(rates), "taxSlabs": len(slabs)}


def list_packs(db: Session) -> list:
    from app.modules.payroll.models import JurisdictionPack

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == MX,
                                               JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.id).all())
    return [_pack_view(db, p) for p in sorted(packs, key=lambda p: (p.jurisdiction_state is not None,
                                                                     p.jurisdiction_state or "", p.id))]


def _national_pack(db: Session, pack_row_id: Optional[int] = None):
    from app.modules.payroll.models import JurisdictionPack

    q = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == MX,
                                          JurisdictionPack.pack_type == "tax",
                                          JurisdictionPack.jurisdiction_state.is_(None))
    if pack_row_id is not None:
        pack = q.filter(JurisdictionPack.id == pack_row_id).first()
        if pack is None:
            raise NotFoundException("Mexico national pack", pack_row_id)
        return pack
    return q.order_by(JurisdictionPack.id.desc()).first()


def _source_view(db: Session, source_document_id) -> Optional[dict]:
    from app.modules.payroll.models import SourceArtifact

    if source_document_id is None:
        return None
    a = db.get(SourceArtifact, source_document_id)
    if a is None:
        return None
    return {"id": a.id, "title": a.title, "url": a.source_url, "sha256": a.checksum_sha256, "file": a.file_path,
            "reviewed": a.reviewer_approved_at is not None}


_VIEW_RATE_PREFIXES = {
    "uma": ("mx_uma_", "mx_subsidy_"),
    "imss": ("mx_imss_", "mx_sbc_"),
    "ceav": ("mx_ceav_",),
    "infonavit": ("mx_infonavit_",),
    "benefits": ("mx_aguinaldo_", "mx_vacation_", "mx_sunday_"),
    "isr": (),
    "minwage": (),
}
_VIEW_SLAB_RULES = {
    "isr": (_content.MX_ISR_TARIFF_RULE,), "minwage": (_content.MX_MIN_WAGE_RULE,),
    "ceav": (_content.MX_CEAV_BAND_RULE,), "benefits": (_content.MX_WORKWEEK_RULE, _content.MX_VACATION_DAYS_RULE),
    "uma": (), "imss": (), "infonavit": (),
}
CONTENT_FAMILIES = tuple(_VIEW_RATE_PREFIXES)


def _in_window(row, on: date) -> bool:
    return ((row.effective_from is None or row.effective_from <= on)
            and (row.effective_to is None or row.effective_to >= on))


def content_view(db: Session, kind: str, on: Optional[date] = None, pack_row_id: Optional[int] = None) -> dict:
    """Read-only pack content of one family, as legally in force on `on`.
    `on` is explicit; when absent the pack's own effective_from is used —
    never the server date (Phase 2 Q5). Content is edited only through the
    governed pack lifecycle."""
    if kind not in _VIEW_RATE_PREFIXES:
        raise NotFoundException("Mexico content family", kind)
    pack = _national_pack(db, pack_row_id)
    base = {"family": kind, "editable": False, "editVia": "governed pack lifecycle (Draft → review → approve)"}
    if pack is None:
        return {**base, "pack": None, "on": _iso(on), "onSource": "query" if on else None,
                "awaitingTranscription": True, "rates": [], "slabs": [], "contentOnly": {}}
    on_source = "query" if on is not None else "packEffectiveFrom"
    on = on or pack.effective_from
    rates, slabs = _pack_rows(db, pack)
    prefixes, rules = _VIEW_RATE_PREFIXES[kind], _VIEW_SLAB_RULES[kind]
    rate_rows = [r for r in rates if prefixes and r.component_key.startswith(prefixes) and _in_window(r, on)]
    slab_rows = [s for s in slabs if s.rule_type in rules and _in_window(s, on)]
    out = {**base, "pack": _pack_view(db, pack), "on": _iso(on), "onSource": on_source,
           "awaitingTranscription": not (rate_rows or slab_rows),
           "rates": [{"id": r.id, "key": r.component_key, "label": r.label,
                      "employeeRatePct": _plain(r.employee_rate_pct), "employerRatePct": _plain(r.employer_rate_pct),
                      "amount": _plain(r.flat_amount), "text": r.text_value,
                      "effectiveFrom": _iso(r.effective_from), "effectiveTo": _iso(r.effective_to),
                      "pendingG1": _content.PENDING_G1 in (r.label or ""),
                      "pendingG2": _content.PENDING_G2 in (r.label or ""),
                      "source": _source_view(db, r.source_document_id)} for r in rate_rows],
           "slabs": [{"id": s.id, "ruleType": s.rule_type, "key": s.filing_status, "label": s.rate_label,
                      "formula": s.tax_formula, "min": _plain(s.min_amount), "max": _plain(s.max_amount),
                      "amount": _plain(s.flat_amount), "ratePct": _plain(s.rate_pct), "table": s.tax_table_number,
                      "effectiveFrom": _iso(s.effective_from), "effectiveTo": _iso(s.effective_to),
                      "pendingG1": _content.PENDING_G1 in (s.rate_label or ""),
                      "source": _source_view(db, s.source_document_id)} for s in slab_rows],
           "contentOnly": {}}
    if kind == "ceav":
        out["contentOnly"]["schedule"] = [
            {"year": b.year, "lower": b.lower_multiple, "lowerUnit": b.lower_unit, "upper": b.upper_multiple,
             "upperUnit": b.upper_unit, "employerPct": b.employer_pct, "seeded": b.year == _content.MX_CEAV_SEEDED_YEAR,
             "source": b.source} for b in _content.MX_CEAV_SCHEDULE]
    if kind == "minwage":
        out["contentOnly"]["zlfnMunicipalities"] = [
            {"state": m.state, "municipality": m.municipality, "source": m.source} for m in _content.MX_ZLFN_MUNICIPALITIES]
    return out


def isn_states(db: Session) -> list:
    """All 32 federal entities with their ISN pack and readiness state. A state
    without an Active pack is unsupported — payroll for it BLOCKS (MX-045)."""
    from app.modules.payroll.models import JurisdictionPack, StateLocalProgramReadiness

    packs = {}
    for p in (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == MX,
                                                JurisdictionPack.pack_type == "tax",
                                                JurisdictionPack.jurisdiction_state.isnot(None))
              .order_by(JurisdictionPack.id).all()):
        packs.setdefault(p.jurisdiction_state, []).append(p)
    readiness = {r.jurisdiction_state: r for r in db.query(StateLocalProgramReadiness)
                 .filter(StateLocalProgramReadiness.jurisdiction_country == MX,
                         StateLocalProgramReadiness.program == "OTHER_STATE_PAYROLL").all()}
    out = []
    for code, name in _content.MX_FEDERAL_ENTITIES:
        state_packs = [_pack_view(db, p) for p in packs.get(code, [])]
        live = any(p["status"] == "Active" for p in state_packs)
        ready = readiness.get(code)
        out.append({"code": code, "name": name, "inScope": code in _content.MX_ISN_STATES_IN_SCOPE,
                    "packs": state_packs, "supported": live, "payroll": "SUPPORTED" if live else "BLOCKED",
                    "readiness": None if ready is None else {"program": ready.program, "legalStatus": ready.legal_status,
                                                             "registrationRequired": ready.registration_required}})
    return out


# ---- organisations ----

def list_organizations(db: Session) -> list:
    from app.modules.organizations.models import Organization

    from app.modules.payroll.models import CompanyComplianceDetails, PayrollMxEmployerProfile

    # An organisation is "Mexican" here if it has a Mexico employee, a Mexico
    # legal employer (Phase 3 onboarding comes before any employee), or Mexico
    # as its company jurisdiction.
    org_ids = {row[0] for row in db.query(PayrollEmployee.organization_id)
               .filter(PayrollEmployee.country_code == MX).distinct().all()}
    org_ids |= {row[0] for row in db.query(PayrollMxEmployerProfile.organization_id).distinct().all()}
    org_ids |= {row[0] for row in db.query(CompanyComplianceDetails.organization_id)
                .filter(CompanyComplianceDetails.jurisdiction_country.in_((MX, "Mexico"))).all()}
    orgs = db.query(Organization).filter(Organization.id.in_(org_ids or {-1})).order_by(Organization.id).all()
    return [{"id": o.id, "name": o.organization_name} for o in orgs]


def _org(db: Session, org_id: int):
    from app.modules.organizations.models import Organization

    org = db.get(Organization, org_id)
    if org is None:
        raise NotFoundException("Organization", org_id)
    return org


def list_employees(db: Session, org_id: int) -> list:
    _org(db, org_id)
    rows = (db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == org_id,
                                             PayrollEmployee.country_code == MX)
            .order_by(PayrollEmployee.id).all())
    return [{"id": e.id, "name": e.name, "employee_code": e.employee_code} for e in rows]


# ---- earning classifications (MX-005 / MX-006) ----

_ISR = ("TAXABLE", "EXEMPT", "PARTIAL")
_SBC = ("FIXED", "VARIABLE", "EXCLUDED")
_CFDI_NODES = ("PERCEPCION", "DEDUCCION", "OTRO_PAGO", "SEPARACION")
_CLASSIFICATION_FIELDS = ("earning_code", "label", "effective_from", "isr_treatment", "isr_exempt_rule_key",
                          "sbc_treatment", "sbc_exclusion_condition", "infonavit_included", "isn_default_included",
                          "isn_state_overrides", "ptu_wage_base_included", "cfdi_node_type", "cfdi_concept_code")


def _audit(db: Session, *, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None):
    service.record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                             old_value=old, new_value=new, reason=reason, legal_reference=SPEC, auto_commit=False)


def _refuse(db: Session, entity_type, entity_id, attempted, actor_id, message):
    db.rollback()
    _audit(db, actor_id=actor_id, action="refused", entity_type=entity_type, entity_id=entity_id or 0,
           new={"attempted": attempted, "result": "REFUSED"}, reason=message)
    db.commit()
    raise BadRequestException(message)


def classification_view(row) -> dict:
    return {"id": row.id, "organizationId": row.organization_id, "earningCode": row.earning_code, "label": row.label,
            "version": row.version, "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
            "isrTreatment": row.isr_treatment, "isrExemptRuleKey": row.isr_exempt_rule_key,
            "sbcTreatment": row.sbc_treatment, "sbcExclusionCondition": row.sbc_exclusion_condition,
            "infonavitIncluded": row.infonavit_included, "isnDefaultIncluded": row.isn_default_included,
            "isnStateOverrides": row.isn_state_overrides or {}, "ptuWageBaseIncluded": row.ptu_wage_base_included,
            "cfdiNodeType": row.cfdi_node_type, "cfdiConceptCode": row.cfdi_concept_code, "status": row.status,
            "createdById": row.created_by_id, "approvedById": row.approved_by_id,
            "approvedAt": _iso(row.approved_at), "sha256": row.sha256}


def _classification_sha(values: dict) -> str:
    payload = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in values.items()}
    return _hashlib.sha256(_json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def create_classification(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    """A new classification version, DRAFT. It is never live until a second
    Super Admin approves it."""
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    if actor_id is None:
        raise BadRequestException("A classification change needs an identified Super Admin.")
    org_id = data.get("organization_id")
    if org_id is not None:
        _org(db, org_id)
    code = (data.get("earning_code") or "").strip().upper()
    label = (data.get("label") or "").strip()
    eff = data.get("effective_from")
    if not code or not label or not isinstance(eff, date):
        raise BadRequestException("earning_code, label and effective_from are required")
    if data.get("isr_treatment") not in _ISR:
        raise BadRequestException(f"isr_treatment must be one of {', '.join(_ISR)}")
    if data.get("sbc_treatment") not in _SBC:
        raise BadRequestException(f"sbc_treatment must be one of {', '.join(_SBC)}")
    if data.get("cfdi_node_type") not in _CFDI_NODES:
        raise BadRequestException(f"cfdi_node_type must be one of {', '.join(_CFDI_NODES)}")
    if data["isr_treatment"] in ("EXEMPT", "PARTIAL") and not data.get("isr_exempt_rule_key"):
        raise BadRequestException("an EXEMPT or PARTIAL ISR treatment must name its exemption rule (MX-009)")
    if data["sbc_treatment"] == "EXCLUDED" and not data.get("sbc_exclusion_condition"):
        raise BadRequestException("an SBC exclusion must state its statutory/documentary condition (MX-022)")
    overrides = data.get("isn_state_overrides") or {}
    unknown = set(overrides) - {c for c, _ in _content.MX_FEDERAL_ENTITIES}
    if unknown:
        raise BadRequestException(f"unknown federal entity code(s) in isn_state_overrides: {', '.join(sorted(unknown))}")
    for field in ("infonavit_included", "isn_default_included", "ptu_wage_base_included"):
        if not isinstance(data.get(field), bool):
            raise BadRequestException(f"{field} must be true or false — every axis is decided explicitly (MX-005)")
    scope = C.organization_id.is_(None) if org_id is None else C.organization_id == org_id
    if db.query(C.id).filter(scope, C.earning_code == code, C.effective_from == eff).first():
        raise BadRequestException(f"{code} already has a version effective {eff.isoformat()} in this scope")
    latest = db.query(C).filter(scope, C.earning_code == code).order_by(C.version.desc()).first()
    values = {k: data.get(k) for k in _CLASSIFICATION_FIELDS}
    values.update(earning_code=code, label=label, isn_state_overrides=overrides or None, organization_id=org_id)
    row = C(**values, version=(latest.version + 1) if latest else 1, status="DRAFT", created_by_id=actor_id,
            sha256=_classification_sha(values))
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_earning_classification", entity_id=row.id,
           new={"earningCode": code, "version": row.version, "status": "DRAFT"})
    db.commit()
    db.refresh(row)
    return classification_view(row)


def _catalog_has_code(db: Session, code: str) -> bool:
    from app.modules.payroll.models import PayrollMxCfdiCatalogEntry, PayrollMxCfdiSchemaRelease

    return db.query(PayrollMxCfdiCatalogEntry.id).join(
        PayrollMxCfdiSchemaRelease, PayrollMxCfdiCatalogEntry.schema_release_id == PayrollMxCfdiSchemaRelease.id
    ).filter(PayrollMxCfdiSchemaRelease.status.in_(("Approved", "Active")),
             PayrollMxCfdiCatalogEntry.code == code).first() is not None


def approve_classification(db: Session, classification_id: int, actor_id: Optional[int]) -> dict:
    """Second Super Admin: DRAFT -> ACTIVE. The ACTIVE version before it in the
    same scope is SUPERSEDED (its window closes the day before), never edited
    away — historical CFDI/IMSS results keep their classification (MX-006).
    A canonical row needs its SAT concept code in an approved catalog (S28)."""
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    row = db.get(C, classification_id)
    if row is None:
        raise NotFoundException("Mexico earning classification", classification_id)
    et = "mx_earning_classification"
    if actor_id is None:
        _refuse(db, et, row.id, "approve", actor_id, "Approval needs an identified Super Admin.")
    if row.status != "DRAFT":
        _refuse(db, et, row.id, "approve", actor_id,
                f"only a DRAFT classification can be approved (this one is {row.status})")
    if row.created_by_id == actor_id:
        _refuse(db, et, row.id, "approve", actor_id,
                "You created this classification — a different Super Admin must approve it (maker-checker).")
    if row.organization_id is None and not (row.cfdi_concept_code and _catalog_has_code(db, row.cfdi_concept_code)):
        _refuse(db, et, row.id, "approve", actor_id,
                "A canonical classification needs its SAT concept code in an approved CFDI catalog release — the "
                "SAT Nómina 1.2 catalog (S28) is not VERIFIED yet, so no canonical row can go live.")
    scope = C.organization_id.is_(None) if row.organization_id is None else C.organization_id == row.organization_id
    newer = (db.query(C).filter(scope, C.earning_code == row.earning_code, C.status == "ACTIVE",
                                C.effective_from >= row.effective_from).first())
    if newer is not None:
        _refuse(db, et, row.id, "approve", actor_id,
                f"version {newer.version} (effective {newer.effective_from.isoformat()}) is already ACTIVE from the "
                "same date or later — approve versions in date order")
    for prior in db.query(C).filter(scope, C.earning_code == row.earning_code, C.status == "ACTIVE").all():
        prior.status = "SUPERSEDED"
        if prior.effective_to is None or prior.effective_to >= row.effective_from:
            prior.effective_to = row.effective_from - _timedelta(days=1)
        _audit(db, actor_id=actor_id, action="supersede", entity_type=et, entity_id=prior.id,
               new={"status": "SUPERSEDED", "effectiveTo": _iso(prior.effective_to), "by": row.id})
    row.status = "ACTIVE"
    row.approved_by_id = actor_id
    row.approved_at = _datetime.now(_timezone.utc)
    _audit(db, actor_id=actor_id, action="approve", entity_type=et, entity_id=row.id, new={"status": "ACTIVE"})
    db.commit()
    db.refresh(row)
    return classification_view(row)


def archive_classification(db: Session, classification_id: int, actor_id: Optional[int], reason: str) -> dict:
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    row = db.get(C, classification_id)
    if row is None:
        raise NotFoundException("Mexico earning classification", classification_id)
    if actor_id is None or not (reason or "").strip():
        raise BadRequestException("Archiving needs an identified Super Admin and a reason.")
    if row.status not in ("DRAFT", "ACTIVE"):
        _refuse(db, "mx_earning_classification", row.id, "archive", actor_id,
                f"a {row.status} classification is retained evidence and cannot be archived")
    old = row.status
    row.status = "ARCHIVED"
    _audit(db, actor_id=actor_id, action="archive", entity_type="mx_earning_classification", entity_id=row.id,
           old={"status": old}, new={"status": "ARCHIVED"}, reason=reason)
    db.commit()
    db.refresh(row)
    return classification_view(row)


def list_classifications(db: Session, organization_id: Optional[int] = None, on: Optional[date] = None) -> list:
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    q = db.query(C).filter(C.organization_id.is_(None) if organization_id is None
                           else C.organization_id == organization_id)
    if on is not None:
        q = q.filter(C.status.in_(("ACTIVE", "SUPERSEDED")), C.effective_from <= on,
                     (C.effective_to.is_(None)) | (C.effective_to >= on))
    return [classification_view(r) for r in q.order_by(C.earning_code, C.version).all()]


def classification_in_force(db: Session, organization_id: Optional[int], earning_code: str, on: date):
    """The classification legally in force for `earning_code` on `on`: the
    organisation's own row if it has one, else the platform catalogue's.
    Historical dates return the SUPERSEDED row that was in force (MX-006)."""
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    def pick(scope):
        return (db.query(C).filter(scope, C.earning_code == earning_code.upper(),
                                   C.status.in_(("ACTIVE", "SUPERSEDED")), C.effective_from <= on,
                                   (C.effective_to.is_(None)) | (C.effective_to >= on))
                .order_by(C.effective_from.desc()).first())

    row = pick(C.organization_id == organization_id) if organization_id is not None else None
    return row or pick(C.organization_id.is_(None))


# ---- CFDI schema releases and catalog entries (MX-015) ----

def release_view(db: Session, row) -> dict:
    from app.modules.payroll.models import PayrollMxCfdiCatalogEntry

    entries = db.query(PayrollMxCfdiCatalogEntry).filter(PayrollMxCfdiCatalogEntry.schema_release_id == row.id).count()
    return {"id": row.id, "cfdiVersion": row.cfdi_version, "complementVersion": row.complement_version,
            "revision": row.revision, "xsdChecksum": row.xsd_checksum, "catalogRelease": row.catalog_release,
            "pacValidationVersion": row.pac_validation_version, "sourceDocumentId": row.source_document_id,
            "status": row.status, "createdById": row.created_by_id, "approvedById": row.approved_by_id,
            "entries": entries}


def list_releases(db: Session) -> list:
    from app.modules.payroll.models import PayrollMxCfdiSchemaRelease

    return [release_view(db, r) for r in
            db.query(PayrollMxCfdiSchemaRelease).order_by(PayrollMxCfdiSchemaRelease.id).all()]


def list_catalog_entries(db: Session, release_id: int) -> list:
    from app.modules.payroll.models import PayrollMxCfdiCatalogEntry, PayrollMxCfdiSchemaRelease

    if db.get(PayrollMxCfdiSchemaRelease, release_id) is None:
        raise NotFoundException("CFDI schema release", release_id)
    rows = (db.query(PayrollMxCfdiCatalogEntry).filter(PayrollMxCfdiCatalogEntry.schema_release_id == release_id)
            .order_by(PayrollMxCfdiCatalogEntry.catalog_name, PayrollMxCfdiCatalogEntry.code).all())
    return [{"id": e.id, "releaseId": e.schema_release_id, "catalogName": e.catalog_name, "code": e.code,
             "description": e.description, "validFrom": _iso(e.valid_from), "validTo": _iso(e.valid_to)} for e in rows]


def create_release(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxCfdiSchemaRelease

    if actor_id is None:
        raise BadRequestException("A schema release needs an identified Super Admin.")
    if not (data.get("cfdi_version") and data.get("complement_version")):
        raise BadRequestException("cfdi_version and complement_version are required")
    row = PayrollMxCfdiSchemaRelease(**{k: data.get(k) for k in (
        "cfdi_version", "complement_version", "revision", "xsd_checksum", "catalog_release", "pac_validation_version",
        "source_document_id")}, status="Draft", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_cfdi_schema_release", entity_id=row.id,
           new={"status": "Draft"})
    db.commit()
    db.refresh(row)
    return release_view(db, row)


def add_catalog_entry(db: Session, release_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxCfdiCatalogEntry, PayrollMxCfdiSchemaRelease

    release = db.get(PayrollMxCfdiSchemaRelease, release_id)
    if release is None:
        raise NotFoundException("CFDI schema release", release_id)
    if actor_id is None:
        raise BadRequestException("A catalog entry needs an identified Super Admin.")
    if release.status != "Draft":
        _refuse(db, "mx_cfdi_schema_release", release.id, "add_entry", actor_id,
                f"catalog entries are frozen once a release leaves Draft (this one is {release.status})")
    if not (data.get("catalog_name") and data.get("code") and data.get("description")):
        raise BadRequestException("catalog_name, code and description are required")
    entry = PayrollMxCfdiCatalogEntry(schema_release_id=release.id, catalog_name=data["catalog_name"],
                                      code=data["code"], description=data["description"],
                                      valid_from=data.get("valid_from"), valid_to=data.get("valid_to"),
                                      attributes=data.get("attributes"))
    db.add(entry)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_cfdi_catalog_entry", entity_id=entry.id,
           new={"release": release.id, "catalog": entry.catalog_name, "code": entry.code})
    db.commit()
    return {"id": entry.id, "releaseId": release.id, "catalogName": entry.catalog_name, "code": entry.code,
            "description": entry.description, "validFrom": _iso(entry.valid_from), "validTo": _iso(entry.valid_to)}


RELEASE_ACTIONS = {"submit": ("Draft", "In Review"), "approve": ("In Review", "Approved"),
                   "activate": ("Approved", "Active"), "supersede": ("Active", "Superseded")}


def transition_release(db: Session, release_id: int, action: str, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxCfdiSchemaRelease

    release = db.get(PayrollMxCfdiSchemaRelease, release_id)
    if release is None:
        raise NotFoundException("CFDI schema release", release_id)
    et = "mx_cfdi_schema_release"
    if action not in RELEASE_ACTIONS:
        raise BadRequestException(f"action must be one of {', '.join(RELEASE_ACTIONS)}")
    if actor_id is None:
        _refuse(db, et, release.id, action, actor_id, "A release change needs an identified Super Admin.")
    source, target = RELEASE_ACTIONS[action]
    if release.status != source:
        _refuse(db, et, release.id, action, actor_id,
                f"{action} needs a {source} release (this one is {release.status})")
    if action == "approve" and release.created_by_id == actor_id:
        _refuse(db, et, release.id, action, actor_id,
                "You registered this release — a different Super Admin must approve it (maker-checker).")
    if action == "activate":
        _refuse(db, et, release.id, action, actor_id,
                "Pinning a CFDI release live needs the Phase 7 PAC validation (MX-015) — activation is refused in "
                "Phase 2.")
    old = release.status
    release.status = target
    if action == "approve":
        release.approved_by_id = actor_id
    _audit(db, actor_id=actor_id, action=action, entity_type=et, entity_id=release.id,
           old={"status": old}, new={"status": target})
    db.commit()
    db.refresh(release)
    return release_view(db, release)
