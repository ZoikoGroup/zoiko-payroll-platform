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


# ══════════════════════════════════════════════════════════════════════════
# Block A1 — statutory setup records, declarations, identifier vault
# (mirrors poland_service: whitelisted fields, effective dating, versioning,
# four-eyes approval via the shared require_four_eyes, audited)
# ══════════════════════════════════════════════════════════════════════════
import re as _re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

STATUS_DRAFT, STATUS_ACTIVE, STATUS_SUPERSEDED = "DRAFT", "ACTIVE", "SUPERSEDED"


def _models():
    from app.modules.payroll import models as m

    return m


def _as_date(value, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


def _as_datetime(value, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date-time.")


def _decimal(value, field: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal number.")


def _reason(reason) -> str:
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A reason is required for every Belgium statutory change (spec §12 audit).")
    return text[:300]


def _audit(db: Session, actor_id, action: str, entity_type: str, entity_id: int, old=None, new=None,
           reason: Optional[str] = None) -> None:
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     old_value=old, new_value=new, reason=reason, legal_reference=SPEC, auto_commit=False)


def _employee(db: Session, organization_id: int, employee_id):
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    employee = (organization_scoped(db, PayrollEmployee, organization_id)
                .filter(PayrollEmployee.id == employee_id).first())
    if employee is None or (getattr(employee, "country_code", None) or "").upper() != BE:
        raise NotFoundException("Belgian employee")
    return employee


def _legal_entity(db: Session, organization_id: int, legal_entity_id) -> None:
    if legal_entity_id is None:
        return
    from app.modules.organizations.models import LegalEntity

    found = (db.query(LegalEntity.id)
             .filter(LegalEntity.id == legal_entity_id, LegalEntity.organization_id == organization_id).first())
    if found is None:
        raise NotFoundException("Legal entity in this organisation")


def _facts(row) -> Optional[dict]:
    """Plain-value dict of a model row (the engine reads dicts). Vault rows are
    never passed here: callers use identifier_view, which carries no digit."""
    if row is None:
        return None
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _in_force(query, model, on: date):
    return query.filter(model.effective_from <= on, (model.effective_to.is_(None)) | (model.effective_to >= on))


def _enum(data: dict, key: str, allowed) -> None:
    value = data.get(key)
    if value is None:
        return
    value = str(value).strip().upper()
    if value not in allowed:
        raise BadRequestException(f"{key} must be one of: {', '.join(allowed)}.")
    data[key] = value


# ── field whitelists (anything else is refused; the server owns status) ────
BE_REGISTRATION_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "legal_name", "enterprise_number", "employer_category_code",
    "withholding_declaration_frequency", "holiday_fund_ref", "legal_language", "mandate_refs",
    "filing_credential_ref", "source_document_id", "evidence_ref")
BE_UNIT_FIELDS = ("registration_id", "unit_number", "name", "address", "region", "effective_from", "effective_to",
                  "legal_entity_id", "evidence_ref")
BE_PROFILE_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "worker_category", "onss_worker_code",
                     "tax_status", "residency", "special_status", "niss_vault_id", "evidence_ref")
BE_SCHEDULE_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "regime", "weekly_hours", "days_pattern",
                      "reference_period", "supersedes_id", "evidence_ref")
BE_CLASSIFICATION_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "employment_line",
                            "establishment_unit_id", "joint_committee", "sub_committee", "collective_agreement_id",
                            "function_class", "seniority_months", "work_schedule_id", "evidence_ref")
BE_DECLARATION_FIELDS = ("declaration_type", "value", "received_at", "effective_from", "effective_to",
                         "source_channel", "legal_entity_id", "evidence_ref")
DECLARATION_CHANNELS = ("PAPER", "ELECTRONIC", "EMPLOYEE_PORTAL", "IMPORT")

_DATE_FIELDS = {"effective_from", "effective_to"}
_DECIMAL_FIELDS = {"weekly_hours"}
_INT_FIELDS = {"legal_entity_id", "source_document_id", "registration_id", "niss_vault_id", "establishment_unit_id",
               "collective_agreement_id", "seniority_months", "work_schedule_id", "supersedes_id"}
_JSON_FIELDS = {"mandate_refs", "address", "days_pattern", "value"}
_COMMITTEE = _re.compile(r"^\d+(?:\.\d+)?$")
_CODE = _re.compile(r"^[A-Z0-9]{1,10}$")


def _clean(payload: dict, fields, *, required=()) -> dict:
    if not isinstance(payload, dict):
        raise BadRequestException("The request body must be an object.")
    unknown = sorted(set(payload) - set(fields))
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    data = {}
    for key, value in payload.items():
        if value is None or value == "":
            data[key] = None
        elif key in _DATE_FIELDS:
            data[key] = _as_date(value, key)
        elif key == "received_at":
            data[key] = _as_datetime(value, key)
        elif key in _DECIMAL_FIELDS:
            data[key] = _decimal(value, key)
        elif key in _INT_FIELDS:
            try:
                data[key] = int(value)
            except (TypeError, ValueError):
                raise BadRequestException(f"{key} must be a whole number.")
        elif key in _JSON_FIELDS:
            if not isinstance(value, (dict, list)):
                raise BadRequestException(f"{key} must be a JSON object or list.")
            data[key] = value
        else:
            data[key] = str(value).strip()
    missing = [key for key in required if data.get(key) in (None, "")]
    if missing:
        raise BadRequestException(f"required field(s): {', '.join(missing)}")
    if data.get("effective_to") and data.get("effective_from") and data["effective_to"] < data["effective_from"]:
        raise BadRequestException("effective_to cannot be before effective_from.")
    return data


# ── versioned records with a second person's approval ──────────────────────
def _create_version(db: Session, model, organization_id: int, data: dict, actor_id, label: str, reason: str,
                    scope: dict):
    """A DRAFT version; previous_version_id points at the latest row of the
    same scope (or the explicitly superseded row)."""
    explicit = data.pop("supersedes_id", None)
    if explicit is not None:
        prior = db.query(model).filter(model.id == explicit, model.organization_id == organization_id,
                                       *[getattr(model, k) == v for k, v in scope.items()]).first()
        if prior is None:
            raise BadRequestException("supersedes_id does not belong to this scope.")
    else:
        query = db.query(model).filter(model.organization_id == organization_id,
                                       *[(getattr(model, k).is_(None) if v is None else getattr(model, k) == v)
                                         for k, v in scope.items()])
        prior = query.order_by(model.effective_from.desc(), model.id.desc()).first()
    row = model(organization_id=organization_id, status=STATUS_DRAFT, created_by_id=actor_id,
                previous_version_id=getattr(prior, "id", None), **data)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "created", label, row.id, new={"effective_from": data["effective_from"].isoformat()},
           reason=reason)
    return row


def _approve_version(db: Session, model, organization_id: int, row_id: int, actor_id, label: str, scope_keys):
    """Four-eyes approval (approver != creator, shared require_four_eyes). An
    earlier ACTIVE version of the same scope that is still open is superseded
    from this version's start; a later ACTIVE version refuses."""
    from app.modules.payroll.service import require_four_eyes

    row = db.query(model).filter(model.id == row_id, model.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException(f"Belgium {label.replace('be_', '').replace('_', ' ')}")
    if row.status != STATUS_DRAFT:
        raise BadRequestException(f"Only a DRAFT {label.replace('_', ' ')} can be approved.")
    require_four_eyes(row.created_by_id, actor_id, f"Approving a Belgium {label.replace('_', ' ')}",
                      db=db, entity_type=label, entity_id=row.id, current_status=row.status)
    start = row.effective_from
    if scope_keys is None:
        others = ([db.get(model, row.previous_version_id)] if row.previous_version_id else [])
        others = [o for o in others if o is not None and o.status == STATUS_ACTIVE]
    else:
        others = db.query(model).filter(model.organization_id == organization_id, model.status == STATUS_ACTIVE,
                                        model.id != row.id,
                                        *[(getattr(model, k).is_(None) if getattr(row, k) is None
                                           else getattr(model, k) == getattr(row, k)) for k in scope_keys]).all()
    for old in others:
        if old.effective_from >= start:
            raise BadRequestException("An ACTIVE version on or after this effective date already exists.")
        if old.effective_to is None or old.effective_to >= start:
            old.effective_to = date.fromordinal(start.toordinal() - 1)
            old.status = STATUS_SUPERSEDED
    db.flush()
    row.status = STATUS_ACTIVE
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "approved", label, row.id, old={"status": STATUS_DRAFT},
           new={"status": STATUS_ACTIVE, "effective_from": start.isoformat()})
    return row


def _one_active(db: Session, model, organization_id: int, on: date, label: str, **scope):
    query = _in_force(db.query(model).filter(model.organization_id == organization_id,
                                             model.status == STATUS_ACTIVE), model, on)
    for key, value in scope.items():
        query = query.filter(getattr(model, key).is_(None) if value is None else getattr(model, key) == value)
    rows = query.all()
    if len(rows) > 1:
        raise BadRequestException(f"Two ACTIVE Belgium {label} versions overlap on {on.isoformat()}.")
    return rows[0] if rows else None


# ── employer registrations (BE-001, BE-038) ─────────────────────────────────
def _enterprise_number(value) -> str:
    digits = _re.sub(r"[\s.]", "", str(value or ""))
    if not _re.fullmatch(r"\d{9,12}", digits):
        raise BadRequestException("enterprise_number must be the KBO/BCE number (digits; format check only, G-16).")
    return digits


def record_be_employer_registration(db: Session, organization_id: int, payload: dict, actor_id, reason=None):
    reason = _reason(reason)
    data = _clean(payload, BE_REGISTRATION_FIELDS, required=("effective_from", "legal_name", "enterprise_number"))
    _legal_entity(db, organization_id, data.get("legal_entity_id"))
    data["enterprise_number"] = _enterprise_number(data["enterprise_number"])
    _enum(data, "legal_language", ("NL", "FR", "DE"))
    if data.get("employer_category_code") is not None:
        data["employer_category_code"] = data["employer_category_code"].upper()
        if not _CODE.fullmatch(data["employer_category_code"]):
            raise BadRequestException("employer_category_code must be an ONSS category code (letters / digits).")
    if data.get("mandate_refs") is not None and not isinstance(data["mandate_refs"], list):
        raise BadRequestException("mandate_refs must be a list of mandate REFERENCES (never secrets).")
    return _create_version(db, _models().PayrollBeEmployerRegistration, organization_id, data, actor_id,
                           "be_employer_registration", reason, {"legal_entity_id": data.get("legal_entity_id")})


def approve_be_employer_registration(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollBeEmployerRegistration, organization_id, row_id, actor_id,
                            "be_employer_registration", ("legal_entity_id",))


def verify_be_employer_registration(db: Session, organization_id: int, row_id: int, actor_id, outcome, reason):
    from app.modules.payroll.service import require_four_eyes

    reason = _reason(reason)
    R = _models().PayrollBeEmployerRegistration
    row = db.query(R).filter(R.id == row_id, R.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgium employer registration")
    outcome = str(outcome or "").strip().upper()
    if outcome not in ("VERIFIED", "REJECTED"):
        raise BadRequestException("outcome must be VERIFIED or REJECTED.")
    if row.status != STATUS_ACTIVE:
        raise BadRequestException("Only an ACTIVE employer registration is verified.")
    require_four_eyes(row.created_by_id, actor_id, "Verifying a Belgium employer registration", db=db,
                      entity_type="be_employer_registration", entity_id=row.id, current_status=row.status)
    old = row.verification_state
    row.verification_state = outcome
    db.flush()
    _audit(db, actor_id, "verified", "be_employer_registration", row.id, old={"verification_state": old},
           new={"verification_state": outcome}, reason=reason)
    return row


# ── establishment units (BE-001, BE-038) ────────────────────────────────────
def record_be_establishment_unit(db: Session, organization_id: int, payload: dict, actor_id, reason=None):
    reason = _reason(reason)
    data = _clean(payload, BE_UNIT_FIELDS, required=("registration_id", "unit_number", "name", "effective_from"))
    R = _models().PayrollBeEmployerRegistration
    registration = db.query(R).filter(R.id == data["registration_id"], R.organization_id == organization_id).first()
    if registration is None:
        raise NotFoundException("Belgium employer registration")
    data["legal_entity_id"] = registration.legal_entity_id
    data["unit_number"] = _re.sub(r"[\s.]", "", data["unit_number"])
    if not _re.fullmatch(r"\d{1,20}", data["unit_number"]):
        raise BadRequestException("unit_number must be the establishment unit number (digits; format check only).")
    return _create_version(db, _models().PayrollBeEstablishmentUnit, organization_id, data, actor_id,
                           "be_establishment_unit", reason,
                           {"registration_id": data["registration_id"], "unit_number": data["unit_number"]})


def approve_be_establishment_unit(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollBeEstablishmentUnit, organization_id, row_id, actor_id,
                            "be_establishment_unit", ("registration_id", "unit_number"))


# ── worker profiles (BE-002) ────────────────────────────────────────────────
def record_be_worker_profile(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                             reason=None):
    content = _content()
    reason = _reason(reason)
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, BE_PROFILE_FIELDS, required=("effective_from", "worker_category"))
    _enum(data, "worker_category", content.WORKER_CATEGORIES)
    _enum(data, "residency", ("RESIDENT", "NON_RESIDENT"))
    if data.get("onss_worker_code") is not None:
        data["onss_worker_code"] = data["onss_worker_code"].upper()
        if not _re.fullmatch(r"[A-Z0-9]{1,4}", data["onss_worker_code"]):
            raise BadRequestException("onss_worker_code must be an ONSS worker code (letters / digits).")
    if data.get("niss_vault_id") is not None:
        _vault_for_employee(db, organization_id, employee.id, data["niss_vault_id"], ("NISS", "BIS"))
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    data["employee_id"] = employee.id
    return _create_version(db, _models().PayrollBeWorkerProfile, organization_id, data, actor_id,
                           "be_worker_profile", reason, {"employee_id": employee.id})


def approve_be_worker_profile(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollBeWorkerProfile, organization_id, row_id, actor_id,
                            "be_worker_profile", ("employee_id",))


# ── work schedules (BE-022) ─────────────────────────────────────────────────
def record_be_work_schedule(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                            reason=None):
    """An explicit schedule object. Schedules are versioned in their own lineage
    (supersedes_id): an employee with several employment lines can hold several
    ACTIVE schedules, so approving one never supersedes another line's."""
    content = _content()
    reason = _reason(reason)
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, BE_SCHEDULE_FIELDS, required=("effective_from", "regime", "weekly_hours"))
    _enum(data, "regime", content.SCHEDULE_REGIMES)
    if data["weekly_hours"] <= 0:
        raise BadRequestException("weekly_hours must be above zero.")
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    data["employee_id"] = employee.id
    if data.get("supersedes_id") is None:
        data["supersedes_id"] = None
        row = _create_version_lineage(db, organization_id, data, actor_id, reason)
        return row
    return _create_version(db, _models().PayrollBeWorkSchedule, organization_id, data, actor_id,
                           "be_work_schedule", reason, {"employee_id": employee.id})


def _create_version_lineage(db: Session, organization_id: int, data: dict, actor_id, reason: str):
    data.pop("supersedes_id", None)
    S = _models().PayrollBeWorkSchedule
    row = S(organization_id=organization_id, status=STATUS_DRAFT, created_by_id=actor_id, **data)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "created", "be_work_schedule", row.id,
           new={"effective_from": data["effective_from"].isoformat()}, reason=reason)
    return row


def approve_be_work_schedule(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollBeWorkSchedule, organization_id, row_id, actor_id,
                            "be_work_schedule", None)


# ── employment classifications (BE-003, BE-020) ─────────────────────────────
def record_be_employment_classification(db: Session, organization_id: int, employee_id: int, payload: dict,
                                        actor_id, reason=None):
    m = _models()
    reason = _reason(reason)
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, BE_CLASSIFICATION_FIELDS, required=("effective_from", "employment_line"))
    for key in ("joint_committee", "sub_committee"):
        if data.get(key) is not None:
            data[key] = data[key].upper()
            pattern = _COMMITTEE if key == "joint_committee" else _CODE
            if not pattern.fullmatch(data[key]):
                raise BadRequestException(f"{key} has an invalid format.")
    if data.get("sub_committee") and not data.get("joint_committee"):
        raise BadRequestException("A sub-committee needs its Joint Committee.")
    if data.get("seniority_months") is not None and data["seniority_months"] < 0:
        raise BadRequestException("seniority_months cannot be negative.")
    if data.get("establishment_unit_id") is not None:
        U = m.PayrollBeEstablishmentUnit
        if db.query(U.id).filter(U.id == data["establishment_unit_id"], U.organization_id == organization_id).first() is None:
            raise NotFoundException("Belgium establishment unit")
    if data.get("work_schedule_id") is not None:
        S = m.PayrollBeWorkSchedule
        if db.query(S.id).filter(S.id == data["work_schedule_id"], S.organization_id == organization_id,
                                 S.employee_id == employee.id).first() is None:
            raise NotFoundException("Work schedule of this employee")
    if data.get("collective_agreement_id") is not None:
        A = m.CollectiveAgreement
        agreement = db.query(A).filter(A.id == data["collective_agreement_id"]).first()
        if agreement is None or (agreement.jurisdiction_country or "").upper() != BE \
                or agreement.organization_id not in (None, organization_id):
            raise NotFoundException("Belgian Joint Committee agreement")
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    data["employee_id"] = employee.id
    return _create_version(db, m.PayrollBeEmploymentClassification, organization_id, data, actor_id,
                           "be_employment_classification", reason,
                           {"employee_id": employee.id, "employment_line": data["employment_line"]})


def approve_be_employment_classification(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollBeEmploymentClassification, organization_id, row_id, actor_id,
                            "be_employment_classification", ("employee_id", "employment_line"))


# ── declarations (spec §5 stages 1 and 5, BE-012) ───────────────────────────
def record_be_declaration(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id):
    content = _content()
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, BE_DECLARATION_FIELDS,
                  required=("declaration_type", "received_at", "effective_from", "source_channel", "evidence_ref"))
    _enum(data, "declaration_type", content.DECLARATION_TYPES)
    _enum(data, "source_channel", DECLARATION_CHANNELS)
    if data.get("value") is not None and not isinstance(data["value"], dict):
        raise BadRequestException("value must be a JSON object.")
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    D = _models().PayrollBeDeclaration
    row = D(organization_id=organization_id, employee_id=employee.id, status="RECEIVED", created_by_id=actor_id,
            **data)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "received", "be_declaration", row.id,
           new={"type": row.declaration_type, "effective_from": row.effective_from.isoformat()},
           reason=f"{row.declaration_type} received {row.received_at.isoformat()}")
    return row


def _declaration(db: Session, organization_id: int, row_id: int):
    D = _models().PayrollBeDeclaration
    row = db.query(D).filter(D.id == row_id, D.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgium declaration")
    return row


def approve_be_declaration(db: Session, organization_id: int, row_id: int, actor_id):
    """Four-eyes approval; an earlier APPROVED declaration of the same type that
    is still open is superseded from this one's start (never edited away)."""
    from app.modules.payroll.service import require_four_eyes

    D = _models().PayrollBeDeclaration
    row = _declaration(db, organization_id, row_id)
    if row.status != "RECEIVED":
        raise BadRequestException("Only a RECEIVED declaration can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a Belgium declaration", db=db,
                      entity_type="be_declaration", entity_id=row.id, current_status=row.status)
    start = row.effective_from
    for old in (db.query(D).filter(D.organization_id == organization_id, D.employee_id == row.employee_id,
                                   D.declaration_type == row.declaration_type, D.status == "APPROVED",
                                   D.id != row.id).all()):
        if old.effective_from >= start:
            raise BadRequestException("An APPROVED declaration of this type already starts on or after this one.")
        if old.effective_to is None or old.effective_to >= start:
            old.effective_to = date.fromordinal(start.toordinal() - 1)
            old.status = "SUPERSEDED"
            old.superseded_by_id = row.id
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "approved", "be_declaration", row.id, old={"status": "RECEIVED"},
           new={"status": "APPROVED", "type": row.declaration_type})
    return row


def withdraw_be_declaration(db: Session, organization_id: int, row_id: int, actor_id, reason, effective_to):
    reason = _reason(reason)
    row = _declaration(db, organization_id, row_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED declaration can be withdrawn.")
    end = _as_date(effective_to, "effectiveTo")
    if end < row.effective_from:
        raise BadRequestException("The withdrawal date cannot be before the declaration started.")
    row.effective_to = end
    row.status = "WITHDRAWN"
    row.withdrawn_at = datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "withdrawn", "be_declaration", row.id, old={"status": "APPROVED"},
           new={"status": "WITHDRAWN", "effective_to": end.isoformat()}, reason=reason)
    return row


# ── identifier vault (spec §15, BE-040): masked; reveal requested + approved ─
def _vault(db: Session, organization_id: int, vault_id: int):
    V = _models().PayrollBeIdentifierVault
    row = db.query(V).filter(V.id == vault_id, V.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian identifier")
    return row


def _vault_for_employee(db: Session, organization_id: int, employee_id: int, vault_id: int, kinds):
    row = _vault(db, organization_id, vault_id)
    if row.employee_id != employee_id or row.identifier_type not in kinds or row.status != "ACTIVE":
        raise BadRequestException("The identifier reference does not belong to this employee.")
    return row


def _vault_owner(row) -> str:
    from app.modules.payroll import be_identifiers as bid

    subject = row.employee_id if row.subject_type == bid.SUBJECT_EMPLOYEE else row.legal_entity_id
    return bid.vault_owner(row.organization_id, row.subject_type, subject, row.identifier_type, row.id)


def _vault_event(db: Session, row, action: str, actor_id, reason=None, purpose=None, previous_id=None):
    Event = _models().PayrollBeIdentifierAccessEvent
    event = Event(organization_id=row.organization_id, legal_entity_id=row.legal_entity_id,
                  employee_id=row.employee_id, vault_id=row.id, actor_id=actor_id, created_by_id=actor_id,
                  action=action, purpose=purpose, reason=(reason or None) and reason[:300],
                  previous_version_id=previous_id)
    db.add(event)
    db.flush()
    return event


def identifier_view(row) -> dict:
    """The only identifier representation any API returns (no digit)."""
    from app.modules.payroll import be_identifiers as bid

    active = row.status == "ACTIVE"
    return {"id": row.id, "subjectType": row.subject_type, "identifierType": row.identifier_type,
            "employeeId": row.employee_id, "legalEntityId": row.legal_entity_id, "onFile": active,
            "masked": bid.masked(row.identifier_type) if active else None, "status": row.status,
            "keyVersion": row.key_version}


def create_be_identifier(db: Session, organization_id: int, identifier_type: str, raw, actor_id, *,
                         employee_id=None, legal_entity_id=None):
    from app.modules.payroll import be_identifiers as bid

    V = _models().PayrollBeIdentifierVault
    identifier_type = str(identifier_type or "").strip().upper()
    if identifier_type in (bid.NISS, bid.BIS):
        subject_type = bid.SUBJECT_EMPLOYEE
        employee = _employee(db, organization_id, employee_id)
        legal_entity_id = getattr(employee, "legal_entity_id", None)
    elif identifier_type == bid.ONSS:
        subject_type, employee_id = bid.SUBJECT_EMPLOYER, None
        _legal_entity(db, organization_id, legal_entity_id)
    else:
        raise BadRequestException("identifierType must be NISS, BIS or ONSS.")
    try:
        plain = bid.normalise(identifier_type, raw)
        fingerprint = bid.fingerprint(identifier_type, plain)
    except bid.BeIdentifierError as error:
        raise BadRequestException(str(error))
    if db.query(V.id).filter(V.organization_id == organization_id, V.identifier_type == identifier_type,
                             V.fingerprint == fingerprint, V.status == "ACTIVE").first():
        raise BadRequestException(f"This {identifier_type} is already on file in this organisation.")
    if subject_type == bid.SUBJECT_EMPLOYEE and db.query(V.id).filter(
            V.organization_id == organization_id, V.employee_id == employee_id,
            V.identifier_type == identifier_type, V.status == "ACTIVE").first():
        raise BadRequestException(f"The employee already has a {identifier_type} on file; delete it first.")
    row = V(organization_id=organization_id, legal_entity_id=legal_entity_id, employee_id=employee_id,
            subject_type=subject_type, identifier_type=identifier_type, ciphertext="pending", key_version=0,
            fingerprint=fingerprint, collected_at=datetime.utcnow(), status="ACTIVE", created_by_id=actor_id)
    db.add(row)
    db.flush()
    try:
        row.ciphertext, row.key_version = bid.encrypt(plain, _vault_owner(row))
    except bid.BeIdentifierError as error:
        raise BadRequestException(str(error))
    plain = None
    db.flush()
    _vault_event(db, row, "CREATE", actor_id, purpose=bid.PURPOSE)
    return row


def list_be_identifiers(db: Session, organization_id: int, employee_id=None) -> list:
    V = _models().PayrollBeIdentifierVault
    q = db.query(V).filter(V.organization_id == organization_id)
    if employee_id is not None:
        _employee(db, organization_id, employee_id)
        q = q.filter(V.employee_id == employee_id)
    return [identifier_view(r) for r in q.order_by(V.id)]


def _last_event(db: Session, row, action: str, after_id: int = 0):
    Event = _models().PayrollBeIdentifierAccessEvent
    return (db.query(Event).filter(Event.vault_id == row.id, Event.action == action, Event.id > after_id)
            .order_by(Event.id.desc()).first())


def request_be_identifier_reveal(db: Session, organization_id: int, vault_id: int, reason, actor_id):
    row = _vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The identifier has been deleted.")
    return _vault_event(db, row, "REVEAL_REQUESTED", actor_id, reason=_reason(reason), purpose="REVEAL")


def approve_be_identifier_reveal(db: Session, organization_id: int, vault_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _vault(db, organization_id, vault_id)
    request = _last_event(db, row, "REVEAL_REQUESTED")
    if request is None:
        raise BadRequestException("There is no reveal request to approve.")
    if _last_event(db, row, "REVEAL_APPROVED", request.id) is not None:
        raise BadRequestException("This reveal request has already been approved.")
    require_four_eyes(request.actor_id, actor_id, "Approving a Belgian identifier reveal", db=db,
                      entity_type="be_identifier_access_event", entity_id=request.id,
                      current_status="REVEAL_REQUESTED")
    return _vault_event(db, row, "REVEAL_APPROVED", actor_id, reason=request.reason, purpose="REVEAL",
                        previous_id=request.id)


def reveal_be_identifier(db: Session, organization_id: int, vault_id: int, actor_id) -> dict:
    """The ONE response that carries the value: requester only, approved by a
    second person, single use."""
    from app.modules.payroll import be_identifiers as bid

    row = _vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The identifier has been deleted.")
    request = _last_event(db, row, "REVEAL_REQUESTED")
    approval = _last_event(db, row, "REVEAL_APPROVED", request.id) if request is not None else None
    if request is None or approval is None:
        raise BadRequestException("A reveal needs a request and a second person's approval.")
    if _last_event(db, row, "REVEALED", approval.id) is not None:
        raise BadRequestException("This approval has already been used; request a new reveal.")
    if request.actor_id != actor_id:
        raise BadRequestException("Only the person who requested the reveal can see the identifier.")
    try:
        value = bid.decrypt(row.ciphertext, row.key_version, _vault_owner(row))
    except bid.BeIdentifierError as error:
        raise BadRequestException(str(error))
    _vault_event(db, row, "REVEALED", actor_id, reason=request.reason, purpose="REVEAL", previous_id=approval.id)
    return {"vaultId": row.id, "identifierType": row.identifier_type, "value": value}


def delete_be_identifier(db: Session, organization_id: int, vault_id: int, actor_id, reason):
    reason = _reason(reason)
    row = _vault(db, organization_id, vault_id)
    if row.status == "DELETED":
        raise BadRequestException("The identifier has already been deleted.")
    row.status = "DELETED"
    row.deleted_at = datetime.utcnow()
    row.ciphertext = None
    db.flush()
    _vault_event(db, row, "DELETED", actor_id, reason=reason)
    return row


def set_be_employer_onss(db: Session, organization_id: int, registration_id: int, raw, actor_id):
    """Put the employer's ONSS number on file (vault) for a DRAFT registration."""
    R = _models().PayrollBeEmployerRegistration
    registration = db.query(R).filter(R.id == registration_id, R.organization_id == organization_id).first()
    if registration is None:
        raise NotFoundException("Belgium employer registration")
    if registration.status != STATUS_DRAFT:
        raise BadRequestException("The ONSS number is set on a DRAFT registration (create a new version).")
    row = create_be_identifier(db, organization_id, "ONSS", raw, actor_id,
                               legal_entity_id=registration.legal_entity_id)
    registration.onss_number_vault_id = row.id
    db.flush()
    _audit(db, actor_id, "updated", "be_employer_registration", registration.id,
           new={"onss_number_vault_id": row.id}, reason="ONSS number put on file (vault)")
    return row


# ── employee summary (identifiers masked) ───────────────────────────────────
def employee_summary(db: Session, organization_id: int, employee_id: int) -> dict:
    m = _models()
    _employee(db, organization_id, employee_id)

    def versions(model):
        return [_json_safe(_facts(r)) for r in db.query(model).filter(
            model.organization_id == organization_id, model.employee_id == employee_id).order_by(model.id)]

    return {"employeeId": employee_id, "identifiers": list_be_identifiers(db, organization_id, employee_id),
            "workerProfiles": versions(m.PayrollBeWorkerProfile),
            "workSchedules": versions(m.PayrollBeWorkSchedule),
            "classifications": versions(m.PayrollBeEmploymentClassification),
            "declarations": versions(m.PayrollBeDeclaration)}


# ── Block A2: applicability resolver (spec §2; read-only, no side effects) ──
def _latest_for(db: Session, model, organization_id: int, on: date, **scope):
    """The version in force on `on` (ACTIVE, or SUPERSEDED inside its own
    window for a past date); otherwise the latest version of any status, so the
    resolver can say "not ACTIVE" instead of "missing"."""
    query = db.query(model).filter(model.organization_id == organization_id)
    for key, value in scope.items():
        query = query.filter(getattr(model, key).is_(None) if value is None else getattr(model, key) == value)
    in_force = (_in_force(query, model, on).filter(model.status.in_((STATUS_ACTIVE, STATUS_SUPERSEDED)))
                .order_by(model.effective_from.desc(), model.id.desc()).all())
    if len(in_force) > 1:
        raise BadRequestException(f"Two Belgium {model.__tablename__} versions overlap on {on.isoformat()}.")
    if in_force:
        return in_force[0]
    return query.order_by(model.effective_from.desc(), model.id.desc()).first()


def _be_registration_for(db: Session, organization_id: int, legal_entity_id, on: date):
    R = _models().PayrollBeEmployerRegistration
    row = None
    if legal_entity_id is not None:
        row = _latest_for(db, R, organization_id, on, legal_entity_id=legal_entity_id)
    return row or _latest_for(db, R, organization_id, on, legal_entity_id=None)


def _be_pack_for(db: Session, organization_id: int, on: date):
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        rates, slabs, pack = resolve_tax_configuration(db, BE, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack" (the resolver blocks on it)
        return None
    if pack is None:
        return None
    rate_map: dict = {}
    for r in rates:
        rate_map.setdefault(r.component_key, []).append(r)
    return BePack(rate_map, slabs, organization_id, on)


def resolve_be_classification(db: Session, organization_id: int, employee_id: int, pay_date, *,
                              period_start=None, pay_basis=None) -> dict:
    """POST /classification/resolve: the decision, its evidence and every
    blocking reason for one employee on one pay date. Reads only; writes
    nothing and never calculates (spec §13)."""
    from app.modules.payroll.engine.jurisdictions.belgium import applicability

    m = _models()
    on = _as_date(pay_date, "payDate")
    start = _as_date(period_start, "periodStart") if period_start not in (None, "") else None
    if start is not None and start > on:
        raise BadRequestException("periodStart cannot be after payDate.")
    employee = _employee(db, organization_id, employee_id)

    def rows(model):
        return db.query(model).filter(model.organization_id == organization_id,
                                      model.employee_id == employee.id).order_by(model.id).all()

    classifications = rows(m.PayrollBeEmploymentClassification)
    unit_ids = {c.establishment_unit_id for c in classifications if c.establishment_unit_id is not None}
    agreement_ids = {c.collective_agreement_id for c in classifications if c.collective_agreement_id is not None}
    U, A = m.PayrollBeEstablishmentUnit, m.CollectiveAgreement
    units = {u.id: _facts(u) for u in (db.query(U).filter(U.organization_id == organization_id,
                                                         U.id.in_(unit_ids)).all() if unit_ids else [])}
    agreements = {a.id: _facts(a) for a in (db.query(A).filter(A.id.in_(agreement_ids)).all()
                                            if agreement_ids else [])
                  if a.organization_id in (None, organization_id)}
    registration = _be_registration_for(db, organization_id, getattr(employee, "legal_entity_id", None), on)
    profile = _latest_for(db, m.PayrollBeWorkerProfile, organization_id, on, employee_id=employee.id)
    result = applicability.resolve(
        _be_pack_for(db, organization_id, on), on, registration=_facts(registration), profile=_facts(profile),
        classifications=[_facts(c) for c in classifications],
        schedules=[_facts(s) for s in rows(m.PayrollBeWorkSchedule)], units=units, agreements=agreements,
        declarations=[_facts(d) for d in rows(m.PayrollBeDeclaration)],
        contract_type=getattr(employee, "employment_type", None), pay_frequency=getattr(employee, "pay_frequency", None),
        pay_basis=pay_basis, period_start=start)
    return _json_safe({"employeeId": employee.id, **result})
