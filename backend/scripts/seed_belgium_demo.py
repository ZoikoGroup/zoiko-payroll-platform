"""
scripts/seed_belgium_demo.py
----------------------------
Belgium DEMO (ZP-BE-ENG-001 Block E4) — local / staging only.

Creates the BE-DEMO-2026 pack ("DEMO — NOT FOR PAYROLL") from the AI-drafted
workbook + DEMO placeholders, a demo organisation, two demo employees
(white-collar and manual worker) and one demo month end to end: setup ->
preview -> approve -> payslips -> DRAFT payment batch -> DmfA draft.

It never touches the real BE-PAYROLL-2026 pack and creates NO user account:
pass two EXISTING, DIFFERENT user ids (four-eyes stays exactly as built):

    BE_DEMO_PACKS_ENABLED=true python -m scripts.seed_belgium_demo --preparer 12 --approver 13

Refused when BE_DEMO_PACKS_ENABLED is not true, in a production environment, or
against a non-local database (_local_db_guard). The demo organisation is
recognised by BE_DEMO_ORG_IDS: the script sets it for its own run and prints the
value to add to the environment (and to BE_CANARY_ORG_IDS to open the Belgium
screens for it).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from scripts._local_db_guard import assert_local_database  # noqa: E402


def seed_demo(db, preparer_id: int, approver_id: int, org_name: str = "DEMO Belgium BV") -> dict:
    from app.config import settings
    from app.modules.auth.models import User
    from app.modules.organizations.models import Organization
    from app.modules.payroll import belgium_demo
    from app.modules.payroll.models import CompanyComplianceDetails

    if not belgium_demo.be_demo_enabled():
        raise SystemExit("Refused: BE_DEMO_PACKS_ENABLED is not true, or this is a production environment.")
    if preparer_id == approver_id:
        raise SystemExit("Refused: --preparer and --approver must be two DIFFERENT existing users.")
    for uid in (preparer_id, approver_id):
        if db.get(User, uid) is None:
            raise SystemExit(f"Refused: user {uid} does not exist (this script never creates accounts).")
    pack = belgium_demo.be_seed_demo_pack(db, preparer_id)
    org = db.query(Organization).filter(Organization.organization_code == "BE-DEMO").first()
    if org is None:
        # EVALUATION workspace: the payroll screens open without a paid plan, and every PDF also carries the
        # platform's "PREVIEW — EVALUATION ONLY" watermark next to the DEMO one (Block H3).
        org = Organization(organization_name=f"{org_name} ({belgium_demo.DEMO_LABEL})", organization_code="BE-DEMO",
                           workspace_type="EVALUATION")
        db.add(org)
        db.flush()
        db.add(CompanyComplianceDetails(organization_id=org.id, name=org.organization_name, jurisdiction_country="BE"))
        db.commit()
    ids = belgium_demo.be_demo_org_ids() | {org.id}
    settings.BE_DEMO_ORG_IDS = ",".join(str(i) for i in sorted(ids))      # this run only
    month = belgium_demo.be_seed_demo_month(db, org.id, preparer_id, approver_id)
    return {"pack": pack.pack_id, "organizationId": org.id, **month}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preparer", type=int, required=True, help="existing user id (prepares / records)")
    parser.add_argument("--approver", type=int, required=True, help="a DIFFERENT existing user id (approves)")
    args = parser.parse_args()
    assert_local_database("seed_belgium_demo")
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_demo(db, args.preparer, args.approver)
        db.commit()
        print(f"DEMO seeded: {out}")
        print(f"Add to the environment: BE_DEMO_ORG_IDS={out['organizationId']} "
              f"(and BE_CANARY_ORG_IDS={out['organizationId']} to open the Belgium screens).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
