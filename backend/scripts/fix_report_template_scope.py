"""Scope fix for released per-employee report templates. DRY RUN by default.

    cd backend
    python -m scripts.fix_report_template_scope --actor-email <super-admin>             # dry run (no writes)
    python -m scripts.fix_report_template_scope --actor-email <super-admin> --apply     # create the Draft versions

A template whose key or report type ends in PREVIEW / STATEMENT / YTD is a
per-employee document. This finds the Published ones whose STORED
document_scope is not PER_EMPLOYEE (the database row, not what a screen shows;
until 2026-11-18 the Super Admin detail always displayed "Aggregate document").

A Published row is never modified. For each affected template, --apply makes a
new DRAFT version through the existing service (service.upsert_report_template,
which audits it and copies the components and fields), with document_scope
PER_EMPLOYEE and change summary "Scope fix: per-employee". The admin given by
--actor-email is recorded as its creator and content editor, so a DIFFERENT
Super Admin must approve it (four-eyes). Publishing, superseding the old version
and activating stay manual.

Skipped and reported: a template that already has a later version, a key whose
next version number is taken, and Active / non-Published rows (listed for
information only).
"""
import argparse
import re
import sys

from sqlalchemy import text

from app.database import SessionLocal
from app.modules.auth.models import User, UserRole
from app.modules.payroll import service
from app.modules.payroll.models import ReportTemplate
from app.modules.payroll.schemas import ReportTemplateUpsert

PER_EMPLOYEE_NAME = re.compile(r"[-_](PREVIEW|STATEMENT|YTD)$")
CHANGE_SUMMARY = "Scope fix: per-employee"


def _is_per_employee_document(t) -> bool:
    return bool(PER_EMPLOYEE_NAME.search(t.template_key or "") or PER_EMPLOYEE_NAME.search(t.report_type or ""))


def _next_version(version: str) -> str:
    """'1.0' -> '1.1', '2' -> '2.1', '1.9' -> '1.10'."""
    m = re.fullmatch(r"(\d+)\.(\d+)", version or "")
    return f"{m.group(1)}.{int(m.group(2)) + 1}" if m else f"{version}.1"


def plan(db) -> dict:
    """{"create": [(template, new_version)], "skip": [(template, reason)], "info": [(template, note)]} — reads only."""
    out = {"create": [], "skip": [], "info": []}
    wrong = [t for t in db.query(ReportTemplate).order_by(ReportTemplate.jurisdiction_country,
                                                         ReportTemplate.template_key, ReportTemplate.id)
             if _is_per_employee_document(t) and t.document_scope != "PER_EMPLOYEE"]
    for t in wrong:
        if t.status != "Published":
            out["info"].append((t, f"{t.status}: not handled by this script (only Published rows are)"))
            continue
        latest = (db.query(ReportTemplate).filter(ReportTemplate.template_key == t.template_key)
                  .order_by(ReportTemplate.created_at.desc(), ReportTemplate.id.desc()).first())
        if latest.id != t.id:
            out["skip"].append((t, f"a later version already exists (v{latest.version}, {latest.status})"))
            continue
        new_version = _next_version(t.version)
        if db.query(ReportTemplate).filter(ReportTemplate.template_key == t.template_key,
                                           ReportTemplate.version == new_version).first():
            out["skip"].append((t, f"v{new_version} already exists"))
            continue
        out["create"].append((t, new_version))
    return out


def create_scope_fix_version(db, t, new_version: str, actor_id: int):
    """The new Draft version, through the governed service upsert."""
    return service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=t.template_key, name=t.name, reportType=t.report_type, jurisdictionCountry=t.jurisdiction_country,
        jurisdictionState=t.jurisdiction_state, jurisdictionLocality=t.jurisdiction_locality,
        reportingYear=t.reporting_year, version=new_version, description=t.description,
        regulatoryAuthority=t.regulatory_authority, effectiveFrom=t.effective_from, effectiveTo=t.effective_to,
        changeSummary=CHANGE_SUMMARY, sourceReferences=t.source_references, documentScope="PER_EMPLOYEE",
        sourceDocumentId=t.source_document_id,
        reconciliationTolerance=float(t.reconciliation_tolerance) if t.reconciliation_tolerance is not None else None,
        reason=f"{CHANGE_SUMMARY} (v{t.version} is {t.status} with document_scope {t.document_scope})",
    ), actor_id=actor_id)


def main(argv=None, session_factory=SessionLocal) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--actor-email", required=True, help="the Super Admin running this (creator + content editor)")
    parser.add_argument("--apply", action="store_true", help="create the Draft versions (default: dry run)")
    args = parser.parse_args(argv)
    db = session_factory()
    try:
        if not args.apply and db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        actor = db.query(User).filter(User.email == args.actor_email.strip().lower()).first() or \
            db.query(User).filter(User.email == args.actor_email.strip()).first()
        if actor is None or actor.role != UserRole.SUPER_ADMIN or not actor.is_active:
            print(f"Refused: {args.actor_email!r} is not an active Super Admin.")
            return 2
        p = plan(db)
        mode = "APPLY" if args.apply else "DRY RUN — nothing is changed"
        print(f"{mode}. Actor: user #{actor.id}. Published per-employee templates stored with the wrong scope: "
              f"{len(p['create']) + len(p['skip'])}.")
        for t, new_version in p["create"]:
            print(f"- {t.jurisdiction_country} {t.template_key} v{t.version} [{t.report_type}] "
                  f"scope {t.document_scope} -> new Draft v{new_version} PER_EMPLOYEE")
        for t, reason in p["skip"]:
            print(f"- SKIP {t.jurisdiction_country} {t.template_key} v{t.version}: {reason}")
        for t, note in p["info"]:
            print(f"- INFO {t.jurisdiction_country} {t.template_key} v{t.version}: {note}")
        if not args.apply:
            print("\nNothing written. Re-run with --apply to create the Draft versions.")
            return 0
        for t, new_version in p["create"]:
            row = create_scope_fix_version(db, t, new_version, actor.id)
            print(f"  created #{row.id} {row.template_key} v{row.version} ({row.status}, {row.document_scope}); "
                  f"a Super Admin other than user #{actor.id} must approve it")
        print(f"\nCreated {len(p['create'])} Draft version(s). Next, per template: a different Super Admin approves, "
              "publish, supersede the old version, activate (four-eyes).")
        return 0
    finally:
        if not args.apply:
            db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
