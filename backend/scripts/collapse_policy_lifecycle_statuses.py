"""
scripts/collapse_policy_lifecycle_statuses.py
-----------------------------------------------
Collapses the POLICY-pack lifecycle to Draft | Active only.

Background: policy packs previously shared the full 7-status lifecycle with
tax packs (Draft | In Review | QA | Approved | Active | Deprecated |
Retired). Policy packs now have no review/approval stage — only "Draft"
(unpublished) and "Active" (live). This script rewrites any existing policy
pack sitting in a legacy status:

    In Review / QA / Approved / Deprecated / Retired  ->  Draft
    Draft / Active                                    ->  unchanged

Tax packs (pack_type = "tax") are NEVER touched — they keep the full
lifecycle.

Idempotent and safe to re-run. Prints a summary of the migration plus the
post-migration status distribution so it can be verified (only Draft/Active
should remain for policy packs).

Usage:
    python -m scripts.collapse_policy_lifecycle_statuses
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter

from app.database import SessionLocal
from app.modules.payroll.models import JurisdictionPack

LEGACY_TO_DRAFT = ("In Review", "QA", "Approved", "Deprecated", "Retired")


def main():
    db = SessionLocal()
    try:
        legacy_rows = (
            db.query(JurisdictionPack)
            .filter(
                JurisdictionPack.pack_type == "policy",
                JurisdictionPack.status.in_(LEGACY_TO_DRAFT),
            )
            .all()
        )
        if legacy_rows:
            print(f"Collapsing {len(legacy_rows)} legacy policy-pack row(s) to Draft:")
            for row in legacy_rows:
                print(f"  #{row.id} {row.pack_id} v{row.version}: {row.status} -> Draft")
                row.status = "Draft"
            db.commit()
        else:
            print("No legacy policy-pack statuses found — nothing to collapse.")

        remaining = Counter(
            r.status
            for r in db.query(JurisdictionPack).filter(JurisdictionPack.pack_type == "policy").all()
        )
        print(f"\nPost-migration policy-pack status distribution: {dict(remaining)}")

        tax_policy_touched = (
            db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_type != "policy", JurisdictionPack.status.in_(LEGACY_TO_DRAFT))
            .count()
        )
        print(f"Tax packs left untouched (would only be touched if explicitly rewritten): {tax_policy_touched}")

        unexpected = {s for s in remaining if s not in ("Draft", "Active")}
        if unexpected:
            print(f"\nWARNING: policy packs still have unexpected status(es): {sorted(unexpected)}")
        else:
            print("\nOK: every policy pack is now Draft or Active.")
    finally:
        db.close()


if __name__ == "__main__":
    main()