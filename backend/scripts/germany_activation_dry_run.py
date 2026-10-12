"""
scripts/germany_activation_dry_run.py
--------------------------------------
Phase 8DC.5/8DC.6 — computes exactly what Germany 2026 registry activation
WOULD create, without ever writing a single registry row anywhere.

HOW THIS STAYS A TRUE DRY RUN:

- Runs against a private, disposable SQLite file created fresh for this
  process only (SQLite is always classified "local" by
  scripts/_local_db_guard.py — see that module's docstring). The file is
  deleted at the end of this script, success or failure.
- Calls `seed_germany_source_evidence.seed_germany_source_evidence(db)`
  for real, because the registry row-builder functions below need real
  SourceArtifact ids to resolve `authority_source_id` — this is the one
  necessary write, and it lands only in the disposable SQLite file, never
  a real system of record.
- For every Germany registry, calls ONLY the private row-builder function
  (`_contribution_ceiling_rows(db)`, `_pv_configuration_rows(db)`, etc.)
  that scripts/seed_germany_2026_registries.py itself uses to compute the
  dicts it would pass to `GermanyX(**entry)` — this script never calls
  that constructor, never calls `db.add()`, and never calls
  `seed_germany_2026_registries()` itself. Zero registry rows are ever
  created, even in the disposable file.
- Never touches PAYROLL_DATABASE_URL/production. Never imports anything
  that would open a connection to it.

Usage:
    python -m scripts.germany_activation_dry_run
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_DB_FILE = Path(tempfile.gettempdir()) / "zoiko_germany_dry_run_8dc.sqlite3"
if _DB_FILE.exists():
    _DB_FILE.unlink()

os.environ["PAYROLL_DATABASE_URL"] = f"sqlite:///{_DB_FILE.as_posix()}"

from scripts._local_db_guard import assert_local_database, describe_target, is_local_database

assert_local_database("germany_activation_dry_run")
print(f"[dry-run] target (guard-verified local): {describe_target()}  is_local={is_local_database()}")

from app.database import SessionLocal, initialize_database

initialize_database()
db = SessionLocal()

try:
    from scripts.seed_germany_source_evidence import seed_germany_source_evidence
    from scripts import seed_germany_2026_registries as reg

    artifacts = seed_germany_source_evidence(db)
    print(f"\n=== Source evidence/artifacts ===")
    print(f"  created: {len(artifacts)} SourceArtifact rows (disposable SQLite only)")

    # Composite natural keys copied verbatim from seed_germany_2026_registries
    # .seed_germany_2026_registries()'s own existing-row duplicate check for
    # each model (the exact fields that function queries on before
    # deciding whether to create a row) — NOT a simplified guess, so this
    # dry run's conflict detection matches the real application logic
    # field-for-field.
    row_builders = [
        ("contribution_ceilings", reg._contribution_ceiling_rows, ("branch", "effective_from")),
        ("pv_configurations", reg._pv_configuration_rows, ("child_category", "is_saxony", "effective_from")),
        ("health_funds", reg._health_fund_rows, ("health_fund_id", "effective_from")),
        ("u1_tariffs", reg._u1_tariff_rows, ("health_fund_id", "tariff_identifier", "effective_from")),
        ("earning_taxability_rules", reg._earning_taxability_rows, ("earning_type", "effective_from")),
        ("overtime_premium_categories", reg._overtime_premium_category_rows, ("category_code", "effective_from")),
        ("overtime_grundlohn_caps", reg._overtime_grundlohn_cap_rows, ("dimension", "effective_from")),
        ("church_tax_exceptions", reg._church_tax_exception_rows,
         ("land_code", "denomination", "municipality_postal_code", "effective_from")),
    ]

    print("\n=== Registry dry-run (computed only — ZERO registry rows created) ===")
    total_missing_source = 0
    grand_total = 0
    for label, builder, key_fields in row_builders:
        entries = builder(db)
        grand_total += len(entries)
        eff_froms = sorted({str(e.get("effective_from")) for e in entries})
        eff_tos = sorted({str(e.get("effective_to")) for e in entries})
        missing_source = [
            tuple(e.get(f) for f in key_fields) for e in entries if not e.get("authority_source_id")
        ]
        total_missing_source += len(missing_source)

        # Duplicate-key detection WITHIN the computed set itself, using the
        # real composite natural key — the only meaningful conflict check
        # on a guaranteed-empty fresh database (existing-row lookups
        # against an empty DB can never reveal a data-authoring bug like
        # two rows sharing a natural key).
        seen = {}
        dupes = []
        for e in entries:
            k = tuple(str(e.get(f)) for f in key_fields)
            if k in seen:
                dupes.append(k)
            seen[k] = True

        print(f"  {label}: {len(entries)} row(s) that would be created, status=DRAFT")
        print(f"    natural key: {key_fields}")
        print(f"    effective_from values: {eff_froms}")
        print(f"    effective_to values:   {eff_tos}")
        print(f"    rows missing authority_source_id: {len(missing_source)} {missing_source if missing_source else ''}")
        print(f"    duplicate natural keys within computed set: {len(dupes)} {dupes if dupes else ''}")

    print(f"\n  TOTAL registry rows that would be created across all 8 categories: {grand_total}")
    print(f"  TOTAL rows with no traceable source artifact: {total_missing_source}")

finally:
    db.close()
    from app import database as _database_module
    _database_module.engine.dispose()
    try:
        _DB_FILE.unlink()
        print(f"\n[dry-run] disposable SQLite file deleted: {_DB_FILE}")
    except FileNotFoundError:
        pass
