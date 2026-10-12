"""
scripts/populate_us_reciprocity_oh.py
--------------------------------------------
Gap-closure Level 2, Batch 7 "Group B", 2026-09-13. Seeds Ohio's own
fully-specified reciprocity agreements (ZP-TAX-US-2026-001 primary-source
batch): Ohio does not withhold state tax for residents of Indiana,
Michigan, Kentucky, Pennsylvania, or West Virginia who work in Ohio
(Form IT 4NR) — five directional rows, all sharing the same certificate
and result, following the exact pattern
scripts/populate_us_reciprocity_pa_nj.py already established.

Idempotent: safe to re-run (upserts by resident_jurisdiction +
work_jurisdiction + effective_from, same natural key
resolve_reciprocity/ReciprocityRule's own unique constraint uses).

Usage:
    python -m scripts.populate_us_reciprocity_oh
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ReciprocityRule, SourceArtifact

RESIDENT_STATES = ["IN", "MI", "KY", "PA", "WV"]


def main():
    db = SessionLocal()
    try:
        source = (
            db.query(SourceArtifact)
            .filter(SourceArtifact.agency == "Ohio Department of Taxation",
                    SourceArtifact.title == "Ohio Reciprocity Agreements (ZP-TAX-US-2026-001, Batch 7) — Form IT 4NR")
            .first()
        )
        if source is None:
            source = SourceArtifact(
                agency="Ohio Department of Taxation",
                title="Ohio Reciprocity Agreements (ZP-TAX-US-2026-001, Batch 7) — Form IT 4NR",
                form_number="IT 4NR",
            )
            db.add(source)
            db.flush()
            print(f"Created SourceArtifact id={source.id}")
        else:
            print(f"Reusing existing SourceArtifact id={source.id}")

        effective_from = date(2026, 1, 1)
        for resident_state in RESIDENT_STATES:
            rule = (
                db.query(ReciprocityRule)
                .filter(
                    ReciprocityRule.resident_jurisdiction == f"US-{resident_state}",
                    ReciprocityRule.work_jurisdiction == "US-OH",
                    ReciprocityRule.effective_from == effective_from,
                )
                .first()
            )
            fields = dict(
                agreement_type="RECIPROCAL_WAGE_WITHHOLDING",
                employee_certificate="IT 4NR",
                certificate_required=True,
                result_when_valid="suppress work-state wage PIT; calculate resident-state withholding if employer obligated/registered",
                effective_to=None,
                source_document_id=source.id,
            )
            if rule:
                for k, v in fields.items():
                    setattr(rule, k, v)
                print(f"Updated existing ReciprocityRule id={rule.id} US-{resident_state} -> US-OH")
            else:
                rule = ReciprocityRule(
                    resident_jurisdiction=f"US-{resident_state}", work_jurisdiction="US-OH",
                    effective_from=effective_from, **fields,
                )
                db.add(rule)
                db.flush()
                print(f"Created new ReciprocityRule US-{resident_state} -> US-OH")
        db.commit()
        print(f"Done: {len(RESIDENT_STATES)} Ohio reciprocity row(s) seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
