"""
scripts/populate_us_reciprocity_pa_nj.py
--------------------------------------------
Seeds the ONE reciprocity agreement ZP-TAX-US-2026-001 gives as a fully
specified, literal example (§8.2's own worked example table): a
Pennsylvania resident working in New Jersey, form NJ-165, suppresses NJ
wage withholding in favor of PA's own.

Deliberately ONE-DIRECTIONAL only. PA-NJ reciprocity is genuinely
bilateral in the real world (the document itself says "regression-tested
in both directions where the agreement is bilateral," §8.2), but the
document does not name PA's own reciprocal-exemption certificate for the
reverse direction (an NJ resident working in PA) anywhere — inventing a
form number/certificate name for that direction would be exactly the
kind of fabrication this whole build has refused to do everywhere else.
The reverse row can be added the same way once that certificate is
sourced.

Idempotent: safe to re-run (upserts by the same natural key
resolve_reciprocity/ReciprocityRule's own unique constraint uses:
resident_jurisdiction + work_jurisdiction + effective_from).

Usage:
    python -m scripts.populate_us_reciprocity_pa_nj
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ReciprocityRule, SourceArtifact


def main():
    db = SessionLocal()
    try:
        source = (
            db.query(SourceArtifact)
            .filter(SourceArtifact.agency == "Pennsylvania DOR / New Jersey Division of Taxation",
                    SourceArtifact.title == "PA-NJ Reciprocal Personal Income Tax Agreement (ZP-TAX-US-2026-001 §8.2)")
            .first()
        )
        if source is None:
            source = SourceArtifact(
                agency="Pennsylvania DOR / New Jersey Division of Taxation",
                title="PA-NJ Reciprocal Personal Income Tax Agreement (ZP-TAX-US-2026-001 §8.2)",
                form_number="NJ-165",
            )
            db.add(source)
            db.flush()
            print(f"Created SourceArtifact id={source.id}")
        else:
            print(f"Reusing existing SourceArtifact id={source.id}")

        effective_from = date(2026, 1, 1)
        rule = (
            db.query(ReciprocityRule)
            .filter(
                ReciprocityRule.resident_jurisdiction == "US-PA",
                ReciprocityRule.work_jurisdiction == "US-NJ",
                ReciprocityRule.effective_from == effective_from,
            )
            .first()
        )
        fields = dict(
            agreement_type="RECIPROCAL_WAGE_WITHHOLDING",
            employee_certificate="NJ-165",
            certificate_required=True,
            result_when_valid="suppress work-state wage PIT; calculate resident-state withholding if employer obligated/registered",
            effective_to=None,
            source_document_id=source.id,
        )
        if rule:
            for k, v in fields.items():
                setattr(rule, k, v)
            print(f"Updated existing ReciprocityRule id={rule.id}")
        else:
            rule = ReciprocityRule(
                resident_jurisdiction="US-PA", work_jurisdiction="US-NJ",
                effective_from=effective_from, **fields,
            )
            db.add(rule)
            print("Created new ReciprocityRule US-PA -> US-NJ")
        db.commit()
        db.refresh(rule)
        print(f"Final row: id={rule.id} {rule.resident_jurisdiction} -> {rule.work_jurisdiction} "
              f"cert={rule.employee_certificate} effective_from={rule.effective_from}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
