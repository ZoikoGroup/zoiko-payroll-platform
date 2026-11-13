"""Belgium DEMO pack (ZP-BE-ENG-001 Block E4) — non-production only.

BE-DEMO-2026, labelled "DEMO — NOT FOR PAYROLL", is built from the AI-drafted
content workbook (docs/belgium/content/BE_2026_AI_DRAFT.xlsx); every row the
draft could not source (NOT FOUND) takes a clearly fake DEMO placeholder from
docs/belgium/content/BE_DEMO_PLACEHOLDERS.json. No value lives in this code.

Guards (fail closed):
  * the demo pack exists and is used only when BE_DEMO_PACKS_ENABLED is true
    AND the environment is not production (ENVIRONMENT / APP_ENV "production",
    "prod" or "live"; with neither set, DEBUG false counts as production);
  * it is signed and activated only by be_seed_demo_pack (seed script / test
    fixture) — the governed activation refuses it, and so does any assignment
    to an organisation that is not a demo organisation (BE_DEMO_ORG_IDS);
  * a non-demo organisation never calculates with it (calc inputs refuse; the
    preflight sees no pack);
  * DEMO payslips and filings carry the DEMO watermark and are never paid
    (no submission / no pain.001 file) and never transmitted or submitted.

The real BE-PAYROLL-2026 pack is never read for signing, never signed and never
activated here.
"""
from __future__ import annotations

import io
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

BE = "BE"
DEMO_PREFIX = "BE-DEMO-"
DEMO_PACK_ID = "BE-DEMO-2026"
DEMO_LABEL = "DEMO — NOT FOR PAYROLL"
_DOCS = Path(__file__).resolve().parents[4] / "docs" / "belgium" / "content"
DRAFT_WORKBOOK = _DOCS / "BE_2026_AI_DRAFT.xlsx"
PLACEHOLDERS = _DOCS / "BE_DEMO_PLACEHOLDERS.json"
_PRODUCTION_NAMES = ("production", "prod", "live")


# ── guards ──────────────────────────────────────────────────────────────────
def be_demo_is_production() -> bool:
    from app.config import settings

    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    if env:
        return env in _PRODUCTION_NAMES
    return not bool(settings.DEBUG)


def be_demo_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "BE_DEMO_PACKS_ENABLED", False)) and not be_demo_is_production()


def be_demo_org_ids() -> frozenset:
    from app.config import settings

    raw = str(getattr(settings, "BE_DEMO_ORG_IDS", "") or "")
    return frozenset(int(p) for p in raw.replace(";", ",").split(",") if p.strip().isdigit())


def be_is_demo_org(organization_id) -> bool:
    return be_demo_enabled() and organization_id is not None and int(organization_id) in be_demo_org_ids()


def be_is_demo_pack(pack) -> bool:
    return str(getattr(pack, "pack_id", "") or "").upper().startswith(DEMO_PREFIX)


def be_is_demo_version(version) -> bool:
    return str(version or "").upper().startswith(DEMO_PREFIX)


def be_demo_pack_refusal(organization_id, pack) -> Optional[str]:
    """Why `pack` may not be used for `organization_id`, or None."""
    if not be_is_demo_pack(pack):
        return None
    if not be_demo_enabled():
        return (f"Belgium: {pack.pack_id} is a {DEMO_LABEL} pack and demo packs are disabled here "
                "(BE_DEMO_PACKS_ENABLED off or a production environment).")
    if not be_is_demo_org(organization_id):
        return (f"Belgium: {pack.pack_id} is a {DEMO_LABEL} pack; only a demo organisation (BE_DEMO_ORG_IDS) may "
                "use it.")
    return None


def be_snapshot_is_demo(snapshot) -> bool:
    s = snapshot or {}
    return bool(s.get("demo")) or be_is_demo_version((s.get("trace") or {}).get("packVersion"))


# ── pack seeding (seed script / test fixture only) ──────────────────────────
def _draft_rows(data: bytes) -> dict:
    """{sheet: [row dict]} of the drafted workbook (text cells)."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if rows:
            header = [str(h) if h is not None else "" for h in rows[0]]
            out[ws.title] = [dict(zip(header, r)) for r in rows[1:]]
    return out


def _val(value) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def be_seed_demo_pack(db: Session, actor_id=None, workbook: Optional[bytes] = None,
                      placeholders: Optional[dict] = None):
    """Create BE-DEMO-2026 (Active, every row signed, every label DEMO) from the
    drafted values + DEMO placeholders. Refused unless demo packs are enabled in
    a non-production environment. Idempotent: an existing demo pack is returned."""
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if not be_demo_enabled():
        raise BadRequestException("Belgium DEMO packs are disabled here (BE_DEMO_PACKS_ENABLED off or a production "
                                  "environment).")
    existing = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == DEMO_PACK_ID).first()
    if existing is not None:
        return existing
    sheets = _draft_rows(workbook if workbook is not None else DRAFT_WORKBOOK.read_bytes())
    ph = placeholders if placeholders is not None else json.loads(PLACEHOLDERS.read_text(encoding="utf-8"))
    _pid, window_from, window_to = content.BE_2026
    source = SourceArtifact(agency="Zoiko", title=f"{DEMO_LABEL}: AI draft + DEMO placeholders [UNVERIFIED]",
                            form_number="ZP-BE-DEMO-2026")
    db.add(source)
    db.flush()
    pack = JurisdictionPack(pack_id=DEMO_PACK_ID, version="1.0", jurisdiction_country=BE, pack_type="tax",
                            status="Active", effective_from=window_from, effective_to=window_to,
                            currency=content.CURRENCY, tax_year=content.TAX_YEAR,
                            compliance_category=f"{DEMO_LABEL} (ZP-BE-ENG-001 Block E4)")
    db.add(pack)
    db.flush()

    drafted = {}
    for row in sheets.get("Scalar keys", []) + sheets.get("Parallel tolerances", []):
        key = row.get("key")
        if key and str(row.get("confidence") or "") not in ("", "NOT FOUND"):
            drafted[key] = row
    columns = {"textValue": "text_value", "employeeRatePct": "employee_rate_pct",
               "employerRatePct": "employer_rate_pct", "flatAmount": "flat_amount"}
    for order, key in enumerate(content.KEYS):
        values, origin = {}, "drafted"
        if key in drafted:
            values = {col: _val(drafted[key].get(name)) for name, col in columns.items()}
            start = _val(drafted[key].get("effectiveFrom"))
        else:
            values = dict(ph["rates"].get(key) or {"text_value": content.NOT_SUPPORTED})
            origin, start = "placeholder", None
        rate = ContributionRate(
            organization_id=None, jurisdiction_country=BE, jurisdiction_pack_id=pack.id, component_key=key,
            label=(f"{DEMO_LABEL} " + (ph["label"] if origin == "placeholder" else "AI draft (unsigned elsewhere)")
                   + f" {key}")[:100],
            employee_share="—", employer_share="—", total="DEMO",
            employee_rate_pct=Decimal(values["employee_rate_pct"]) if values.get("employee_rate_pct") else None,
            employer_rate_pct=Decimal(values["employer_rate_pct"]) if values.get("employer_rate_pct") else None,
            flat_amount=Decimal(values["flat_amount"]) if values.get("flat_amount") else None,
            text_value=values.get("text_value"),
            effective_from=date.fromisoformat(start[:10]) if start else None,
            source_document_id=source.id, sort_order=order)
        db.add(rate)

    def slab(rule_type, label, **f):
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=BE,
                       rule_type=rule_type, min_amount=Decimal(f.get("min_amount") or "0"),
                       max_amount=Decimal(f["max_amount"]) if f.get("max_amount") else None,
                       rate_pct=Decimal(f.get("rate_pct") or "0"),
                       flat_amount=Decimal(f["flat_amount"]) if f.get("flat_amount") else None,
                       formula_expression=f.get("formula_expression"), tax_formula=(f.get("tax_formula") or "")[:150],
                       filing_status=f.get("filing_status"), tax_regime=f.get("tax_regime"),
                       assessment_basis=f.get("assessment_basis"), effective_from=f.get("effective_from"),
                       effective_to=f.get("effective_to"), rate_label=f"{DEMO_LABEL} {label}"[:150],
                       source_document_id=source.id, sort_order=0))

    for row in sheets.get("Earning classification", []):
        slab(content.EARNING_CLASS_RULE, "AI draft class", tax_regime=row.get("obligation"),
             filing_status=row.get("component"), assessment_basis=_val(row.get("treatment")) or "REVIEW")
    drafted_rules = set()
    for row in sheets.get("Slab keys", []):
        key = row.get("key")
        if not key or str(row.get("confidence") or "") in ("", "NOT FOUND") or key not in content.RULE_TYPES:
            continue
        rule = content.RULE_TYPES[key]
        drafted_rules.add(rule)
        day = _val(row.get("date"))
        slab(rule, f"AI draft {key}", min_amount=_val(row.get("minAmount")), flat_amount=_val(row.get("flatAmount")),
             rate_pct=_val(row.get("ratePct")), tax_formula=_val(row.get("name")), filing_status=_val(row.get("dimension")),
             effective_from=date.fromisoformat(day) if day else None, effective_to=date.fromisoformat(day) if day else None)
    for row in sheets.get("Band proposals (post code list)", []):
        key = row.get("key")
        if key in content.RULE_TYPES:
            drafted_rules.add(content.RULE_TYPES[key])
            slab(content.RULE_TYPES[key], f"AI draft band {key}", min_amount=_val(row.get("minAmount")),
                 rate_pct=_val(row.get("ratePct")), filing_status=_val(row.get("dimension")))
    for row in sheets.get("Filing schema versions", []):
        key = row.get("key")
        if key in content.RULE_TYPES and _val(row.get("version")) and str(row.get("confidence") or "") != "NOT FOUND":
            start, end = _val(row.get("effectiveFrom")), _val(row.get("effectiveTo"))
            slab(content.RULE_TYPES[key], f"AI draft {key}", tax_formula=_val(row.get("version")),
                 effective_from=date.fromisoformat(start) if start else None,
                 effective_to=date.fromisoformat(end) if end else None)
    for s in ph["slabs"]:
        if s["rule_type"] not in drafted_rules:
            slab(s["rule_type"], ph["label"], **{k: v for k, v in s.items() if k != "rule_type"})
    db.flush()
    return pack


# ── demo month (seed script / test fixture only) ────────────────────────────
DEMO_IBAN_EMPLOYER = "BE68539007547034"      # privacy-scan: allow (published example IBAN, DEMO)
DEMO_IBAN_WHITE = "BE71096123456769"         # privacy-scan: allow (published example IBAN, DEMO)
DEMO_IBAN_MANUAL = "BE62510007547061"        # privacy-scan: allow (published example IBAN, DEMO)


def be_seed_demo_month(db: Session, organization_id: int, preparer_id: int, approver_id: int,
                       pay_date: date = date(2026, 9, 30)) -> dict:
    """One demo month end to end for an EXISTING demo organisation, with two
    EXISTING users (no account is created): setup -> preview -> approve ->
    payslips -> DRAFT payment batch -> DmfA draft. Refused unless the
    organisation is a demo organisation and the two users differ."""
    from app.modules.payroll import belgium_filing as bf
    from app.modules.payroll import belgium_payment_service as pay
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem

    if not be_is_demo_org(organization_id):
        raise BadRequestException("The demo month runs only for a demo organisation (BE_DEMO_ORG_IDS) with demo "
                                  "packs enabled in a non-production environment.")
    if preparer_id is None or approver_id is None or preparer_id == approver_id:
        raise BadRequestException("The demo month needs two DIFFERENT existing users (four-eyes stays as built).")
    a, b = preparer_id, approver_id

    def two_step(record, approve, *args):
        row = record(*args)
        db.flush()
        return approve(db, organization_id, row.id, b)

    details = db.query(CompanyComplianceDetails).filter_by(organization_id=organization_id).first()
    if details is not None and not details.settlement_acc:
        details.settlement_acc = DEMO_IBAN_EMPLOYER
    reg = two_step(be.record_be_employer_registration, be.approve_be_employer_registration, db, organization_id,
                   {"effective_from": "2026-01-01", "legal_name": f"{DEMO_LABEL} employer",
                    "enterprise_number": "0999999999", "employer_category_code": "000",
                    "onss_special_160_status": "NOT_APPLICABLE", "special_160_evidence_ref": "DEMO",
                    "withholding_declaration_frequency": "MONTHLY"}, a, "DEMO setup")
    be.verify_be_employer_registration(db, organization_id, reg.id, b, "VERIFIED", "DEMO")
    for name in ("basic", "hra", "special_allowance"):
        two_step(be.record_be_component_mapping, be.approve_be_component_mapping, db, organization_id,
                 {"platform_component_source": "PLATFORM_FIELD", "platform_component_key": name,
                  "be_component": "SALARY", "effective_from": "2026-01-01"}, a, "DEMO mapping")
    employees = []
    for code, label, category, worker_code, salary, iban in (
            ("DEMO-WC", "DEMO White-collar", "EMPLOYEE", "495", Decimal("3800"), DEMO_IBAN_WHITE),
            ("DEMO-MW", "DEMO Manual worker", "MANUAL", "015", Decimal("3400"), DEMO_IBAN_MANUAL)):
        emp = PayrollEmployee(organization_id=organization_id, employee_code=code, name=label, country_code=BE,
                              employment_type="Full-time", pay_frequency="Monthly", ctc=salary, basic=salary,
                              hra=Decimal("0"), date_of_joining=date(2025, 1, 1), compliance_fields={"iban": iban})
        db.add(emp)
        db.flush()
        two_step(be.record_be_worker_profile, be.approve_be_worker_profile, db, organization_id, emp.id,
                 {"effective_from": "2026-01-01", "worker_category": category, "onss_worker_code": worker_code,
                  "residency": "RESIDENT", "pay_basis": "SALARIED"}, a, "DEMO hire")
        two_step(be.record_be_work_schedule, be.approve_be_work_schedule, db, organization_id, emp.id,
                 {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38"}, a, "DEMO hire")
        two_step(be.record_be_employment_classification, be.approve_be_employment_classification, db,
                 organization_id, emp.id, {"effective_from": "2026-01-01", "employment_line": "MAIN",
                                           "joint_committee": "200", "function_class": "B", "seniority_months": 0,
                                           "contract_type": "INDEFINITE", "contract_start_date": "2025-01-01"},
                 a, "DEMO hire")
        bf.build_be_dimona_events(db, organization_id, emp.id, a)      # DRAFT, never transmitted (DEMO)
        employees.append(emp)
    db.flush()
    preview = service.preview_payroll_run(db, organization_id, [e.id for e in employees], BE,
                                          period_start=pay_date.replace(day=1), period_end=pay_date,
                                          pay_date=pay_date)
    run = PayrollRun(organization_id=organization_id, period_label=f"{DEMO_LABEL} {pay_date:%b %Y}",
                     period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date, created_by=a)
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, organization_id)
    db.refresh(run)
    service.advance_payroll_run_status(db, run.id, a, organization_id)            # Draft -> Review
    for p in be.be_run_preflight(db, run):
        if p.get("exception") and p["severity"] == "BLOCK":
            be.acknowledge_be_run_exception(db, organization_id, run.id, {"employeeId": p["employeeId"],
                                                                           "code": p["code"],
                                                                           "reason": f"{DEMO_LABEL}"}, a)
    db.commit()
    service.advance_payroll_run_status(db, run.id, b, organization_id)            # Review -> Approved (four-eyes)
    db.refresh(run)
    items = db.query(PayslipItem).filter_by(payroll_run_id=run.id).all()
    batch = pay.create_salary_payment_batch(db, organization_id, run.id, a, requested_execution_date=date.today(),
                                            idempotency_key=f"DEMO-{run.id}")
    filing, _obligations = bf.build_be_dmfa(db, organization_id, bf.quarter_key(pay_date), None, a)
    db.commit()
    return {"runId": run.id, "status": str(getattr(run.status, "value", run.status)), "preview": preview,
            "payslips": [i.id for i in items], "demo": all(be_snapshot_is_demo(i.be_calculation_snapshot)
                                                           for i in items),
            "paymentBatchId": batch.id, "paymentBatchStatus": batch.status,
            "dmfaFilingId": filing.id, "dmfaStatus": filing.status}
