"""
scripts/seed_brazil_canonical_packs.py
--------------------------------------
Seeds the canonical (organization_id IS NULL) Brazil content as DRAFT: one
BR-PAYROLL-2026 national tax JurisdictionPack holding every statutory row of
engine/countries/brazil_content.py (INSS bands, IRRF table + deductions, the
Lei 15.270/2025 reduction, minimum wage, salário-família, FGTS, CPP and the
2026 CPRB transition), the SourceArtifact evidence each row cites, and Brazil's
jurisdiction_service_registry row as PLANNED.

Source: ZP-BR-ENG-001 v1.0. Every value comes from brazil_content, itself
transcribed only from the files saved under docs/brazil/sources/
(SOURCES_MANIFEST.csv). The eSocial rubric catalogue is NOT seeded here: its
incidence codes are not yet verified against a saved Tabela 03 (BR-K3).

Evidence: one SourceArtifact per saved document, matched by URL + SHA-256 (a
changed file becomes a NEW artifact). A row that cites a source the manifest
does not list as VERIFIED refuses the seed, and so does a saved file whose
SHA-256 no longer matches its manifest row.

Governance: nothing is ever set Active here; the registry row is created only
when missing (an existing row is never changed). Re-running refuses to touch a
pack that has left Draft; a Draft pack's rows are replaced wholesale from the
content, so an unchanged re-run produces the same rows. Activation still needs
the shared gates (four-eyes, evidence, a golden run that PASSes) and Brazil's
own pack_activation_refusal hook, which refuses until G1–G8 are signed.

Strict guard: Brazil has not passed gate G1 (spec §24), so this script refuses
to run unless BOTH (a) ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND is set AND
(b) the target database URL has been printed and confirmed interactively (type
CONFIRM). A non-interactive run is refused.

Usage:
    python -m scripts.seed_brazil_canonical_packs
"""
import csv
import hashlib
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.engine.countries import brazil_content as content  # noqa: E402
from app.modules.payroll.models import JurisdictionPack, SourceArtifact, TaxSlab  # noqa: E402
from scripts._local_db_guard import describe_target, is_local_database  # noqa: E402

CODE = "BR"
CURRENCY = "BRL"
SPEC = content.SPEC
AUTHORITY = "Receita Federal / INSS / MTE (FGTS) / Presidência da República"
_OVERRIDE_ENV = "ZOIKO_ALLOW_NONLOCAL_DB_WRITES"
_OVERRIDE_VALUE = "I_UNDERSTAND"

MAIN_PACK_ID, MAIN_FROM, MAIN_TO = content.BR_2026
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO_ROOT / "docs" / "brazil" / "sources"
MANIFEST_PATH = SOURCES_DIR / "SOURCES_MANIFEST.csv"
_USABLE_STATUSES = ("VERIFIED",)
# The pack's primary evidence once VERIFIED (the shared activation gate requires one).
_PRIMARY_SOURCE = "S1"


def _parse_ts(value):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _overlaps(eff_from, eff_to, start, end) -> bool:
    return (eff_from is None or eff_from <= end) and (eff_to is None or eff_to >= start)


# ── evidence ────────────────────────────────────────────────────────────────

def load_manifest(path: Path = None) -> dict:
    """{code: manifest row} for every usable (VERIFIED) source file."""
    path = Path(path or MANIFEST_PATH)
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {row["code"]: row for row in csv.DictReader(fh)
                if (row.get("status") or "").strip() in _USABLE_STATUSES}


def _check_file(row: dict, sources_dir: Path) -> None:
    file_path = Path(sources_dir) / row["file"]
    if not file_path.is_file():
        raise SystemExit(f"[{row['code']}] {row['file']} is listed as VERIFIED but is not saved under {sources_dir}")
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    if digest != row["sha256"]:
        raise SystemExit(f"[{row['code']}] {row['file']} no longer matches its manifest SHA-256 "
                         f"({digest} != {row['sha256']}) — re-verify the source before seeding")


def _upsert_sources(db, manifest: dict, needed: set, sources_dir: Path = None) -> dict:
    """One SourceArtifact per saved document, matched by URL + SHA-256.
    Unreviewed — the human G1 reviewer marks each one reviewed."""
    sources_dir = Path(sources_dir or SOURCES_DIR)
    missing = sorted(needed - set(manifest))
    if missing:
        raise SystemExit(f"content cites {', '.join(missing)} but SOURCES_MANIFEST.csv has no VERIFIED file for "
                         "it — save and verify the source first")
    ids = {}
    for code in sorted(needed):
        row = manifest[code]
        _check_file(row, sources_dir)
        url, sha = row["url"], row["sha256"]
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.source_url == url, SourceArtifact.checksum_sha256 == sha).first())
        if artifact is None:
            artifact = SourceArtifact(
                agency=(row.get("issuer") or "")[:200] or "unknown", title=f"[{code}] {row['title']}"[:300],
                source_url=url, checksum_sha256=sha,
                file_path=f"docs/brazil/sources/{row['file']}", original_filename=row["file"],
                content_type=row.get("content_type") or None,
                file_size_bytes=int(row["bytes"]) if (row.get("bytes") or "").isdigit() else None,
                retrieved_at=_parse_ts(row.get("retrieved_at")),
            )
            db.add(artifact)
            db.flush()
        ids[code] = artifact.id
    return ids


# ── pack and rows ───────────────────────────────────────────────────────────

def _source_references() -> str:
    refs = content.SOURCE_REFERENCES + content.ADDENDUM_SOURCE_REFERENCES
    return f"{SPEC}; " + "; ".join(f"[{code}] {title}" for code, title in refs)


def _upsert_pack(db, source_document_id=None) -> JurisdictionPack:
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == MAIN_PACK_ID, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{MAIN_PACK_ID} v1.0 is {pack.status!r}, not Draft — refusing to rewrite a pack that "
                         "has entered review/approval. Create a new version from Super Admin instead.")
    if pack is None:
        pack = JurisdictionPack(pack_id=MAIN_PACK_ID, jurisdiction_country=CODE, version="1.0")
        db.add(pack)
    pack.jurisdiction_state = None
    pack.parent_pack_id = None
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from = MAIN_FROM
    pack.effective_to = MAIN_TO
    pack.tax_year = str(MAIN_FROM.year)
    pack.currency = CURRENCY
    pack.regulatory_authority = AUTHORITY
    pack.compliance_category = "INSS / IRRF + Lei 15.270 reduction / minimum wage / salário-família / FGTS / CPP"
    pack.compliance_owner = "Super Admin — Brazil build"
    pack.change_summary = (f"v1.0 — {SPEC} federal core, transcribed only from docs/brazil/sources/ "
                           f"(SOURCES_MANIFEST.csv). Content SHA-256 {content.CONTENT_HASH}. Every row "
                           f"{content.PENDING_G1} — Draft pending the gate G1 statutory review.")
    pack.source_references = _source_references()
    pack.source_document_id = source_document_id
    db.flush()
    return pack


def _rows_in_window():
    return [r for r in content.BR_CONTENT_ROWS if _overlaps(r.effective_from, r.effective_to, MAIN_FROM, MAIN_TO)]


def _seed_rows(db, pack, source_ids) -> int:
    # Canonical rows only: an org-scoped row (organization_id IS NOT NULL) on
    # this pack is an organisation's override and is never deleted by a re-seed.
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()
    count = 0
    for order, row in enumerate(_rows_in_window(), start=1):
        label = f"{row.label} {content.PENDING_G1}"
        if len(label) > 150:
            raise SystemExit(f"TaxSlab rate_label longer than 150 characters: {label!r}")
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None, jurisdiction_state=None,
            rule_type=row.rule_type, filing_status=row.key,
            min_amount=row.min_amount if row.min_amount is not None else Decimal("0"),
            max_amount=row.max_amount,
            rate_pct=row.rate_pct if row.rate_pct is not None else Decimal("0"),
            flat_amount=row.flat_amount, rate_label=label,
            tax_formula=f"{row.rule_type} {row.key} — ZP-BR-ENG-001 [{row.source}]",
            effective_from=row.effective_from, effective_to=row.effective_to,
            source_document_id=source_ids[row.source], sort_order=order,
        ))
        count += 1
    db.flush()
    return count


def _ensure_service_registry_row(db) -> str:
    """Brazil's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_brazil(db, manifest: dict = None, sources_dir: Path = None) -> dict:
    from app.modules.payroll.service import record_tax_audit

    manifest = load_manifest() if manifest is None else manifest
    needed = {r.source for r in _rows_in_window()} | {_PRIMARY_SOURCE}
    source_ids = _upsert_sources(db, manifest, needed, sources_dir)
    pack = _upsert_pack(db, source_document_id=source_ids[_PRIMARY_SOURCE])
    slabs = _seed_rows(db, pack, source_ids)
    availability = _ensure_service_registry_row(db)
    record_tax_audit(
        db, actor_id=None, action="seed", entity_type="jurisdiction_pack", entity_id=pack.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
        old_value=None, new_value={"status": pack.status, "tax_slabs": str(slabs),
                                   "content_sha256": content.CONTENT_HASH},
        reason=f"Canonical Brazil pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
               "(scripts/seed_brazil_canonical_packs.py) — Draft, pending G1.",
        auto_commit=False,
    )
    db.flush()
    return {"pack": pack, "tax_slabs": slabs, "availability": availability, "sources": source_ids}


def _require_confirmed_target() -> None:
    target = describe_target()
    print(f"[seed_brazil_canonical_packs] TARGET DATABASE: {target or '<not configured>'}")
    if (os.environ.get(_OVERRIDE_ENV) or "").strip() != _OVERRIDE_VALUE:
        print(
            f"\n[seed_brazil_canonical_packs] REFUSING - Brazil has not passed gate G1; a stray run "
            f"of this statutory WRITE script is worse than for other countries.\n"
            f"  Target: {target or '<not configured>'}\n\n"
            f"  Set {_OVERRIDE_ENV}={_OVERRIDE_VALUE} to proceed (required even for a local SQLite target).\n",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not is_local_database():
        print(f"[seed_brazil_canonical_packs] WARNING: the target is NOT a local/isolated database "
              f"({target}). Confirm carefully below.", file=sys.stderr)
    if not sys.stdin.isatty():
        print("[seed_brazil_canonical_packs] REFUSING - non-interactive run: there is no keyboard to confirm "
              "the printed target database. Re-run in an interactive terminal and type CONFIRM.", file=sys.stderr)
        raise SystemExit(2)
    print("[seed_brazil_canonical_packs] The target database is printed above. Type CONFIRM to proceed:")
    if sys.stdin.readline().strip() != "CONFIRM":
        print("[seed_brazil_canonical_packs] Not confirmed - aborting.", file=sys.stderr)
        raise SystemExit(2)


def main() -> None:
    _require_confirmed_target()
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_brazil(db)
        db.commit()
        print(f"Seeded {out['pack'].pack_id} v{out['pack'].version} as Draft ({out['tax_slabs']} TaxSlab rows); "
              f"source artifacts={len(out['sources'])} service availability={out['availability']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
