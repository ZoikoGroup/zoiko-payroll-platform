"""
payroll/belgium_service.py
--------------------------
Belgium (ZP-BE-ENG-001) jurisdiction statutory module — Phase 1 fail-closed
scaffold, registered in jurisdiction_hooks._MODULES with all 13 hooks.

Nothing Belgian can be calculated, approved, paid, activated or opened yet.
Each hook follows how the platform calls it (Phase 1 hook caller table):

* Hooks called only for something whose country is BE (type a) fail closed:
  they raise a clear Belgium-blocked error or return a refusal.
* retention_settings is ALSO called for every registered country on every
  report download (retention_service._report_country, type b), so it never
  raises there: it returns an inert settings object that matches only Belgian
  reports, has no record categories and keeps every decision OPEN, so nothing
  is purged. Deleting a Belgian employee is refused while the Belgian retention
  decisions are OPEN (gap G-21) — enforced inside retained_record_label, which
  only the deletion check (retention_service.assert_employee_deletable) calls.
* pack_holidays returns [] (no guessed dates), statutory_summary reports
  NOT_BUILT, payslip_hold_view returns None (read-only display).

No statutory value lives here. No NISS/INSZ is read, logged or returned.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

BE = "BE"
SPEC = "ZP-BE-ENG-001 v1.0"

NOT_BUILT_MESSAGE = ("Belgian payroll is not built yet (ZP-BE-ENG-001); it stays disabled until the Belgium "
                     "release gates G1-G7 are signed.")
RELEASE_GATES_UNMET = "Belgium release gates G1–G7 not met"
DELETION_REFUSED_MESSAGE = ("Belgium: employee records cannot be deleted until Belgian statutory retention rules "
                            "are approved (spec §15).")
RETENTION_PERIOD_DECISION = "BE-G21-RETENTION"


def _conflict(detail: str):
    from fastapi import HTTPException, status as http_status

    return HTTPException(http_status.HTTP_409_CONFLICT, detail=detail)


def _run_has_belgian_items(db: Session, run) -> bool:
    from app.modules.payroll.models import PayslipItem

    return db.query(PayslipItem.id).filter(PayslipItem.payroll_run_id == run.id,
                                           PayslipItem.country_code == BE).first() is not None


# ── 1. calc_inputs (type a; no BE caller before Phase 5) ────────────────────
def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of=None, period=None, **_kwargs) -> dict:
    from app.modules.payroll.engine.jurisdictions.belgium import errors as E

    raise E.BECalculationBlockedError(E.ENGINE_NOT_BUILT, NOT_BUILT_MESSAGE,
                                      organization_id=getattr(employee, "organization_id", None))


# ── 2. before_run_transition (loop, but only for runs with BE payslips) ─────
def before_run_transition(db: Session, run, next_status, actor_id) -> None:
    if not _run_has_belgian_items(db, run):
        return
    raise _conflict(f"Belgium: the run cannot move to {getattr(next_status, 'value', next_status)} — "
                    + NOT_BUILT_MESSAGE)


# ── 3./4. shared statutory profile (type a) ─────────────────────────────────
def _be_statutory_profile_errors(data) -> list:
    # Belgian statutory facts (worker category, Joint Committee, tax status,
    # NISS/INSZ in the vault) live in the effective-dated payroll_be_* records
    # (Phase 4), never on the shared statutory profile.
    return ["Belgian statutory facts are not held on the shared statutory profile; the Belgian worker profile "
            "arrives with ZP-BE-ENG-001 Phase 4."]


def _be_profile_values(db: Session, employee, data, previous) -> dict:
    # Unreachable after _be_statutory_profile_errors refuses; a backstop.
    raise BadRequestException("Belgium: the shared statutory profile is refused for Belgian employees.")


# ── 5. pack_activation_refusal (type a) ─────────────────────────────────────
def _content():
    from app.modules.payroll.engine.countries import belgium_content as content

    return content


def _row_empty(row, kind: str) -> bool:
    """True when a canonical BE row holds no value for its kind (seeded state).
    A row signed NOT_SUPPORTED (any kind) is a decided row, not an empty one."""
    content = _content()
    if (row.text_value or "").strip().upper() == content.NOT_SUPPORTED:
        return False
    if kind == content.KIND_RATE:
        return row.employee_rate_pct is None and row.employer_rate_pct is None
    if kind == content.KIND_AMOUNT:
        return row.flat_amount is None
    return not (row.text_value or "").strip() or (row.text_value or "") == "PENDING_G1"


def be_pack_activation_refusal(db: Session, pack, actor_id=None) -> Optional[str]:
    """Why a Belgian pack must NOT be activated, or None (ZP-BE-ENG-001 §17 G1).

    Refused while ANY required catalogue row is missing, empty, unsourced or
    unsigned ("[PENDING G1]"). A row signed NOT_SUPPORTED is a decided, signed
    row (the feature stays blocked at calculation time), as in Poland. A band /
    formula / table key signed SLAB_ROWS needs at least one signed slab row of
    its rule type; every earning-classification row must be signed. Four-eyes
    approval is enforced separately by the shared approval lists."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if (getattr(pack, "jurisdiction_country", None) or "").upper() != BE:
        return None
    if actor_id is not None:
        # Four-eyes, completing the shared rules (editors never approve; the
        # approver never activates; the LAST editor never activates): nobody who
        # edited or signed a row of this version may activate it.
        from app.modules.payroll import be_super_admin

        if actor_id in be_super_admin.statutory_editors(db, pack):
            return (f"Belgium pack {pack.pack_id}: a Super Admin who edited or signed a row of this version cannot "
                    "also activate it (four-eyes).")
    content = _content()
    rates = {r.component_key: r for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))}
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    if not rates:
        return "Belgium pack has no statutory content — seed it from belgium_content.py first."
    problems = []
    for key, (_group, kind, _ref, _label) in content.KEYS.items():
        row = rates.get(key)
        if row is None:
            problems.append(f"{key} (missing)")
        elif content.PENDING_MARK in (row.label or ""):
            problems.append(f"{key} (unsigned)")
        elif _row_empty(row, kind):
            problems.append(f"{key} (empty)")
        elif row.source_document_id is None:
            problems.append(f"{key} (unsourced)")
        elif kind in content.SLAB_KINDS and (row.text_value or "").upper() == content.SLAB_ROWS:
            rule = content.RULE_TYPES[key]
            mine = [s for s in slabs if s.rule_type == rule]
            if not mine or any(content.PENDING_MARK in (s.rate_label or "") for s in mine):
                problems.append(f"{key} (slab rows missing or unsigned)")
    classes = [s for s in slabs if s.rule_type == content.EARNING_CLASS_RULE]
    if not classes or any(content.PENDING_MARK in (s.rate_label or "") for s in classes):
        problems.append(f"{content.EARNING_CLASS_RULE} (missing or unsigned)")
    if problems:
        shown = ", ".join(problems[:8]) + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else "")
        return (f"Belgium pack {pack.pack_id} cannot be activated: {len(problems)} required row(s) are missing, "
                f"empty, unsourced or unsigned: {shown}. Gate G1 must sign them (ZP-BE-ENG-001 §17).")
    return None


def _be_pack_activation_refusal(db: Session, pack, actor_id=None) -> Optional[str]:
    return be_pack_activation_refusal(db, pack, actor_id)


# ── 6. retention_settings (type b + a) ──────────────────────────────────────
BE_RETENTION_CATEGORIES: tuple = ()      # none declared until G-21 is decided


def _decision_state(db: Session, key: str) -> str:
    return "OPEN"                         # G-21: no approved Belgian retention rule exists


def _retention_employee(db: Session, employee_id: int, organization_id: int) -> None:
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    employee = (organization_scoped(db, PayrollEmployee, organization_id)
                .filter(PayrollEmployee.id == employee_id).first())
    if employee is None or (getattr(employee, "country_code", None) or "").upper() != BE:
        raise NotFoundException("Belgian employee")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    """Called only by retention_service.assert_employee_deletable. While the
    Belgian retention decision is OPEN (G-21), deletion is refused outright."""
    if _decision_state(db, RETENTION_PERIOD_DECISION) != "RECORDED":
        raise _conflict(DELETION_REFUSED_MESSAGE)
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return False


def _is_report(report) -> bool:
    if report is None:
        return False
    country = (getattr(report, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(report, "report_type", "") or "").upper()
    return country == BE or report_type.startswith("BE_")


def _be_retention_settings():
    # The platform calls this hook with NO arguments (retention_service.settings),
    # including once per registered country on every report download: never raise.
    from app.modules.payroll.retention_service import RetentionJurisdiction

    return RetentionJurisdiction(
        country=BE, label="Belgium", categories=BE_RETENTION_CATEGORIES,
        period_decision=RETENTION_PERIOD_DECISION, end_decision=RETENTION_PERIOD_DECISION,
        decision_reference="BE-RETENTION-G21", decision_state=_decision_state,
        validate_employee=_retention_employee, retained_record_label=_retained_record_label,
        has_statutory_profile=_has_statutory_profile, report_matches=_is_report, audit_spec=SPEC)


# ── 7. service_registry_transition (type a) ─────────────────────────────────
def be_unmet_requirements(db: Session) -> list:
    """Phase 1: the release gates are never met (readiness arrives in Phase 10)."""
    return [{"key": "BE_RELEASE_GATES_G1_G7", "label": RELEASE_GATES_UNMET,
             "detail": "ZP-BE-ENG-001 §17; the Belgian engine is not built"}]


def _be_service_registry_transition(db: Session, target: str, reason: str, actor_id=None, as_of=None):
    from app.modules.payroll import service

    def readiness():
        return be_unmet_requirements(db), {}

    return service.transition_service_registry(
        db, BE, target, reason, actor_id, label="Belgium", readiness=readiness,
        invalid_target_message=lambda t: (f"Belgium availability can only be {service.SERVICE_REGISTRY_OPEN} "
                                          f"or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Belgium registry row - seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Belgium is {a}; only PLANNED moves to AVAILABLE.")


def ensure_be_service_registry_row(db: Session) -> str:
    """Belgium's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == BE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=BE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


# ── 8. statutory_summary (type a; read-only status) ─────────────────────────
RELEASE_GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")


def statutory_summary(db: Session) -> dict:
    """Pack + signing status; the engine is NOT_BUILT and every release gate is
    NOT MET (gates are computed in Phase 10)."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    content = _content()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == BE)
             .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).all())
    out = []
    for p in packs:
        rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == p.id,
                                                   ContributionRate.organization_id.is_(None)).all())
        out.append({"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,
                    "effectiveFrom": p.effective_from.isoformat() if p.effective_from else None,
                    "effectiveTo": p.effective_to.isoformat() if p.effective_to else None,
                    "rows": len(rates),
                    "pendingRows": sum(1 for r in rates if content.PENDING_MARK in (r.label or "")),
                    "activationRefusal": be_pack_activation_refusal(db, p)})
    return {"country": BE, "jurisdiction": BE, "spec": SPEC, "status": "NOT_BUILT", "available": False,
            "packs": out, "gates": {g: "NOT MET" for g in RELEASE_GATES}}


def _evidence(db: Session, tag: str):
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag,
                                            SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    accepted = next((r for r in rows if r.reviewer_id and r.file_path and r.reviewer_id != r.created_by_id), None)
    return accepted, bool(rows)


def owner_decisions(db: Session) -> list:
    """Owner / specialist decisions (gaps register): OPEN until reviewed
    evidence tagged BE-DECISION-<key> exists (uploader != reviewer)."""
    out = []
    for key, label, blocks in _content().OWNER_DECISIONS:
        tag = f"BE-DECISION-{key}"
        accepted, submitted = _evidence(db, tag)
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": tag,
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


# ── 9. statutory_editors (type a) ───────────────────────────────────────────
def _be_statutory_editors(db: Session, pack) -> set:
    """Super Admins who edited or signed a BE row of this pack version: the
    shared pack approval refuses every one of them (four-eyes)."""
    from app.modules.payroll import be_super_admin

    return be_super_admin.statutory_editors(db, pack)


# ── Draft pack seed (scripts/seed_belgium_canonical_packs.py, Super Admin) ──
def seed_belgium_pack(db: Session):
    """Write the belgium_content catalogue into the Draft BE-PAYROLL-2026 pack.

      * one SourceArtifact per evidence-register entry (S1-S24) with its title
        and URL and NO checksum (not archived), reused when present;
      * one canonical ContributionRate row per catalogue key with EVERY value
        field empty and the label "<label> (spec-proposed: ...) [PENDING G1]"
        — a spec figure is display text only, never a value;
      * one BE_EARNING_CLASS row per (obligation, component), REVIEW, pending.

    Idempotent and create-only: an existing Draft pack only gains the rows it
    lacks (a row edited in the console is never overwritten); a pack that has
    left Draft is refused. Creates no Joint Committee pack."""
    from decimal import Decimal

    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    content = _content()
    pack_id, window_from, window_to = content.BE_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise BadRequestException(f"{pack_id} is {pack.status}, not Draft — it is never re-seeded.")

    sources = {}
    for code, agency, title, url in content.SOURCE_REFERENCES:
        form = f"ZP-BE-ENG-001 {code}"
        artifact = db.query(SourceArtifact).filter(SourceArtifact.form_number == form).first()
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=f"{code} {title} [UNVERIFIED: not archived]"[:300],
                                      form_number=form, source_url=url)
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=BE, pack_type="tax",
                                status="Draft", effective_from=window_from, effective_to=window_to,
                                currency=content.CURRENCY, tax_year=content.TAX_YEAR,
                                compliance_category="Belgium statutory payroll (ZP-BE-ENG-001)")
        db.add(pack)
        db.flush()

    existing = {r.component_key for r in db.query(ContributionRate.component_key).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))}
    for order, (key, (_group, _kind, ref, _label)) in enumerate(content.KEYS.items()):
        if key in existing:
            continue
        cited = [s.strip() for s in ref.replace(",", " ").split() if s.strip() in sources]
        db.add(ContributionRate(
            organization_id=None, jurisdiction_country=BE, jurisdiction_pack_id=pack.id, component_key=key,
            label=f"{content.key_label(key)} {content.PENDING_MARK}"[:100], employee_share="—", employer_share="—",
            total="PENDING G1", employee_rate_pct=None, employer_rate_pct=None, flat_amount=None, text_value=None,
            source_document_id=sources[cited[0]] if cited else None, sort_order=order))

    have_classes = {(s.tax_regime, s.filing_status) for s in db.query(TaxSlab).filter(
        TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None),
        TaxSlab.rule_type == content.EARNING_CLASS_RULE)}
    order = 0
    for obligation in content.OBLIGATIONS:
        for component in content.COMPONENTS:
            order += 1
            if (obligation, component) in have_classes:
                continue
            # min_amount / rate_pct are NOT NULL structural placeholders on the
            # shared table; the classification itself is assessment_basis.
            db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=BE,
                           rule_type=content.EARNING_CLASS_RULE, min_amount=Decimal("0"), max_amount=None,
                           rate_pct=Decimal("0"), tax_regime=obligation, filing_status=component,
                           assessment_basis="REVIEW", tax_formula="",
                           rate_label=f"{obligation}: {component} — REVIEW {content.PENDING_MARK}"[:150],
                           sort_order=order))
    db.flush()
    return pack


# ── shared-flow guards (BE-guarded branches call these) ─────────────────────
def be_agreement_refusal(agreement_code) -> Optional[str]:
    """Why a Belgian collective agreement (Joint Committee pack, D3) is refused
    by the shared upsert, or None. agreement_code is the single source of truth:
    BE-PC-<committee>[-<sub>]-<version>."""
    try:
        _content().parse_be_agreement_code(agreement_code)
    except ValueError as exc:
        return f"Belgium: {exc}."
    return None


def be_pack_assignment_refusal(pack) -> Optional[str]:
    """A Belgian pack can be assigned to organisations only once Active."""
    if (getattr(pack, "jurisdiction_country", None) or "").upper() == BE and pack.status != "Active":
        return (f"Belgium pack {pack.pack_id} v{pack.version} is {pack.status}; only an Active Belgian pack can be "
                "assigned to organisations.")
    return None


# ── 10. template_activation_refusal (type a) ────────────────────────────────
def _be_template_activation_refusal(db: Session, template, actor_id=None) -> Optional[str]:
    return ("Belgium form templates (Dimona, DmfA, 281.10, payslip) stay inactive until the authority schemas are "
            "archived and the filing path is certified (gate G3).")


# ── 11. pack_holidays (type a) ──────────────────────────────────────────────
def _be_pack_holidays(db: Session, year: int) -> list:
    # Belgian public holidays and substitute days arrive as signed content
    # (Phase 6, D15); nothing is seeded from a guessed list.
    return []


# ── 12. payment_treatment (loop, but only for runs with BE items) ───────────
def _be_payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    if not any((getattr(i, "country_code", None) or "").upper() == BE for i in items):
        return {}
    raise _conflict("Belgium: no payment file can include Belgian payslips — " + NOT_BUILT_MESSAGE)


# ── 13. payslip_hold_view (type a; read-only display) ───────────────────────
def _be_payslip_hold_view(item) -> Optional[dict]:
    return None


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_be_statutory_profile_errors",
    "statutory_profile_values": "_be_profile_values",
    "pack_activation_refusal": "_be_pack_activation_refusal",
    "retention_settings": "_be_retention_settings",
    "service_registry_transition": "_be_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_be_statutory_editors",
    "template_activation_refusal": "_be_template_activation_refusal",
    "pack_holidays": "_be_pack_holidays",
    "payment_treatment": "_be_payment_treatment",
    "payslip_hold_view": "_be_payslip_hold_view",
}
