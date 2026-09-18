"""
scripts/seed_germany_2026_all_jurisdictions.py
------------------------------------------------
Creates/activates a Germany 2026 JurisdictionPack (jurisdiction_state, e.g.
"DE-BW") for all 16 German Länder, each linked back to the existing federal
pack (DE-PAYROLL-CY2026-V1) via parent_pack_id — using the exact same
JurisdictionPack governance framework seed_germany_compliance_pack_2026.py
already used to create that federal pack (no new architecture).

WHY A LAND PACK HOLDS NO RATES/SLABS OF ITS OWN

German federal income tax, solidarity surcharge, and social insurance
(RV/ALV/GKV/PV) are federal law — identical for every Land. The ONE
statutory value that genuinely varies by Land (Kirchensteuer/church tax,
8% in Bavaria/Baden-Württemberg, 9% elsewhere) is already fully modeled
end-to-end by an earlier phase (8BL), independently of JurisdictionPack:
a hardcoded default table (CHURCH_TAX_LAND_RATES in
engine/jurisdictions/germany/pap/core.py), an optional registry-override
mechanism (GermanyMinijobMidijobParameter rows keyed
"church_tax_rate_de_<land>"), and a per-employee selector
(EmployeeStatutoryProfile.de_church_tax_land) — see that module's own
"NOTE (2026-09-15 registry-readiness audit)" comment, which explicitly
states no additional church-tax base-rate registry is required. This
script does NOT create those 16 override rows: doing so would mean
minting a new SourceArtifact citation for values that already have a
correctly-cited home (the hardcoded table + the existing Bad Wimpfen
exception's own evidence chain) — inventing a fresh citation under this
task's time pressure is exactly the kind of fabrication the brief that
requested this script explicitly warns against. Publishing an override
per Land remains available as a genuine, separate governance action for
whoever owns that decision; this script does not make it for them.

So each Land pack here is real, but deliberately empty of its own
rates/slabs — this is not a placeholder to fill in "later"; it's the
correct final shape given federal centralization. It exists so that (a)
the platform-wide JurisdictionPack listing/governance UI can show, filter,
and audit Germany per-Land exactly like every other country's
state/devolved-nation packs (UK Scotland, US states), and (b) an org's
"which Länder do we operate in" question has a real, queryable governed
answer instead of only being inferable from employee-level
de_church_tax_land values after the fact.

WHY jurisdiction_state (never one-pack-per-Land IN PLACE OF the federal
pack)

engine/tax_resolver.py's _find_active_tax_pack already has the exact
policy this needs, used unmodified: a state-scoped pack only "wins" over
the country-level pack if it holds real income-tax TaxSlab rows
(_pack_has_income_tax_slabs). Every Land pack this script creates holds
none, so _find_active_tax_pack(db, "DE", state="DE-BY", ...) always falls
through to the federal pack — federal rules stay the single source of
truth for every Land, automatically, with zero new resolver code. This
mirrors this same table's existing UK Scotland precedent
(jurisdiction_state="Scotland" or similar, national pack still governs
income tax/NI) rather than inventing a parallel "one full pack per Land"
design the spec never asked for and Germany's actual tax law does not
support.

IDEMPOTENT / RESUMABLE: identical convention to
seed_germany_compliance_pack_2026.py — checks (pack_id, version) first;
if found and not yet Active, resumes the Approve/Activate steps instead of
either erroring or silently doing nothing (found necessary for real: this
script's own federal-pack sibling crashed mid-lifecycle once during this
task, from an unrelated pre-existing audit-column bug, fixed separately in
service.record_tax_audit).

Usage:
    PAYROLL_DATABASE_URL=sqlite:///./germany_local.sqlite3 \\
        python -m scripts.seed_germany_2026_all_jurisdictions \\
        --maker-id 12 --checker-id 34 --federal-pack-id 130
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_db_guard import assert_local_database, describe_target, is_local_database
from scripts._actor_authorization import resolve_and_authorize_maker_checker

SCRIPT_NAME = "seed_germany_2026_all_jurisdictions"

# (ISO 3166-2:DE subdivision code, English name per the task brief, pack_id suffix)
# Same 16 codes already used platform-wide for Germany Land selection:
# CHURCH_TAX_LAND_RATES, EmployeeStatutoryProfile.de_church_tax_land,
# and the church_tax_rate_de_* parameter codes — not a new convention.
GERMAN_LAENDER = [
    ("DE-BW", "Baden-Württemberg"),
    ("DE-BY", "Bavaria"),
    ("DE-BE", "Berlin"),
    ("DE-BB", "Brandenburg"),
    ("DE-HB", "Bremen"),
    ("DE-HH", "Hamburg"),
    ("DE-HE", "Hesse"),
    ("DE-MV", "Mecklenburg-Vorpommern"),
    ("DE-NI", "Lower Saxony"),
    ("DE-NW", "North Rhine-Westphalia"),
    ("DE-RP", "Rhineland-Palatinate"),
    ("DE-SL", "Saarland"),
    ("DE-SN", "Saxony"),
    ("DE-ST", "Saxony-Anhalt"),
    ("DE-SH", "Schleswig-Holstein"),
    ("DE-TH", "Thuringia"),
]

FEDERAL_PACK_ID_STR = "DE-PAYROLL-CY2026-V1"


def _land_pack_id(land_code: str) -> str:
    suffix = land_code.split("-", 1)[1]  # "DE-BW" -> "BW"
    return f"DE-{suffix}-PAYROLL-CY2026-V1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/activate a Germany 2026 JurisdictionPack for all 16 Länder, "
                    "each linked to the federal DE-PAYROLL-CY2026-V1 pack.",
    )
    parser.add_argument("--maker-id", type=int, required=True, help="Real, active Super Admin user id (maker).")
    parser.add_argument("--checker-id", type=int, required=True, help="Real, active Super Admin user id (checker). Must differ from --maker-id.")
    parser.add_argument(
        "--federal-pack-id", type=int, default=None,
        help=f"payroll_jurisdiction_packs.id of the existing federal {FEDERAL_PACK_ID_STR} pack. "
             "If omitted, resolved by looking up (pack_id, version='1.0'); refuses to run if not found "
             "or not Active.",
    )
    return parser.parse_args()


def _resolve_federal_pack(db, federal_pack_id):
    from app.modules.payroll.models import JurisdictionPack

    if federal_pack_id is not None:
        pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == federal_pack_id).first()
        if not pack:
            print(f"[{SCRIPT_NAME}] REFUSING TO RUN — no JurisdictionPack with id={federal_pack_id}.", file=sys.stderr)
            raise SystemExit(2)
    else:
        pack = (
            db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == FEDERAL_PACK_ID_STR, JurisdictionPack.version == "1.0")
            .first()
        )
        if not pack:
            print(
                f"[{SCRIPT_NAME}] REFUSING TO RUN — federal pack {FEDERAL_PACK_ID_STR} v1.0 not found. "
                "Run scripts.seed_germany_compliance_pack_2026 first.", file=sys.stderr,
            )
            raise SystemExit(2)
    if pack.jurisdiction_state is not None:
        print(
            f"[{SCRIPT_NAME}] REFUSING TO RUN — pack id={pack.id} ({pack.pack_id}) is not a country-level "
            f"pack (jurisdiction_state={pack.jurisdiction_state!r}); every Land pack must link to the real "
            "federal (country-level) pack, never to another Land's pack.", file=sys.stderr,
        )
        raise SystemExit(2)
    if pack.status != "Active":
        print(
            f"[{SCRIPT_NAME}] REFUSING TO RUN — federal pack id={pack.id} ({pack.pack_id}) is {pack.status!r}, "
            "not Active. Activate it first.", file=sys.stderr,
        )
        raise SystemExit(2)
    return pack


def _seed_one_land(db, service, JurisdictionPackUpsert, land_code: str, land_name: str, federal_pack, maker, checker) -> dict:
    from app.modules.payroll.models import JurisdictionPack

    pack_id_str = _land_pack_id(land_code)
    existing = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == pack_id_str, JurisdictionPack.version == "1.0")
        .first()
    )
    if existing is None:
        pack = service.upsert_jurisdiction_pack(
            db,
            JurisdictionPackUpsert(
                packId=pack_id_str,
                jurisdictionCountry="DE",
                jurisdictionState=land_code,
                packType="tax",
                version="1.0",
                status="Draft",
                effectiveFrom=date(2026, 1, 1),
                effectiveTo=date(2026, 12, 31),
                taxYear="2026",
                currency="EUR",
                regulatoryAuthority="Bundesministerium der Finanzen (BMF) / ITZBund",
                complianceCategory="Statutory Payroll Tax & Social Insurance — Land-level",
                complianceOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
                engineeringOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
                sourceReferences=(
                    f"Land-level governance wrapper for {land_name} ({land_code}); inherits federal "
                    f"{FEDERAL_PACK_ID_STR} for income tax/Soli/RV/ALV/GKV/PV (federal law, uniform "
                    "nationwide). Church tax is this Land's only genuine statutory difference; already "
                    "governed independently (CHURCH_TAX_LAND_RATES / church_tax_rate_de_* registry)."
                ),
                changeSummary=(
                    f"Initial {land_name} Germany 2026 Land-level jurisdiction pack. Holds no rates/slabs "
                    "of its own by design — see module docstring."
                ),
            ),
            actor_id=maker.id,
        )
        # JurisdictionPackUpsert has no parentPackId field (never wired up
        # platform-wide, including for the UK Scotland pack this mirrors) —
        # set directly rather than extending a shared schema/service
        # function for this one task, matching "preserve existing
        # architecture, don't redesign it to make this task easier."
        pack.parent_pack_id = federal_pack.id
        db.commit()
        db.refresh(pack)
        print(f"[{SCRIPT_NAME}] {land_name}: created {pack.pack_id} (id={pack.id}, parent_pack_id={pack.parent_pack_id}).")
    else:
        pack = existing
        if pack.parent_pack_id != federal_pack.id:
            pack.parent_pack_id = federal_pack.id
            db.commit()
            db.refresh(pack)
        print(f"[{SCRIPT_NAME}] {land_name}: {pack.pack_id} already exists (id={pack.id}, status={pack.status}).")

    if pack.status == "Draft":
        pack = service.set_jurisdiction_pack_approver(db, pack.id, actor_id=checker.id)
        print(f"[{SCRIPT_NAME}] {land_name}: approved -> status={pack.status}.")
    if pack.status == "Approved":
        pack = service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=checker.id)
        print(f"[{SCRIPT_NAME}] {land_name}: activated -> status={pack.status}.")

    return {"land_code": land_code, "land_name": land_name, "pack_id": pack.pack_id, "id": pack.id, "status": pack.status}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args()

    import os

    target = describe_target()
    local = is_local_database()
    print(f"[{SCRIPT_NAME}] Configured database target: {target or '<not configured>'}")
    print(f"[{SCRIPT_NAME}] ENVIRONMENT={os.environ.get('ENVIRONMENT', '<unset>')}")
    print(f"[{SCRIPT_NAME}] is_local_database() = {local}")
    assert_local_database(SCRIPT_NAME)

    from app.database import SessionLocal, initialize_database
    from app.modules.payroll import service
    from app.modules.payroll.schemas import JurisdictionPackUpsert
    from app.modules.payroll.engine import tax_resolver

    initialize_database()
    db = SessionLocal()
    try:
        maker, checker = resolve_and_authorize_maker_checker(db, args.maker_id, args.checker_id)
        print(f"[{SCRIPT_NAME}] maker={maker.id} ({maker.email}), checker={checker.id} ({checker.email}) "
              "— both verified active Super Admin users.")

        federal_pack = _resolve_federal_pack(db, args.federal_pack_id)
        print(f"[{SCRIPT_NAME}] Federal pack: {federal_pack.pack_id} (id={federal_pack.id}, status={federal_pack.status}).")

        results = []
        for land_code, land_name in GERMAN_LAENDER:
            result = _seed_one_land(db, service, JurisdictionPackUpsert, land_code, land_name, federal_pack, maker, checker)
            # Prove centralization, not just record existence: a Land pack
            # must never win over the federal pack for real tax/slab
            # resolution (Phase 5's "federal calculation stays centralized"
            # requirement) — verified live here via the exact resolver the
            # rest of the platform already uses, not a bespoke check.
            resolved = tax_resolver.find_active_tax_pack(db, "DE", state=land_code, as_of=date(2026, 6, 1))
            result["resolves_to_federal"] = bool(resolved and resolved.id == federal_pack.id)
            result["ok"] = result["status"] == "Active" and result["resolves_to_federal"]
            results.append(result)

        print("\nGermany 2026 jurisdiction readiness (Länder)")
        print("-" * 44)
        print(f"\nFederal configuration: {'PASS' if federal_pack.status == 'Active' else 'FAIL'}\n")
        for r in results:
            print(f"{r['land_name']:<24}{'PASS' if r['ok'] else 'FAIL'}")
        ready = sum(1 for r in results if r["ok"])
        print(f"\nTotal Länder: {len(results)}")
        print(f"Ready: {ready}")
        print(f"Failed: {len(results) - ready}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
