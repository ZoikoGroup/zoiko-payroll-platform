"""
scripts/seed_germany_compliance_pack_2026.py
------------------------------------------
Phase 8CI — creates the real Germany 2026 top-level Compliance Pack
(DE-PAYROLL-CY2026-V1) via the existing, generic, country-agnostic
JurisdictionPack governance framework (the same one USA/UK already use —
see Phase 8CH's report, docs/GERMANY_2026_8CH_COMPLIANCE_FRAMEWORK_
COMPLETION_REPORT.md). This is a top-level GOVERNANCE/VERSION record for
"Germany's 2026 statutory configuration as a whole" — it does NOT create,
duplicate, or replace any of Germany's ~15 existing statutory registries
(health funds, contribution ceilings, PV, minijob/midijob, church tax,
PAP, overtime), which remain independently effective-dated, PUBLISHED-
gated, and audited exactly as before. See GermanyCompliancePackSection.jsx's
own docstring for the identical scope statement on the frontend side.

SAFETY (Phase 8BY pattern, reused verbatim from every other Germany write
script in this directory): refuses to run against anything but a local/
isolated database. Call `assert_local_database()` BEFORE
`initialize_database()` — a non-local target must never even get an
engine constructed against it.

PHASE 8DF CHANGE FROM THE NIKHIL-BRANCH VERSION THIS WAS PORTED FROM: the
earlier version hardcoded maker/checker actor ids as 901/902, documented
there as an "obviously-fake" placeholder convention. This version instead
REQUIRES --maker-id/--checker-id on the command line and validates both
resolve to real, active `User` rows with role=super_admin (see
scripts/_actor_authorization.py) before doing anything else. No other
logic was changed from the validated nikhil version. Also confirmed this
phase (8DF) against main's current `upsert_jurisdiction_pack` /
`set_jurisdiction_pack_approver` / `set_jurisdiction_pack_status`: main
has since grown a "policy" pack type and a US-only tax-pack activation
gate (source-artifact + effective-date + golden-test-certification),
both explicitly scoped away from Germany's `packType="tax"`,
`jurisdictionCountry="DE"` usage here (the US gate's own comment
explicitly lists DE among the pre-existing non-US Draft packs it was
written not to break) — no adaptation to this script's own logic was
required.

WHAT THIS SCRIPT DOES NOT DO:

- Does not seed 2025/2027 packs. Phase 8CI's own brief explicitly says:
  "If historical records are not present in the local database, do NOT
  invent historical statutory packs. Instead prove the uniqueness/
  effective-date/versioning mechanism using the existing framework and
  controlled test fixtures" — that proof lives in
  tests/test_germany_compliance_pack_framework.py, not here.
- Does not fabricate a compliance owner, engineering owner, or review
  date — none is specified anywhere in the supplied Germany documentation
  or this repository's own conventions, so these are left exactly as
  "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION" rather than invented.
- Does not activate PAP, does not touch any Germany registry table, does
  not run against or seed the shared/production database.

REGULATORY AUTHORITY / SOURCE REFERENCES — not invented: "Bundesministerium
der Finanzen (BMF) / ITZBund" is the exact authority already cited in this
codebase's own seed_germany_source_evidence.py for the PAP Lohnsteuer2026
artifact (BMF owns Lohnsteuer/EStG and issues PAP); the source reference
cites the actual, real, repository-resident file
docs/Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx
(the "supplied Germany statutory document" every other Germany seed
script in this directory already treats as Tier-1 authority) plus the
existing SourceArtifact evidence chain those scripts already populate.

Usage (against an isolated SQLite file ONLY — never the shared/remote DB):

    PAYROLL_DATABASE_URL=sqlite:///./phase8ci_local_isolated.sqlite3 \
        python -m scripts.seed_germany_compliance_pack_2026 --maker-id 12 --checker-id 34
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import assert_local_database, describe_target, is_local_database
from scripts._actor_authorization import resolve_and_authorize_maker_checker

SCRIPT_NAME = "seed_germany_compliance_pack_2026"

PACK_ID = "DE-PAYROLL-CY2026-V1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the Germany 2026 top-level Compliance Pack (DE-PAYROLL-CY2026-V1), "
                    "using real, distinct Super Admin actors.",
    )
    parser.add_argument("--maker-id", type=int, required=True, help="Real, active Super Admin user id (maker).")
    parser.add_argument("--checker-id", type=int, required=True, help="Real, active Super Admin user id (checker). Must differ from --maker-id.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Phase 8DF: guard against a non-UTF8 Windows console crashing on a
    # non-ASCII character in printed text (see the identical fix +
    # rationale in seed_germany_source_evidence.py).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # ── Section 17 requirement: print DB identity/environment/guard result
    # BEFORE any mutation, and refuse outright if not demonstrably local. ──
    import os

    target = describe_target()
    local = is_local_database()
    print(f"[{SCRIPT_NAME}] Configured database target: {target or '<not configured>'}")
    print(f"[{SCRIPT_NAME}] ENVIRONMENT={os.environ.get('ENVIRONMENT', '<unset>')}")
    print(f"[{SCRIPT_NAME}] is_local_database() = {local}")
    assert_local_database(SCRIPT_NAME)  # refuses (exit 2) if not local, unless the explicit override is set

    from app.database import SessionLocal, initialize_database
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    initialize_database()
    db = SessionLocal()
    try:
        # Phase 8DF: no hardcoded placeholder actor ids — both must
        # resolve to real, active, distinct Super Admin users, or this
        # refuses to run before touching the pack.
        maker, checker = resolve_and_authorize_maker_checker(db, args.maker_id, args.checker_id)
        print(f"[{SCRIPT_NAME}] maker={maker.id} ({maker.email}), checker={checker.id} ({checker.email}) "
              "— both verified active Super Admin users.")

        existing = (
            db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == PACK_ID, JurisdictionPack.version == "1.0")
            .first()
        )
        if existing:
            print(f"[{SCRIPT_NAME}] {PACK_ID} v1.0 already exists (id={existing.id}, status={existing.status}) — nothing to do.")
            return

        pack = service.upsert_jurisdiction_pack(
            db,
            JurisdictionPackUpsert(
                packId=PACK_ID,
                jurisdictionCountry="DE",
                jurisdictionState=None,
                packType="tax",
                version="1.0",
                status="Draft",
                effectiveFrom=date(2026, 1, 1),
                effectiveTo=date(2026, 12, 31),
                taxYear="2026",
                currency="EUR",
                regulatoryAuthority="Bundesministerium der Finanzen (BMF) / ITZBund",
                complianceCategory="Statutory Payroll Tax & Social Insurance",
                complianceOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
                engineeringOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
                nextReviewDate=None,
                sourceReferences=(
                    "Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx "
                    "(supplied Germany statutory document); see payroll_source_artifacts "
                    "for the per-registry SourceArtifact evidence chain (BMF PAP "
                    "Lohnsteuer2026.xml, Deutsche Rentenversicherung, SGB XI, AOK, "
                    "individual Krankenkasse Umlagesaetze pages) seeded by "
                    "seed_germany_source_evidence.py."
                ),
                changeSummary=(
                    "Initial Germany 2026 top-level compliance pack (Phase 8CI). This is a "
                    "governance/version wrapper for 'Germany's 2026 statutory configuration as "
                    "a whole' (tax year, effective period, regulatory authority, owners, source "
                    "references) — it does NOT replace or duplicate the existing, independently "
                    "effective-dated Germany statutory registries (health funds, contribution "
                    "ceilings, PV, minijob/midijob, church tax, PAP, overtime), which remain the "
                    "actual configuration the payroll engine reads from."
                ),
            ),
            actor_id=maker.id,
        )
        print(f"[{SCRIPT_NAME}] Created {pack.pack_id} v{pack.version} (id={pack.id}, status={pack.status}).")

        approved = service.set_jurisdiction_pack_approver(db, pack.id, actor_id=checker.id)
        print(f"[{SCRIPT_NAME}] Approved by actor_id={checker.id} -> status={approved.status}.")

        activated = service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=checker.id)
        print(f"[{SCRIPT_NAME}] Activated -> status={activated.status}, "
              f"effective {activated.effective_from} to {activated.effective_to}.")

        entries = service.list_tax_configuration_audit(db, jurisdiction_pack_id=activated.id)
        print(f"[{SCRIPT_NAME}] Audit trail: {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} recorded "
              f"({', '.join(sorted({e.action for e in entries}))}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
