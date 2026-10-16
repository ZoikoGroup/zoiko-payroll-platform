"""
scripts/seed_mexico_canonical_packs.py
--------------------------------------
Seeds the canonical (organization_id IS NULL) Mexico content as DRAFT:
one MX-PAYROLL-2026 national tax JurisdictionPack (every scalar parameter,
every Art. 96 ISR bracket, minimum wage, the 2026 CEAV bands, workweek and
vacation rows whose legal window touches 2026), one MX-ISN-<STATE>-2026 state
pack per state in scope (parent -> the national pack; CDMX only), a
StateLocalProgramReadiness row per state, the SourceArtifact evidence each
row cites, and Mexico's jurisdiction_service_registry row as PLANNED.

Source: ZP-MX-ENG-001 v1.0. Every value comes from
engine/countries/mexico_content.py, itself transcribed only from the files
saved under docs/mexico/sources/ (SOURCES_MANIFEST.csv). While that content
is empty this script still creates the Draft packs, the registry row and the
readiness rows — with zero statutory rows.

Evidence: one SourceArtifact per saved document, matched by URL + SHA-256
(a changed file becomes a NEW artifact, HK seed pattern). A content row that
cites a source the manifest does not list as VERIFIED refuses the seed.

Governance: nothing is ever set Active here, and the registry/readiness rows
are created only when missing (an existing row is never changed). Re-running
refuses to touch a pack that has left Draft; a Draft pack's rows are replaced
wholesale from the content, so an unchanged re-run produces the same rows.

Strict guard: Mexico has not passed gate G1 (spec §22), so this script
refuses to run unless BOTH (a) ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND is
set AND (b) the target database URL has been printed and confirmed
interactively (type CONFIRM). A non-interactive run is refused.

Usage:
    python -m scripts.seed_mexico_canonical_packs
"""
import csv
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.engine.countries import mexico_content as content  # noqa: E402
from app.modules.payroll.models import (  # noqa: E402
    ContributionRate, JurisdictionPack, SourceArtifact, StateLocalProgramReadiness, TaxSlab,
)
from scripts._local_db_guard import describe_target, is_local_database  # noqa: E402

CODE = "MX"
CURRENCY = "MXN"
SPEC = content.SPEC
AUTHORITY = "SAT / IMSS / INFONAVIT / STPS-CONASAMI"
_OVERRIDE_ENV = "ZOIKO_ALLOW_NONLOCAL_DB_WRITES"
_OVERRIDE_VALUE = "I_UNDERSTAND"

MAIN_PACK_ID, MAIN_FROM, MAIN_TO = content.MX_2026
REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "docs" / "mexico" / "sources" / "SOURCES_MANIFEST.csv"
# Manifest statuses whose file may back a seeded row (scripts/verify_mexico_sources.py).
_USABLE_STATUSES = ("VERIFIED",)
# ISN readiness: Mexico ISN uses the generic "other state payroll" program —
# not STATE_PT, which is India's employee professional tax (Phase 0 decision 6).
_ISN_PROGRAM = "OTHER_STATE_PAYROLL"


def _dec(value):
    return Decimal(str(value)) if value is not None else None


def _pct_display(value):
    return f"{value.normalize():f}%" if value is not None else "—"


def _marked(label: str, *, pending_g2: bool = False) -> str:
    marks = f" {content.PENDING_G1}" + (f" {content.PENDING_G2}" if pending_g2 else "")
    return label + marks


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


def _upsert_sources(db, manifest: dict, needed: set) -> dict:
    """One SourceArtifact per saved document, matched by URL + SHA-256.
    Unreviewed — the human G1 reviewer marks each one reviewed."""
    missing = sorted(needed - set(manifest))
    if missing:
        raise SystemExit(f"content cites {', '.join(missing)} but SOURCES_MANIFEST.csv has no VERIFIED file for "
                         "it — save and verify the source first (scripts/verify_mexico_sources.py)")
    ids = {}
    for code in sorted(needed):
        row = manifest[code]
        url, sha = row["url"], row["sha256"]
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.source_url == url, SourceArtifact.checksum_sha256 == sha).first())
        if artifact is None:
            artifact = SourceArtifact(
                agency=(row.get("issuer") or "")[:200] or "unknown", title=f"[{code}] {row['title']}"[:300],
                source_url=url, checksum_sha256=sha,
                file_path=f"docs/mexico/sources/{row['file']}", original_filename=row["file"],
                content_type=row.get("content_type") or None,
                file_size_bytes=int(row["bytes"]) if (row.get("bytes") or "").isdigit() else None,
                retrieved_at=_parse_ts(row.get("retrieved_at")),
            )
            db.add(artifact)
            db.flush()
        ids[code] = artifact.id
    return ids


def _parse_ts(value):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


# ── packs and rows ──────────────────────────────────────────────────────────

def _upsert_pack(db, *, pack_id, state, parent, compliance_category, change_summary) -> JurisdictionPack:
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{pack_id} v1.0 is {pack.status!r}, not Draft — refusing to rewrite "
                         "a pack that has entered review/approval. Create a new version from Super Admin instead.")
    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=CODE, version="1.0")
        db.add(pack)
    pack.jurisdiction_state = state
    pack.parent_pack_id = parent.id if parent is not None else None
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from = MAIN_FROM
    pack.effective_to = MAIN_TO
    pack.tax_year = str(MAIN_FROM.year)
    pack.currency = CURRENCY
    pack.regulatory_authority = AUTHORITY
    pack.compliance_category = compliance_category
    pack.compliance_owner = "Super Admin — Mexico build"
    pack.change_summary = change_summary
    pack.source_references = _source_references()
    db.flush()
    return pack


def _rewrite_pack_rows(db, pack):
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).delete()


def _add_rate(db, pack, sort_order, row, source_ids, *, state=None):
    spec = content.MX_PARAMETER_KEYS.get(row.key)
    if spec is None:
        raise SystemExit(f"{row.key} is not in MX_PARAMETER_KEYS — catalog drift")
    kind, label, scope = spec
    if (scope == "state") != (state is not None):
        raise SystemExit(f"{row.key} is a {scope} parameter and cannot be seeded into this pack")
    if row.pending_g2 != (row.key in content.MX_PENDING_G2_KEYS):
        raise SystemExit(f"{row.key}: pending_g2 flag disagrees with MX_PENDING_G2_KEYS")
    label = _marked(label, pending_g2=row.pending_g2)
    if len(label) > 100:
        raise SystemExit(f"ContributionRate label longer than 100 characters: {label!r}")
    er, ee, flat = _dec(row.employer_pct), _dec(row.employee_pct), _dec(row.flat_amount)
    shown = str(flat) if flat is not None else (row.text_value if row.text_value is not None else None)
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        jurisdiction_state=state, component_key=row.key, label=label,
        employee_share=_pct_display(ee) if ee is not None else (shown or "—"),
        employer_share=_pct_display(er) if er is not None else "—",
        total=(_pct_display(er if er is not None else ee) if (er is not None or ee is not None) else (shown or "—")),
        employer_rate_pct=er, employee_rate_pct=ee, flat_amount=flat, text_value=row.text_value,
        effective_from=row.effective_from, effective_to=row.effective_to,
        source_document_id=source_ids[row.source], sort_order=sort_order,
    ))


def _add_slab(db, pack, sort_order, source_ids, *, rule_type, filing_status, rate_label, tax_formula, rate_pct,
              source, min_amount="0", max_amount=None, flat_amount=None, effective_from=None, effective_to=None,
              tax_table_number=None, assessment_basis=None):
    rate_label = _marked(rate_label)
    if len(rate_label) > 150:
        raise SystemExit(f"TaxSlab rate_label longer than 150 characters: {rate_label!r}")
    db.add(TaxSlab(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None, jurisdiction_state=None,
        rule_type=rule_type, filing_status=filing_status,
        min_amount=_dec(min_amount), max_amount=_dec(max_amount), rate_pct=_dec(rate_pct),
        flat_amount=_dec(flat_amount), rate_label=rate_label, tax_formula=tax_formula,
        tax_table_number=tax_table_number, assessment_basis=assessment_basis,
        effective_from=effective_from, effective_to=effective_to,
        source_document_id=source_ids[source], sort_order=sort_order,
    ))


def _national_rows(start, end):
    """Every national content row whose legal window touches the pack window."""
    scalars = [r for r in content.MX_SCALAR_CONTENT if _overlaps(r.effective_from, r.effective_to, start, end)]
    isr = [b for b in content.MX_ISR_TARIFFS if _overlaps(b.effective_from, b.effective_to, start, end)]
    wages = [w for w in content.MX_MIN_WAGES if _overlaps(w.effective_from, w.effective_to, start, end)]
    ceav = [b for b in content.MX_CEAV_SCHEDULE if b.year == content.MX_CEAV_SEEDED_YEAR]
    week = [w for w in content.MX_WORKWEEK if _overlaps(w.effective_from, w.effective_to, start, end)]
    vac = [v for v in content.MX_VACATION_DAYS if _overlaps(v.effective_from, v.effective_to, start, end)]
    return scalars, isr, wages, ceav, week, vac


def _cited_sources() -> set:
    scalars, isr, wages, ceav, week, vac = _national_rows(MAIN_FROM, MAIN_TO)
    cited = {r.source for group in (scalars, isr, wages, ceav, week, vac) for r in group}
    cited |= {r.source for rows in content.MX_ISN_CONTENT.values() for r in rows}
    return cited


def _seed_national_pack(db, source_ids) -> JurisdictionPack:
    pack = _upsert_pack(
        db, pack_id=MAIN_PACK_ID, state=None, parent=None,
        compliance_category="ISR / subsidio al empleo / IMSS / CEAV / INFONAVIT / labour floors",
        change_summary=f"v1.0 — {SPEC} federal core, transcribed only from docs/mexico/sources/ "
                       "(SOURCES_MANIFEST.csv). Every row needs_g1 — Draft pending the gate G1 statutory review.",
    )
    _rewrite_pack_rows(db, pack)
    scalars, isr, wages, ceav, week, vac = _national_rows(MAIN_FROM, MAIN_TO)
    order = 0
    for row in scalars:
        order += 1
        _add_rate(db, pack, order, row, source_ids)
    for b in isr:
        order += 1
        _add_slab(db, pack, order, source_ids, rule_type=content.MX_ISR_TARIFF_RULE, filing_status=b.period,
                  min_amount=b.lower, max_amount=b.upper, flat_amount=b.fixed_quota, rate_pct=b.rate_pct,
                  rate_label=f"{b.rate_pct}% over {b.lower}", tax_formula=f"ISR Art. 96 tariff — {b.period}",
                  source=b.source, effective_from=b.effective_from, effective_to=b.effective_to)
    for w in wages:
        order += 1
        _add_slab(db, pack, order, source_ids, rule_type=content.MX_MIN_WAGE_RULE, filing_status=w.code,
                  flat_amount=w.daily_amount, rate_pct="0", rate_label=f"MXN {w.daily_amount}/day",
                  tax_formula=f"Minimum wage — {w.description}", source=w.source, assessment_basis=w.kind,
                  effective_from=w.effective_from, effective_to=w.effective_to)
    for b in ceav:
        order += 1
        _add_slab(db, pack, order, source_ids, rule_type=content.MX_CEAV_BAND_RULE,
                  filing_status=f"{b.lower_multiple}{b.lower_unit}", min_amount=b.lower_multiple,
                  max_amount=b.upper_multiple, rate_pct=b.employer_pct, rate_label=f"{b.employer_pct}% employer",
                  tax_formula=f"CEAV {b.year} band {b.lower_multiple} {b.lower_unit} – "
                              f"{b.upper_multiple or '∞'} {b.upper_unit or ''}".strip(),
                  source=b.source, tax_table_number=str(b.year), assessment_basis=f"{b.lower_unit}/{b.upper_unit or '-'}",
                  effective_from=b.effective_from, effective_to=b.effective_to)
    for w in week:
        order += 1
        _add_slab(db, pack, order, source_ids, rule_type=content.MX_WORKWEEK_RULE, filing_status="WEEKLY_MAX",
                  flat_amount=w.ordinary_weekly_max_hours, rate_pct="0",
                  rate_label=f"{w.ordinary_weekly_max_hours} h/week",
                  tax_formula="; ".join(f"{k}={v}" for k, v in w.overtime_rules) or "workweek",
                  source=w.source, effective_from=w.effective_from, effective_to=w.effective_to)
    for v in vac:
        order += 1
        _add_slab(db, pack, order, source_ids, rule_type=content.MX_VACATION_DAYS_RULE,
                  filing_status=f"YEAR_{v.service_year_from}", min_amount=str(v.service_year_from),
                  max_amount=str(v.service_year_to) if v.service_year_to is not None else None,
                  flat_amount=v.days, rate_pct="0", rate_label=f"{v.days} days",
                  tax_formula="Vacation days by years of service", source=v.source,
                  effective_from=v.effective_from, effective_to=v.effective_to)
    return pack


def _seed_isn_pack(db, state, national, source_ids) -> JurisdictionPack:
    pack = _upsert_pack(
        db, pack_id=content.MX_ISN_PACK_ID_FORMAT.format(state=state), state=state, parent=national,
        compliance_category=f"Impuesto Sobre Nóminas — {state}",
        change_summary=f"v1.0 — {state} state payroll tax overlay ({SPEC} §15), separately versioned (MX-047). "
                       "Every row needs_g1 — Draft pending the gate G4 statutory review.",
    )
    _rewrite_pack_rows(db, pack)
    for order, row in enumerate(content.MX_ISN_CONTENT.get(state, ()), start=1):
        _add_rate(db, pack, order, row, source_ids, state=state)
    return pack


def _ensure_isn_readiness_row(db, state) -> None:
    """One OTHER_STATE_PAYROLL readiness row per state in scope — Mexico ISN
    (Phase 0 decision 6). Created only when missing; never changed."""
    exists = (db.query(StateLocalProgramReadiness)
              .filter(StateLocalProgramReadiness.jurisdiction_country == CODE,
                      StateLocalProgramReadiness.jurisdiction_state == state,
                      StateLocalProgramReadiness.jurisdiction_locality.is_(None),
                      StateLocalProgramReadiness.program == _ISN_PROGRAM).first())
    if exists is None:
        db.add(StateLocalProgramReadiness(
            jurisdiction_country=CODE, jurisdiction_state=state, jurisdiction_locality=None,
            program=_ISN_PROGRAM, legal_status="SOURCE_REQUIRED", registration_required=True,
            notes=f"Mexico state payroll tax (Impuesto Sobre Nóminas), {state} — {SPEC} §15; "
                  "program OTHER_STATE_PAYROLL (not India's STATE_PT)."))
        db.flush()


def _ensure_service_registry_row(db) -> str:
    """Mexico's jurisdiction_service_registry row, PLANNED, created only when
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


def _source_references() -> str:
    refs = content.SOURCE_REFERENCES + content.ADDENDUM_SOURCE_REFERENCES
    return f"{SPEC}; " + "; ".join(f"[{code}] {title}" for code, title in refs)


def seed_mexico(db, manifest: dict = None) -> dict:
    from app.modules.payroll.service import record_tax_audit

    manifest = load_manifest() if manifest is None else manifest
    source_ids = _upsert_sources(db, manifest, _cited_sources())
    national = _seed_national_pack(db, source_ids)
    isn = {state: _seed_isn_pack(db, state, national, source_ids) for state in content.MX_ISN_STATES_IN_SCOPE}
    for state in content.MX_ISN_STATES_IN_SCOPE:
        _ensure_isn_readiness_row(db, state)
    availability = _ensure_service_registry_row(db)

    for pack in (national, *isn.values()):
        rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
        slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count()
        record_tax_audit(
            db, actor_id=None, action="seed", entity_type="jurisdiction_pack", entity_id=pack.id,
            jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
            old_value=None, new_value={"status": pack.status, "contribution_rates": str(rates),
                                       "tax_slabs": str(slabs)},
            reason=f"Canonical Mexico pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
                   "(scripts/seed_mexico_canonical_packs.py) — Draft, needs_g1.",
            auto_commit=False,
        )
    db.flush()
    return {"national": national, "isn": isn, "availability": availability, "sources": source_ids}


def _require_confirmed_target() -> None:
    target = describe_target()
    print(f"[seed_mexico_canonical_packs] TARGET DATABASE: {target or '<not configured>'}")
    if (os.environ.get(_OVERRIDE_ENV) or "").strip() != _OVERRIDE_VALUE:
        print(
            f"\n[seed_mexico_canonical_packs] REFUSING - Mexico has not passed gate G1; a stray run "
            f"of this statutory WRITE script is worse than for other countries.\n"
            f"  Target: {target or '<not configured>'}\n\n"
            f"  Set {_OVERRIDE_ENV}={_OVERRIDE_VALUE} to proceed (this is stricter than assert_local_database - "
            f"required even for a local SQLite target).\n",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not is_local_database():
        print(
            f"[seed_mexico_canonical_packs] WARNING: the target is NOT a local/isolated database "
            f"({target}). Confirm carefully below.", file=sys.stderr,
        )
    if not sys.stdin.isatty():
        print(
            "[seed_mexico_canonical_packs] REFUSING - non-interactive run: there is no keyboard to confirm "
            "the printed target database. Re-run in an interactive terminal and type CONFIRM.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print("[seed_mexico_canonical_packs] The target database is printed above. Type CONFIRM to proceed:")
    if sys.stdin.readline().strip() != "CONFIRM":
        print("[seed_mexico_canonical_packs] Not confirmed - aborting.", file=sys.stderr)
        raise SystemExit(2)


def main() -> None:
    _require_confirmed_target()
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_mexico(db)
        db.commit()
        for pack in (out["national"], *out["isn"].values()):
            rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
            slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count()
            print(f"Seeded {pack.pack_id} v{pack.version} as Draft ({rates} ContributionRate rows, {slabs} TaxSlab rows)")
        print(f"source artifacts={len(out['sources'])} service availability={out['availability']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
