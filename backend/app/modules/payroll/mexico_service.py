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

from app.core.authz.scopes import organization_scoped
from app.core.exceptions import BadRequestException
from app.modules.payroll import retention_service, service
from app.modules.payroll.engine.countries.mexico import ENGINE_VERSION
from app.modules.payroll.engine.countries.mexico_content import GATES, SPEC
from app.modules.payroll.models import (
    EmployeeStatutoryProfile, PayrollEmployee, PayrollRun, PayslipItem,
)

MX = "MX"


def _employee(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = service.get_employee_by_id(db, employee_id, organization_id)  # 404s outside the tenant
    if service._normalize_country(employee.country_code or "") != MX:
        raise BadRequestException(f"employee #{employee_id} is not a Mexico employee")
    return employee


# ---- Readiness (spec §22) ----

# Phase 10d (plan D10): a gate, or an owner (legal) decision, is SIGNED /
# RECORDED only by evidence — a source artifact tagged MX-GATE-Gn /
# MX-DECISION-…, not superseded, with an UPLOADED document, reviewed by a
# Super Admin other than its creator (mark_source_artifact_reviewed refuses
# the creator). Created / uploaded but not reviewed is SUBMITTED. Signing is a
# human act on real evidence; the build signs nothing.
RELEASE_GATES_DOC = "docs/mexico/release-gates/README.md"
ACTIVATION_RUNBOOK_DOC = "docs/mexico/MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md"
RELEASE_CHECKLIST_DOC = "docs/mexico/MEXICO_RELEASE_CHECKLIST.md"
UNKNOWN_RUNBOOK_DOC = "docs/mexico/MEXICO_UNKNOWN_STATE_RUNBOOK.md"
OWNER_DECISIONS = (
    ("MX-D-RETENTION-PERIOD", "Retention period per record category", "MX-DECISION-RETENTION-PERIOD"),
    ("MX-D-RETENTION-END", "Deletion vs anonymisation at end of retention", "MX-DECISION-RETENTION-END"),
    ("MX-D-HOSTING", "Hosting and cross-border transfers (2025 privacy law)", "MX-DECISION-HOSTING"),
    ("MX-D-Q9", "Q9 — Mexican identifiers (RFC, CURP, NSS, CLABE) at rest", "MX-DECISION-Q9"),     # Phase 10e
)


def _mx_evidence(db: Session, tag: str):
    """(the accepted artifact or None, whether any live artifact exists)."""
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag, SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    accepted = next((r for r in rows if r.reviewer_id and r.file_path is not None and r.created_by_id is not None
                     and r.reviewer_id != r.created_by_id), None)
    return accepted, bool(rows)


def gate_states(db: Session) -> list:
    """G1–G8 from their evidence (OPEN / SUBMITTED / SIGNED)."""
    from app.modules.payroll.mexico_employer_service import GATE_DEFINITIONS

    out = []
    for key, label in GATES:
        accepted, submitted = _mx_evidence(db, f"MX-GATE-{key}")
        out.append({"gate": key, "label": label, "state": "SIGNED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "evidenceTag": f"MX-GATE-{key}", "artifactId": accepted.id if accepted else None,
                    "definition": GATE_DEFINITIONS[key], "checklist": f"docs/mexico/release-gates/{key}/CHECKLIST.md"})
    return out


def owner_decisions(db: Session) -> list:
    out = []
    for key, label, tag in OWNER_DECISIONS:
        accepted, submitted = _mx_evidence(db, tag)
        out.append({"key": key, "label": label, "evidenceTag": tag,
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def statutory_summary(db: Session) -> dict:
    gates = gate_states(db)
    signed = sum(g["state"] == "SIGNED" for g in gates)
    retention = retention_service.retention_policies(db, MX)
    from app.modules.payroll import mexico_dormancy, mexico_pilot_service
    from app.modules.billing.models import JurisdictionServiceRegistry

    row = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == MX).first()
    registry = row.availability if row is not None else None
    flag = mexico_dormancy.flag_enabled()
    available = flag and registry == service.SERVICE_REGISTRY_OPEN
    grants = mexico_pilot_service.list_grants(db)
    active = [g for g in grants if g["state"] == "ACTIVE"]
    level = "AVAILABLE" if available else (f"PILOT ({len(active)} organisation{'s' if len(active) != 1 else ''})"
                                           if flag and active else "DORMANT")
    return {"jurisdiction": MX, "spec": SPEC, "available": available, "level": level,
            "registry": registry, "onboardingEnabled": flag,
            "pilotGrants": grants, "pilotPreconditions": mexico_pilot_service.pilot_preconditions(db),
            "onboardingPaused": mexico_dormancy.onboarding_paused(db),                  # Phase 10g
            "gaPreconditions": mexico_pilot_service.ga_preconditions(db),
            "engineVersion": ENGINE_VERSION, "phase": 10, "gates": gates, "signedGates": signed,
            "decisions": owner_decisions(db),
            "retention": [{"category": c["category"], "label": c["label"], "state": c["state"],
                           "blocker": c["blocker"]} for c in retention["categories"]],
            "documents": {"releaseGates": RELEASE_GATES_DOC, "activationRunbook": ACTIVATION_RUNBOOK_DOC,
                          "releaseChecklist": RELEASE_CHECKLIST_DOC, "unknownRunbook": UNKNOWN_RUNBOOK_DOC},
            "note": f"Live Mexican payroll stays gated until G1–G8 are signed (ZP-MX-ENG-001 §22) — {signed}/8 signed. "
                    "A gate is signed only by uploaded evidence reviewed by a second Super Admin. The onboarding flag "
                    "is a kill switch only: Mexico opens for everyone only when the registry is AVAILABLE (all eight "
                    "gates, Q9, the identity key), or for one named organisation under an approved, non-binding "
                    "pilot grant. Every Mexican calculation is BLOCKED until its content is transcribed."}


# ---- Governance hooks ----

def transition_mx_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """PLANNED <-> AVAILABLE. AVAILABLE is refused until every gate G1–G8 is
    signed (spec §22: approval of the build is not approval of live payroll)."""
    def readiness():
        # Phase 10e: every gate SIGNED, Q9 RECORDED and the identity key configured.
        from app.modules.payroll import mexico_pilot_service

        unmet = [c for c in mexico_pilot_service.ga_preconditions(db) if not c["met"]]
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
    gates 1 (content exact) and 2 (every row source-linked) to hold already,
    and (Phase 11d) every cited source to be VERIFIED, not an archive copy."""
    if pack.status != "QA":
        return (f"Mexico pack approval is refused: {pack.pack_id} v{pack.version} is {pack.status} — move it through "
                "In Review to QA first (Draft → In Review → QA → Approved).")
    # Gate 1 (content), gate 2 (evidence) and, Phase 11d, every cited source
    # VERIFIED: an archive copy backs a Draft pack only, never an Approved one.
    for check in activation_checks(db, pack, actor_id):
        if check["key"] in ("content", "evidence", "sources_verified") and not check["met"]:
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
    """Completion W4-3a (Phase 12c, plan E6 / D3): the real gate in place of the
    permanent refusal — its release gates SIGNED, its statutory content Active,
    and its fields proven on a committed Mexican payslip (mexico_report_service)."""
    from app.modules.payroll import mexico_report_service

    return mexico_report_service.mx_report_activation_refusal(db, template)


# ---- Calculation and run hooks ----

def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None, **kwargs) -> dict:
    """Phase 6: the guarded, read-only input builder (mexico_run_service) —
    refused unless Mexico onboarding is enabled AND the organisation is
    Mexican; every engine input as of the run's pay date."""
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.calc_inputs(db, run, employee, resolved_pack, as_of, **kwargs)


def _mx_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """Reached only for a run with Mexican payslips (service.advance_payroll_run_
    status). APPROVED: preflight clear + fingerprint + ledger commit (MX-039/040);
    AUTHORIZED / PAID refused until CFDI (Phase 7) and bank settlement (Phase 10)."""
    from app.modules.payroll import mexico_run_service

    mexico_run_service.before_run_transition(db, run, next_status, actor_id)


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """Every Mexican payment item is held until bank settlement (Phase 10, D11)."""
    from app.modules.payroll import mexico_run_service

    return mexico_run_service.payment_treatment(db, organization_id, run, items)


def _mx_pack_holidays(db: Session, year: int) -> list:
    """Mexican mandatory rest days are not seeded from a reviewed source yet —
    none is invented here."""
    return []


def _mx_statutory_profile_errors(data) -> list:
    """Phase 4b — shape checks (mexico_employee_service). Reachable only for a
    Mexican employee, which cannot exist while MX_TENANT_ONBOARDING_ENABLED is off."""
    from app.modules.payroll import mexico_employee_service

    return mexico_employee_service.statutory_profile_errors(data)


def _mx_profile_values(db: Session, employee, data, previous) -> dict:
    """Phase 4b — full validation, carry-forward and identity tokens (Q7 strict)."""
    from app.modules.payroll import mexico_employee_service

    return mexico_employee_service.profile_values(db, employee, data, previous)


def _mx_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    return None


# ---- Records governance (retention_service) ----
# retention_service._report_country asks EVERY jurisdiction module for its
# settings on each report download, so this must answer (never raise).
# Phase 10c (plan D8): the Mexican record categories are declared, but the
# retention periods and the hosting / cross-border stance are legal decisions
# not taken yet — the owner decision stays OPEN, so every category is
# BLOCKED_UNDECIDED and NOTHING is purged. Legal holds work now (shared
# service). A CFDI (stamped XML and its events) is never deleted at all.
MX_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and Mexican calculation snapshots (incl. corrections)"),
    ("CFDI", "CFDI de nómina XML, stamps, cancellations and their events — never deleted"),
    ("IMSS_INFONAVIT", "IMSS movements, SUA periods, branch ledgers and INFONAVIT notices"),
    ("AUTHORITY_FILINGS", "SAT ISR, IMSS, INFONAVIT and ISN liabilities, returns and payment evidence"),
    ("PAYMENTS_AND_JOURNAL", "Salary payment batches and outcomes; payroll journal exports"),
    ("TERMINATIONS", "Terminations, finiquito / liquidación evidence"),
    ("PTU_AND_ANNUAL", "PTU allocations and annual ISR adjustments"),
    ("EMPLOYEE_IDENTITY", "RFC, CURP, NSS, CLABE and the Mexican statutory profile"),
)


def _decision_state(db: Session, key: str) -> str:
    """RECORDED only by reviewed evidence (Phase 10d); OPEN until then."""
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    """A statutory record of the employee that must be kept (so the employee is
    deactivated, never deleted) — the first found, by label."""
    from app.modules.payroll import models as m

    for model, label in ((m.PayrollMxCfdiDocument, "CFDI documents"),
                         (m.PayrollMxImssMovement, "IMSS movements"),
                         (m.PayrollMxTermination, "terminations"),
                         (m.PayrollMxPtuAllocation, "PTU allocations"),
                         (m.PayrollMxAnnualIsrAdjustment, "annual ISR adjustments"),
                         (m.PayrollMxPaymentItem, "salary payments"),
                         (m.PayrollMxVacationRecord, "vacation records")):
        if db.query(model.id).filter(model.organization_id == organization_id,
                                     model.employee_id == employee_id).first():
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return db.query(EmployeeStatutoryProfile.id).filter(EmployeeStatutoryProfile.employee_id == employee_id,
                                                        EmployeeStatutoryProfile.country_code == MX).first() is not None


def is_mx_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == MX
                                        or str(getattr(report, "report_type", "") or "").startswith("MX_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=MX, label="Mexico", categories=MX_RETENTION_CATEGORIES,
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
                                    s.rate_pct, s.effective_from, s.effective_to, s.tax_table_number,
                                    jurisdiction_state=s.jurisdiction_state) for s in slabs]
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
                    if scope == "national" and kind != "text" and k not in _content.MX_PER_CASE_KEYS}
        required |= set(_content.MX_REQUIRED_TEXT_KEYS)
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

    # Phase 11d (gap register A9): an ARCHIVE_COPY_VERIFIED source may back a
    # Draft pack only — every cited file must be VERIFIED (a direct download)
    # in docs/mexico/sources/SOURCES_MANIFEST.csv, with its entry in
    # VERIFICATION_LOG.csv, before the pack goes live.
    from app.modules.payroll import mexico_sources

    manifest_rows, log_rows = mexico_sources.read_rows(), mexico_sources.read_log()
    if not artifacts:
        sv = (False, "no cited source to confirm")
    elif not manifest_rows:
        sv = (False, "SOURCES_MANIFEST.csv cannot be read — no source can be confirmed VERIFIED")
    else:
        unverified = [a.id for a in artifacts
                      if not mexico_sources.verified_artifact(manifest_rows, a.source_url, a.checksum_sha256,
                                                              log_rows)]
        sv = ((False, f"source artifact(s) {unverified[:5]} are not VERIFIED in SOURCES_MANIFEST.csv with a matching "
                      "VERIFICATION_LOG.csv entry — an archive copy feeds a Draft pack only; verify a direct "
                      "download from the official URL with scripts/verify_mexico_sources.py first")
              if unverified else (True, f"all {len(artifacts)} cited source file(s) are VERIFIED"))
    checks.append({"key": "sources_verified", "label": "Every cited source VERIFIED (not an archive copy)",
                   "met": sv[0], "detail": sv[1]})

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


def _state_pack(db: Session, pack_row_id: Optional[int]):
    """W5-1: one state ISN pack (its id is required — 32 entities, no default)."""
    from app.modules.payroll.models import JurisdictionPack

    if pack_row_id is None:
        raise BadRequestException("pack_id (a Mexico state ISN pack) is required")
    pack = (db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id,
                                              JurisdictionPack.jurisdiction_country == MX,
                                              JurisdictionPack.pack_type == "tax",
                                              JurisdictionPack.jurisdiction_state.isnot(None)).first())
    if pack is None:
        raise NotFoundException("Mexico state ISN pack", pack_row_id)
    return pack


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
    "isn": ("mx_isn_",),                                         # W5-1: a STATE pack (pack_id required)
}
_VIEW_SLAB_RULES = {
    "isr": (_content.MX_ISR_TARIFF_RULE,), "minwage": (_content.MX_MIN_WAGE_RULE,),
    "ceav": (_content.MX_CEAV_BAND_RULE,), "benefits": (_content.MX_WORKWEEK_RULE, _content.MX_VACATION_DAYS_RULE),
    "uma": (), "imss": (), "infonavit": (), "isn": (),
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
    pack = _state_pack(db, pack_row_id) if kind == "isn" else _national_pack(db, pack_row_id)
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


# W5-1: the module-direct rule switches a gate owner decides (DECISIONS_PENDING).
# None = undecided: every calculation that needs it BLOCKS with its own code.
_RULE_SWITCHES = (
    ("MX_EXEMPTION_WAGE_REFERENCE", "D-07", "Unit of the LISR Art. 93 exempt limits"),
    ("MX_SPECIAL_PAY_WITHHOLDING_METHOD", "D-08", "Withholding method for a special payment in its own run"),
    ("MX_MONTHLY_ORDINARY_INCOME_DAYS", "D-09", "Monthly ordinary income from a daily salary"),
    ("MX_INDEMNITY_SALARY_BASIS", "D-12", "Indemnity salary (LFT Art. 89)"),
    ("MX_SERVICE_YEARS_COUNT", "D-13", "Part years of service"),
    ("MX_SENIORITY_PREMIUM_WAGE_REFERENCE", "D-07b", "Seniority premium wage reference"),
    ("MX_PTU_CAP_EXCESS", "D-14", "PTU cap (LFT Art. 127 VIII): the excess"),
    ("MX_PTU_HISTORY_AVERAGE", "D-14", "PTU cap: the three-year average"),
)
# Content interfaces built with no transcribed rule yet (W3-5): None = BLOCK.
_RULE_INTERFACES = (
    ("MX_SBC_FIXED_INTEGRATION_RULE", "D-18", "FIXED SBC items (LSS Art. 30 I)"),
    ("MX_FIXED_DAYS_TERMINATION_RULE", "D-19", "Fixed salary days at termination"),
)


_CONCEPT_LABELS = {
    "AGUINALDO": "Aguinaldo", "VACATION_PREMIUM": "Vacation premium (prima vacacional)",
    "VACATION_PAYOUT": "Vacation paid out at termination", "PTU": "PTU (profit sharing)",
    "SEPARATION_SENIORITY_PREMIUM": "Seniority premium (prima de antigüedad)",
    "SEPARATION_PAYMENT": "Separation payment", "SEPARATION_INDEMNITY": "Indemnity",
    "OVERTIME": "Overtime (horas extra)", "SUNDAY_PREMIUM": "Sunday premium (prima dominical)",
}


def _citations_view(citations, manifest: dict, log: list) -> list:
    """Each (CODE/file, quoted wording) citation with the manifest row of the
    cited file (title, url, sha256, verification status)."""
    from app.modules.payroll import mexico_sources

    out = []
    for cite, ref in citations:
        row = manifest.get(cite)
        out.append({"cite": cite, "ref": ref, "title": row.get("title") if row else None,
                    "url": row.get("url") if row else None, "sha256": row.get("sha256") if row else None,
                    "status": mexico_sources.effective_status(row, log) if row else "NOT_IN_MANIFEST"})
    return out


def _cites(obj) -> tuple:
    return tuple(getattr(obj, "citations", None) or ((obj.source, obj.source_ref),))


def statutory_rules_view(db: Session, on: Optional[date] = None) -> dict:
    """W5-1: every module-direct Mexico rule family (not stored as pack rows),
    read-only, each with its quoted source wording, the manifest row of the
    cited file and the [PENDING G1] marker. Year-keyed families (annual ISR
    tariff, official holidays) show the year of `on`; `on` defaults to the
    national pack's effective_from, never the server date. Changed only by a
    code release that passes `verify_mexico_sources.py compare`."""
    from app.modules.payroll import mexico_sources
    from app.modules.payroll.engine.countries import mexico_rules as _r

    c = _content
    pack = _national_pack(db)
    on_source = "query" if on is not None else ("packEffectiveFrom" if pack is not None else None)
    on = on or (pack.effective_from if pack is not None else None)
    year = on.year if on else None
    manifest = {mexico_sources.cite_key(r): r for r in mexico_sources.read_rows()}
    log = mexico_sources.read_log()

    def item(key, label, citations, **extra):
        return {"key": key, "label": label, "pendingG1": True, "citations": _citations_view(citations, manifest, log),
                **extra}

    families = []

    def family(key, title, items, note=None):
        families.append({"family": key, "title": title, "items": items, "note": note,
                         "awaitingTranscription": not items})

    family("annualIsr", f"Annual ISR tariff {year or ''}".strip(), [
        item(b.lower, f"{b.lower} – {b.upper or 'en adelante'}", ((b.source, b.source_ref),),
             lower=b.lower, upper=b.upper, fixedQuota=b.fixed_quota, ratePct=b.rate_pct)
        for b in c.MX_ISR_ANNUAL_TARIFFS.get(year, ())])
    family("filingCalendar", "Filing calendar", [
        item(f"{r.report_type}{'/' + r.state if r.state else ''}", r.due_rule, _cites(r), reportType=r.report_type,
             frequency=r.frequency, dueDay=r.due_day, dueMonth=r.due_month, state=r.state)
        for r in c.MX_FILING_CALENDAR],
        note="IMSS monthly / bimonthly payment dates are not listed (gap A18)")
    family("specialPay", "Special pay: LISR Art. 93 exemptions and withholding", [
        item(k, _CONCEPT_LABELS.get(k, k), _cites(o)) for k, o in sorted(c.MX_SPECIAL_PAY_RULES.items())]
        + ([item("AGUINALDO_RULE", "Aguinaldo amount and payable-by date (LFT Art. 87)", _cites(c.MX_AGUINALDO_RULE))]
           if c.MX_AGUINALDO_RULE is not None else []))
    family("isnInclusion", "State ISN: special pay in the base", [
        item(f"{st}/{concept}", f"{st}: {_CONCEPT_LABELS.get(concept, concept)}", ((src, ref),), state=st,
             included=inc) for (st, concept), (inc, src, ref) in sorted(c.MX_SPECIAL_PAY_ISN_INCLUSION.items())],
        note="A concept not listed for a state BLOCKS (MX_ISN_SPECIAL_PAY_RULE_MISSING; D-06)")
    family("termination", "Termination reasons and the finiquito", [
        item(k, o.label, _cites(o)) for k, o in sorted(c.MX_TERMINATION_REASONS.items())]
        + ([item("FINIQUITO_RULE", "Finiquito: vacation owed and withholding", _cites(c.MX_FINIQUITO_RULE))]
           if c.MX_FINIQUITO_RULE is not None else []))
    family("ptu", "PTU (profit sharing)", (
        [item("PTU_RULE", "Distribution and cap (LFT Arts. 122-127)", _cites(c.MX_PTU_RULE))]
        if c.MX_PTU_RULE is not None else [])
        + [item(k, o.label, _cites(o), exclusion=True) for k, o in sorted(c.MX_PTU_EXCLUSION_REASONS.items())])
    family("annualAdjustment", "Annual ISR adjustment (LISR Art. 97)", (
        [item("ANNUAL_ADJUSTMENT_RULE", "Annual adjustment", _cites(c.MX_ANNUAL_ADJUSTMENT_RULE))]
        if c.MX_ANNUAL_ADJUSTMENT_RULE is not None else [])
        + [item(k, o.label, _cites(o), exclusion=True)
           for k, o in sorted(c.MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS.items())])
    family("ordinaryExemptions", "Ordinary earnings: LISR Art. 93 exemptions", [
        item(k, _CONCEPT_LABELS.get(o.kind, o.kind), _cites(o))
        for k, o in sorted(c.MX_ORDINARY_EXEMPTION_RULES.items())])
    working = []
    if c.MX_CONTRIBUTION_DAYS_RULE is not None:
        working.append(item("CONTRIBUTION_DAYS", "Absences and incapacity: contribution days (LSS Art. 31)",
                            _cites(c.MX_CONTRIBUTION_DAYS_RULE)))
    if c.MX_RISK_PREMIUM_PERIOD is not None:
        p = c.MX_RISK_PREMIUM_PERIOD
        working.append(item("RISK_PREMIUM_PERIOD", f"Risk premium period starts {p.start_day:02d}/{p.start_month:02d}",
                            _cites(p)))
    if c.MX_IMSS_MOVEMENT_DEADLINE is not None:
        m = c.MX_IMSS_MOVEMENT_DEADLINE
        working.append(item("IMSS_MOVEMENT_DEADLINE", f"IMSS movements: {m.business_days} business days", _cites(m)))
    working += [item(f"JORNADA_{code}", f"Working day {code}: {hours} hours", ((src, ref),))
                for code, (hours, src, ref) in sorted(c.MX_JORNADA_DAILY_HOURS.items())]
    holidays = c.MX_OFFICIAL_HOLIDAYS.get(year)
    if holidays:
        dates, src, ref = holidays
        working.append(item(f"HOLIDAYS_{year}", f"Official holidays {year}: {', '.join(d.isoformat() for d in dates)}",
                            ((src, ref),)))
    family("workingTime", "Working time and the IMSS calendar", working,
           note=None if holidays else f"No official holidays transcribed for {year or 'the year'} (D-16)")

    decisions = [{"name": n, "decision": d, "label": lbl, "value": getattr(_r, n, None),
                  "decided": getattr(_r, n, None) is not None} for n, d, lbl in _RULE_SWITCHES]
    decisions += [{"name": n, "decision": d, "label": lbl, "value": None,
                   "decided": getattr(c, n, None) is not None} for n, d, lbl in _RULE_INTERFACES]
    return {"editable": False, "editVia": "a code release that passes verify_mexico_sources.py compare",
            "pack": _pack_view(db, pack) if pack is not None else None, "on": _iso(on), "onSource": on_source,
            "manifestAvailable": bool(manifest), "families": families, "decisions": decisions}


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

    # An organisation is "Mexican" here if it has a Mexico legal employer
    # (Phase 3 onboarding comes before any employee) or Mexico as its company
    # jurisdiction. ZP-PRIV: a platform principal never reads worker rows, so
    # employees are not consulted (a Mexican employee needs a Mexican employer).
    org_ids = {row[0] for row in db.query(PayrollMxEmployerProfile.organization_id).distinct().all()}
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
    rows = (organization_scoped(db, PayrollEmployee, org_id).filter(PayrollEmployee.country_code == MX)
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


# The SAT catalog holding the concept codes of each CFDI node type (S28). A
# separation payment is a perception (Nómina 1.2 SeparacionIndemnizacion).
_NODE_CODE_CATALOG = {"PERCEPCION": "c_TipoPercepcion", "SEPARACION": "c_TipoPercepcion",
                      "DEDUCCION": "c_TipoDeduccion", "OTRO_PAGO": "c_TipoOtroPago"}


def _catalog_has_code(db: Session, node_type: str, code: str) -> bool:
    """Phase 11a: the code must be in the catalog of the row's OWN node type —
    before, any catalog of any approved release matched (a deduction could pass
    with a perception code)."""
    from app.modules.payroll import mexico_cfdi_catalog_service

    catalog = _NODE_CODE_CATALOG.get(node_type)
    return bool(catalog) and mexico_cfdi_catalog_service.catalog_has_code(db, catalog, code)


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
    if row.organization_id is None and not (row.cfdi_concept_code
                                            and _catalog_has_code(db, row.cfdi_node_type, row.cfdi_concept_code)):
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
