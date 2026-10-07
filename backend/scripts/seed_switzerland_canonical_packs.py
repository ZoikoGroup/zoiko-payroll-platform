"""
scripts/seed_switzerland_canonical_packs.py
-------------------------------------------
Seeds the canonical (organization_id IS NULL) Switzerland content as DRAFT:
the CH-PAYROLL-2026 federal JurisdictionPack with every federal scalar
parameter from engine/countries/switzerland_content.py, one CH-<XX>-PAYROLL-2026
Draft pack per canton (five inert parameter SCAFFOLDS each — every value NULL,
so the engine refuses to calculate from them until the canton's own published
tariff / FAK rates are entered), a CH-PAYROLL-2027-07 change-watch pack (EOG
revision in force 1 July 2027), plus Switzerland's jurisdiction_service_registry
row as PLANNED.

NO ZP-CH SPEC EXISTS IN THIS REPOSITORY. The federal values are the published
2026 statutory figures the content module cites (S1-S10); every entrance is
flagged needs_g1 and every pack stays Draft — the statutory review that must
precede launch (gate G1) has one small, complete file to sign off. Nothing here
is ever activated and this script never claims a source document it did not
retrieve (no SourceArtifact is registered for the web references).

Governance: nothing is ever set Active here, and the registry row is created
only when missing (an existing row is never changed). Re-running refuses to
touch a pack that has left Draft; a Draft pack's rows are replaced wholesale
from the content, so an unchanged re-run produces the same rows.

Strict guard: Switzerland has not passed gate G1, so this script is stricter
than the Italy/Sweden seeds — main() refuses to run unless BOTH
(a) ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND is set AND (b) the target
database URL has been printed and confirmed interactively (type CONFIRM).
A non-interactive run is refused outright.

Usage:
    python -m scripts.seed_switzerland_canonical_packs
"""
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.engine.countries.switzerland_content import (  # noqa: E402
    CH_CANTON_CODES, CH_CANTON_PARAMETER_KEYS, CH_CANTON_PARAMETER_LABELS, CH_CANTONS,
    CH_FEDERAL_PARAMETER_KEYS, CH_FEDERAL_SEED_2026, CH_PARAMETER_KEYS, CH_QST_ANNUAL_MODEL_CANTONS,
    CH_SOURCES,
)
from app.modules.payroll.models import ContributionRate, JurisdictionPack  # noqa: E402
from scripts._local_db_guard import describe_target, is_local_database  # noqa: E402

CODE = "CH"
CURRENCY = "CHF"
SPEC = "Switzerland 2026 — published federal statutory sources (S1-S10); no ZP-CH spec yet"
AUTHORITY = "Bundesamt für Sozialversicherungen (BSV); Eidgenössische Steuerverwaltung (ESTV); BVG-Kommission"
_OVERRIDE_ENV = "ZOIKO_ALLOW_NONLOCAL_DB_WRITES"
_OVERRIDE_VALUE = "I_UNDERSTAND"

FEDERAL_PACK_ID = "CH-PAYROLL-2026"
FUTURE_PACK_ID = "CH-PAYROLL-2027-07"
CANTON_SOURCE_REFERENCE = (
    "Canton Quellensteuer tariff / FAK rates are NOT published figures this tool can retrieve — "
    "every canton cell is an inert NULL scaffold to be entered from the canton's own published rates."
)
EOG_NOTICE = (
    "EOG revision (S11) in force 1 July 2027 — revised EO compensation; no rows yet, change-watch pack only."
)


def _dec(value):
    return Decimal(str(value)) if value is not None else None


def _pct_display(value):
    return f"{value.normalize():f}%" if value is not None else "—"


def _ensure_service_registry_row(db) -> str:
    """Switzerland's jurisdiction_service_registry row, PLANNED, created only
    when missing — an existing row is never changed (same rule as Italy)."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def _source_references(canton_state=None) -> str:
    refs = "; ".join(f"[{i}] {t} <{u}>" for i, t, u in CH_SOURCES)
    refs = f"{SPEC}; " + refs
    if canton_state is not None:
        refs += "; " + CANTON_SOURCE_REFERENCE
        if canton_state in CH_QST_ANNUAL_MODEL_CANTONS:
            refs += f" [{canton_state}: Jahresmodell (ANNUAL) per S9]"
    return refs


def _upsert_pack(db, *, pack_id, jurisdiction_state, effective_from, effective_to, tax_year,
                 compliance_category, change_summary, source_references) -> JurisdictionPack:
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{pack_id} v1.0 is {pack.status!r}, not Draft — refusing to rewrite "
                         "a pack that has entered review/approval. Create a new version from Super Admin instead.")
    created = pack is None
    if created:
        pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=CODE, version="1.0")
        db.add(pack)
    pack.jurisdiction_state = jurisdiction_state
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from = effective_from
    pack.effective_to = effective_to
    pack.tax_year = tax_year
    pack.currency = CURRENCY
    pack.regulatory_authority = AUTHORITY
    pack.compliance_category = compliance_category
    pack.compliance_owner = "Super Admin — Switzerland build"
    pack.change_summary = change_summary
    pack.source_references = source_references
    db.flush()
    return pack


def _add_rate(db, pack, sort_order, key, label, *, employer_rate_pct=None, employee_rate_pct=None,
              flat_amount=None):
    if key not in CH_PARAMETER_KEYS:
        raise SystemExit(f"{key} is not in engine CH_PARAMETER_KEYS — catalog drift")
    if len(label) > 100:
        raise SystemExit(f"ContributionRate label longer than 100 characters: {label!r}")
    er, ee, flat = _dec(employer_rate_pct), _dec(employee_rate_pct), _dec(flat_amount)
    shown = str(flat) if flat is not None else None
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        jurisdiction_state=pack.jurisdiction_state,
        component_key=key, label=label,
        employee_share=_pct_display(ee) if ee is not None else (shown or "—"),
        employer_share=_pct_display(er) if er is not None else "—",
        total=_pct_display(er if er is not None else ee) if (er is not None or ee is not None) else (shown or "—"),
        employer_rate_pct=er, employee_rate_pct=ee, flat_amount=flat,
        sort_order=sort_order,
    ))


def _rewrite_pack_rows(db, pack):
    """Italy's non-destructive idempotency: a Draft pack's canonical rows are
    replaced wholesale from the content, so an unchanged re-run produces the
    same rows.
    """
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).delete()


def _seed_federal_pack(db):
    federal_keys = {key for key, _label, _ee, _er, _flat, _source, _g1 in CH_FEDERAL_SEED_2026}
    if set(CH_FEDERAL_PARAMETER_KEYS) != federal_keys:
        missing = set(CH_FEDERAL_PARAMETER_KEYS) - federal_keys
        stale = federal_keys - set(CH_FEDERAL_PARAMETER_KEYS)
        raise SystemExit(f"Federal pack drift — CH_FEDERAL_SEED_2026 keys do not match CH_FEDERAL_PARAMETER_KEYS: "
                         f"missing={sorted(missing)} stale={sorted(stale)}")

    pack = _upsert_pack(
        db, pack_id=FEDERAL_PACK_ID, jurisdiction_state=None,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31), tax_year="2026",
        compliance_category="AHV / IV / EO / ALV / UVG / BVG / FAK / QST",
        change_summary=f"v1.0 — {SPEC}: 3 federal contribution pairs (AHV 8.7%, IV 1.4%, EO 0.5%), "
                       "ALV 2.2% with the CHF 148,200 ceiling, UVG ceiling CHF 148,200 / NBUV from 8 h/week, "
                       "BVG 2026 measures (22,680 / 26,460 / 90,720 / 3,780), FAK federal minimums (215 / 268, "
                       "threshold 630/mo and 7,560/yr), EO parental 80% up to CHF 220/day, CHF 0.05 rounding. "
                       "Every value needs_g1 — Draft pending the gate G1 statutory review.",
        source_references=_source_references(),
    )
    _rewrite_pack_rows(db, pack)
    for order, (key, label, ee, er, flat, _source, _g1) in enumerate(CH_FEDERAL_SEED_2026, start=1):
        _add_rate(db, pack, order, key, label,
                  employee_rate_pct=ee, employer_rate_pct=er, flat_amount=flat)
    return pack


def _seed_canton_packs(db):
    canton_keys = set(CH_CANTON_PARAMETER_KEYS)
    packs = []
    for canton_index, (canton_code, canton_name) in enumerate(CH_CANTONS, start=1):
        pack = _upsert_pack(
            db, pack_id=f"{canton_code}-PAYROLL-2026", jurisdiction_state=canton_code,
            effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31), tax_year="2026",
            compliance_category="Quellensteuer / FAK",
            change_summary=f"v1.0 — Draft canton SCAFFOLD for {canton_name} ({canton_code}). "
                           "Every value is NULL until the canton's own published Quellensteuer tariff and FAK "
                           "rates are entered (CANTON_SOURCE_REFERENCE); the engine refuses to calculate from a "
                           "NULL row.",
            source_references=_source_references(canton_state=canton_code),
        )
        _rewrite_pack_rows(db, pack)
        for order, key in enumerate(CH_CANTON_PARAMETER_KEYS, start=1):
            label = f"{CH_CANTON_PARAMETER_LABELS[key]} — {canton_code} [unfilled scaffold]"
            _add_rate(db, pack, order, key, label)
        packs.append(pack)
    return packs


def _seed_future_pack(db):
    pack = _upsert_pack(
        db, pack_id=FUTURE_PACK_ID, jurisdiction_state=None,
        effective_from=date(2027, 7, 1), effective_to=None, tax_year="2027-07",
        compliance_category="EO (EOG revision)",
        change_summary="v1.0 — change-watch pack with NO rows yet: " + EOG_NOTICE,
        source_references=_source_references(),
    )
    _rewrite_pack_rows(db, pack)
    return pack


def seed_switzerland(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    federal = _seed_federal_pack(db)
    cantons = _seed_canton_packs(db)
    future = _seed_future_pack(db)
    availability = _ensure_service_registry_row(db)

    packs = [(federal, "federal"), *[(p, "canton") for p in cantons], (future, "future")]
    for pack, _kind in packs:
        count = (db.query(ContributionRate)
                 .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                         ContributionRate.organization_id.is_(None)).count())
        record_tax_audit(
            db, actor_id=None, action="seed", entity_type="jurisdiction_pack", entity_id=pack.id,
            jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
            old_value=None, new_value={"status": pack.status, "contribution_rates": str(count)},
            reason=f"Canonical Switzerland pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
                   "(scripts/seed_switzerland_canonical_packs.py) — Draft, needs_g1.",
            auto_commit=False,
        )
    db.flush()
    return {
        "federal": federal, "cantons": cantons, "future": future, "availability": availability,
    }


def _require_confirmed_target() -> None:
    target = describe_target()
    print(f"[seed_switzerland_canonical_packs] TARGET DATABASE: {target or '<not configured>'}")
    if (os.environ.get(_OVERRIDE_ENV) or "").strip() != _OVERRIDE_VALUE:
        print(
            f"\n[seed_switzerland_canonical_packs] REFUSING - Switzerland has not passed gate G1; a stray run of "
            f"this statutory WRITE script is worse than for other countries.\n"
            f"  Target: {target or '<not configured>'}\n\n"
            f"  Set {_OVERRIDE_ENV}={_OVERRIDE_VALUE} to proceed (this is stricter than assert_local_database - "
            f"required even for a local SQLite target).\n",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not is_local_database():
        print(
            f"[seed_switzerland_canonical_packs] WARNING: the target is NOT a local/isolated database "
            f"({target}). Confirm carefully below.", file=sys.stderr,
        )
    if not sys.stdin.isatty():
        print(
            "[seed_switzerland_canonical_packs] REFUSING - non-interactive run: there is no keyboard to confirm "
            "the printed target database. Re-run in an interactive terminal and type CONFIRM.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print("[seed_switzerland_canonical_packs] The target database is printed above. Type CONFIRM to proceed:")
    if sys.stdin.readline().strip() != "CONFIRM":
        print("[seed_switzerland_canonical_packs] Not confirmed - aborting.", file=sys.stderr)
        raise SystemExit(2)


def main() -> None:
    _require_confirmed_target()
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_switzerland(db)
        db.commit()
        print(f"Seeded {out['federal'].pack_id} v{out['federal'].version} as Draft "
              f"({len(CH_FEDERAL_SEED_2026)} ContributionRate rows)")
        for pack in out["cantons"]:
            print(f"Seeded {pack.pack_id} v{pack.version} as Draft (5 inert scaffold rows — all NULL)")
        print(f"Seeded {out['future'].pack_id} v{out['future'].version} as Draft (0 rows, change-watch)")
        print(f"service availability={out['availability']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()