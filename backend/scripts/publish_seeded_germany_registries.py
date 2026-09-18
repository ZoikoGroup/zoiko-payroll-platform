"""
scripts/publish_seeded_germany_registries.py
----------------------------------------------
Walks every DRAFT Germany statutory-registry row created by
scripts/seed_germany_2026_registries.py through the REAL governance
lifecycle (DRAFT -> VERIFIED -> APPROVED -> PUBLISHED) using the actual
service-layer maker-checker functions — never by setting `row.status`
directly. This is the exact call sequence already proven in
tests/test_germany_e2e_payroll_scenario.py and
tests/test_germany_minijob_midijob_parameters.py:

    row = service.create_X_record(db, XCreate(...), actor_id=maker)
    row = service.set_X_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_X_approver(db, row.id, actor_id=checker)
    row = service.set_X_status(db, row.id, "PUBLISHED", actor_id=checker)

`set_X_status(..., "PUBLISHED", ...)` itself enforces (server-side, not
duplicated here):
  - a distinct approver (approved_by_id != updated_by_id), and
  - a non-null authority_source_id (a real SourceArtifact evidence link).

Nothing in this script bypasses either check — a row missing evidence or
never routed through set_X_approver will raise BadRequestException here,
exactly as it would through the real Super Admin UI/API.

This script is purely additive: it never invents a statutory value, never
self-approves in a way the real API wouldn't allow, and never touches
`backend/.env`. It reads whichever PAYROLL_DATABASE_URL is already set in
the process environment — the same convention as every other script in
this directory. Run it against an isolated database only, immediately
after seed_germany_2026_registries.py, with a real distinct maker/checker
actor id pair.

PHASE 8DF CHANGE FROM THE NIKHIL-BRANCH VERSION THIS WAS PORTED FROM:
the earlier version hardcoded maker/checker actor ids as 901/902,
documented there as "obviously-fake" placeholders. This version instead
REQUIRES --maker-id/--checker-id on the command line and validates both
resolve to real, active `User` rows with role=super_admin (see
scripts/_actor_authorization.py) before doing anything else — it refuses
to run rather than silently falling back to any placeholder. No other
logic was changed from the validated nikhil version.

Two responsibilities:

1. publish_all_draft_registry_rows(db, maker_id, checker_id) — walks every
   DRAFT row already created by seed_germany_2026_registries.py (Contribution
   Ceilings, PV Configuration, Health Funds, U1 Tariffs, Earning Taxability
   Rules, Overtime Premium Categories, Overtime Grundlohn Caps, Church Tax
   Exceptions) to PUBLISHED.

2. migrate_and_publish_minijob_midijob_parameters(db, maker_id, checker_id) —
   seed_germany_2026_registries.py does NOT seed GermanyMinijobMidijobParameter
   at all (confirmed by reading that model's own introducing migration
   docstring: zero seed data anywhere, by design). This creates one row per
   REAL existing hardcoded constant in app/modules/payroll/hardcoded_defaults.py
   (cited by exact constant name below), then publishes each — never
   inventing, rounding, or guessing a value. The 16 `church_tax_rate_de_*`
   parameter codes this table's own vocabulary reserves are DELIBERATELY
   SKIPPED: their real source is CHURCH_TAX_LAND_RATES in
   engine/jurisdictions/germany/pap/core.py, not hardcoded_defaults.py, and
   the general Church Tax rate is this project's own documented sanctioned
   hardcoded-constant exception (not a DB registry this task's Step 4 asked
   to migrate) — reported below as "not migrated — out of scope", not
   silently omitted.

Usage (against whichever PAYROLL_DATABASE_URL is configured in the
environment — never invoked automatically, never run against a shared/
remote database by this phase):

    python -m scripts.publish_seeded_germany_registries --maker-id 12 --checker-id 34
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database import SessionLocal, initialize_database

from scripts._local_db_guard import assert_local_database
from scripts._actor_authorization import resolve_and_authorize_maker_checker
from app.modules.payroll import service
from app.modules.payroll.models import (
    GermanyChurchTaxException, GermanyContributionCeiling, GermanyEarningTaxabilityRule,
    GermanyHealthFund, GermanyHealthFundU1Tariff, GermanyMinijobMidijobParameter,
    GermanyOvertimeGrundlohnCap, GermanyOvertimePremiumCategory, GermanyPvConfiguration,
    SourceArtifact,
)
from app.modules.payroll.schemas import GermanyMinijobMidijobParameterCreate


# ── Generic DRAFT -> PUBLISHED walker ───────────────────────────────────

def _walk_to_published(db: Session, row_id: int, set_status_fn, set_approver_fn, maker_id: int, checker_id: int):
    """Applies the real governed sequence to one row already sitting in
    DRAFT. Returns the final PUBLISHED row. Raises whatever
    BadRequestException the real service layer would raise (e.g. missing
    authority_source_id) — never swallowed, since a row that can't
    legitimately publish must surface that, not be silently skipped."""
    row = set_status_fn(db, row_id, "VERIFIED", actor_id=maker_id)
    row = set_approver_fn(db, row.id, actor_id=checker_id)
    return set_status_fn(db, row.id, "PUBLISHED", actor_id=checker_id)


# (model, list_all_query_attr_for_DRAFT, set_status_fn, set_approver_fn, human_label)
_REGISTRY_WALK_PLAN = [
    (GermanyContributionCeiling, service.set_contribution_ceiling_status,
     service.set_contribution_ceiling_approver, "contribution_ceilings"),
    (GermanyPvConfiguration, service.set_pv_configuration_status,
     service.set_pv_configuration_approver, "pv_configurations"),
    (GermanyHealthFund, service.set_health_fund_status,
     service.set_health_fund_approver, "health_funds"),
    (GermanyHealthFundU1Tariff, service.set_u1_tariff_status,
     service.set_u1_tariff_approver, "u1_tariffs"),
    (GermanyEarningTaxabilityRule, service.set_earning_taxability_rule_status,
     service.set_earning_taxability_rule_approver, "earning_taxability_rules"),
    (GermanyOvertimePremiumCategory, service.set_overtime_premium_category_status,
     service.set_overtime_premium_category_approver, "overtime_premium_categories"),
    (GermanyOvertimeGrundlohnCap, service.set_overtime_grundlohn_cap_status,
     service.set_overtime_grundlohn_cap_approver, "overtime_grundlohn_caps"),
    (GermanyChurchTaxException, service.set_germany_church_tax_exception_status,
     service.set_germany_church_tax_exception_approver, "church_tax_exceptions"),
]


def publish_all_draft_registry_rows(db: Session, maker_id: int, checker_id: int) -> dict:
    """Walks every currently-DRAFT row of every registry above to
    PUBLISHED via the real governed sequence. Returns
    {registry_label: {"published": [ids], "already_non_draft": count}}."""
    results = {}
    for model, set_status_fn, set_approver_fn, label in _REGISTRY_WALK_PLAN:
        draft_rows = db.query(model).filter(model.status == "DRAFT").all()
        published_ids = []
        for row in draft_rows:
            published = _walk_to_published(db, row.id, set_status_fn, set_approver_fn, maker_id, checker_id)
            published_ids.append(published.id)
        results[label] = {"published_ids": published_ids, "published_count": len(published_ids)}
    return results


# ── Minijob/Midijob parameter migration (Step 4) ────────────────────────
# Every (value, value_type) pair below is a verbatim transcription of the
# named constant in app/modules/payroll/hardcoded_defaults.py — cited by
# exact name so it is traceable line-for-line. None invented, rounded, or
# guessed. effective_from=2026-01-01 matches every other Germany 2026
# registry row seeded this phase.
#
# (parameter_code, value, value_type, label, hardcoded_defaults.py constant cited)
_MINIJOB_MIDIJOB_MIGRATION_PLAN = [
    ("minijob_upper_threshold", Decimal("603.00"), "EUR_THRESHOLD",
     "Minijob upper monthly earnings threshold", "_DE_MINIJOB_UPPER_THRESHOLD"),
    ("midijob_upper_threshold", Decimal("2000.00"), "EUR_THRESHOLD",
     "Midijob upper monthly earnings threshold", "_DE_MIDIJOB_UPPER_THRESHOLD"),
    ("minijob_employer_health_rate", Decimal("13"), "PERCENTAGE",
     "Minijob employer flat health contribution rate", "_DE_MINIJOB_EMPLOYER_HEALTH_RATE"),
    ("minijob_employer_pension_rate", Decimal("15"), "PERCENTAGE",
     "Minijob employer flat pension contribution rate", "_DE_MINIJOB_EMPLOYER_PENSION_RATE"),
    ("minijob_u1_rate", Decimal("0.80"), "PERCENTAGE",
     "Minijob U1 (sickness reimbursement) levy rate", "_DE_MINIJOB_U1_RATE"),
    ("minijob_u2_rate", Decimal("0.22"), "PERCENTAGE",
     "Minijob U2 (maternity) levy rate", "_DE_MINIJOB_U2_RATE"),
    ("minijob_u3_rate", Decimal("0.15"), "PERCENTAGE",
     "Minijob U3 (Insolvenzgeldumlage) levy rate", "_DE_MINIJOB_U3_RATE"),
    ("minijob_employee_pension_topup_rate", Decimal("3.60"), "PERCENTAGE",
     "Minijob employee pension top-up rate", "_DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE"),
    ("minijob_flat_tax_rate", Decimal("2"), "PERCENTAGE",
     "Minijob flat Pauschsteuer rate", "_DE_MINIJOB_FLAT_TAX_RATE"),
    ("midijob_total_base_multiplier", Decimal("1.1459372226"), "COEFFICIENT_MULTIPLIER",
     "Midijob total contribution-base formula multiplier", "_DE_MIDIJOB_TOTAL_BASE_MULTIPLIER"),
    ("midijob_total_base_subtrahend", Decimal("291.8744452399"), "COEFFICIENT_SUBTRAHEND",
     "Midijob total contribution-base formula subtrahend", "_DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND"),
    ("midijob_employee_base_multiplier", Decimal("1.43163922691"), "COEFFICIENT_MULTIPLIER",
     "Midijob employee contribution-base formula multiplier", "_DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER"),
    ("midijob_employee_base_subtrahend", Decimal("863.2784538207"), "COEFFICIENT_SUBTRAHEND",
     "Midijob employee contribution-base formula subtrahend", "_DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND"),
    ("midijob_pv_childless_surcharge_rate", Decimal("0.6"), "PERCENTAGE",
     "PV childless surcharge rate (SGB XI Section 55 Abs. 3)", "_DE_PV_CHILDLESS_SURCHARGE_RATE"),
    # Label kept short deliberately: GermanyMinijobMidijobParameter.label is
    # String(150), and this row's original label (plus the "(from
    # hardcoded_defaults.X)" suffix every migrated row gets below) came to
    # 176 chars — a real StringDataRightTruncation the first time this ran
    # against Postgres (SQLite doesn't enforce VARCHAR length). The
    # "distinct from minijob_u3_rate" clause this drops is not lost
    # information — it's already documented on _GERMANY_MINIJOB_MIDIJOB_
    # PARAMETER_CODES's own comment (Phase 8BL) — so trimming it here only
    # shortens display text, not the governed record.
    ("employer_insolvency_levy_rate", Decimal("0.15"), "PERCENTAGE",
     "Employer Insolvenzgeldumlage (U3) flat federal rate, applies to all "
     "Germany classifications", "_DE_INSOLVENCY_LEVY_RATE"),
]

# Deliberately NOT migrated — reported, not silently skipped. See module
# docstring: real source is CHURCH_TAX_LAND_RATES in
# engine/jurisdictions/germany/pap/core.py, not hardcoded_defaults.py.
_SKIPPED_CHURCH_TAX_LAND_CODES = [
    "church_tax_rate_de_bw", "church_tax_rate_de_by", "church_tax_rate_de_be",
    "church_tax_rate_de_bb", "church_tax_rate_de_hb", "church_tax_rate_de_hh",
    "church_tax_rate_de_he", "church_tax_rate_de_mv", "church_tax_rate_de_ni",
    "church_tax_rate_de_nw", "church_tax_rate_de_rp", "church_tax_rate_de_sl",
    "church_tax_rate_de_sn", "church_tax_rate_de_st", "church_tax_rate_de_sh",
    "church_tax_rate_de_th",
]


def _find_or_create_source(db: Session, agency: str, title: str, form_number=None, publication_date=None) -> SourceArtifact:
    """Idempotent — reuses an existing (agency, title) SourceArtifact if one
    already exists (e.g. from seed_germany_source_evidence.py), never
    duplicates. §4/§14 citations mirror the exact convention already
    established for §9/§10/§15 in that script (same agency name, same
    cover-page publication_date) — hardcoded_defaults.py's own comments
    cite "spec §4" (Minijob/Midijob) and "spec §14" (Insolvency levy)
    verbatim, so these are not new/invented citations."""
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        return existing
    row = SourceArtifact(agency=agency, title=title, form_number=form_number, publication_date=publication_date)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def migrate_and_publish_minijob_midijob_parameters(
    db: Session, maker_id: int, checker_id: int, jurisdiction_pack_id: "int | None" = None,
) -> dict:
    """Creates one GermanyMinijobMidijobParameter row per real hardcoded
    constant (see _MINIJOB_MIDIJOB_MIGRATION_PLAN) and publishes each via
    the real governed sequence. Idempotent: skips a parameter_code that
    already has a row covering 2026-01-01 (so re-running this script never
    creates a duplicate/overlapping version).

    Phase 8DL: `jurisdiction_pack_id`, when given, is stamped onto every
    newly-created row here too — unlike the other 8 registries (created by
    seed_germany_2026_registries.py, which already accepts this
    parameter), Minijob/Midijob rows are created HERE, by this script, so
    the linkage must be threaded through this specific call site."""
    spec_4_source = _find_or_create_source(
        db, "Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0",
        "§4 Minijob / Midijob Statutory Parameters (thresholds, flat rates, sliding-scale coefficients)",
        form_number="ZP-TAX-DE-2026-001 §4", publication_date=date(2026, 8, 21),
    )
    spec_14_source = _find_or_create_source(
        db, "Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0",
        "§14 Insolvency Levy (U3, Insolvenzgeldumlage) — flat federal rate for 2026",
        form_number="ZP-TAX-DE-2026-001 §14", publication_date=date(2026, 8, 21),
    )
    pv_childless_source = (
        db.query(SourceArtifact)
        .filter(
            SourceArtifact.agency == "Bundesministerium der Justiz (gesetze-im-internet.de)",
            SourceArtifact.title.contains("PV childless surcharge"),
        )
        .first()
    )

    def _source_for(parameter_code: str) -> "SourceArtifact | None":
        if parameter_code == "midijob_pv_childless_surcharge_rate":
            return pv_childless_source or spec_4_source
        if parameter_code == "employer_insolvency_levy_rate":
            return spec_14_source
        return spec_4_source

    created_and_published = []
    skipped_already_present = []
    for parameter_code, value, value_type, label, constant_name in _MINIJOB_MIDIJOB_MIGRATION_PLAN:
        existing = service.resolve_minijob_midijob_parameter(db, parameter_code, as_of=date(2026, 1, 1))
        if existing is not None:
            skipped_already_present.append(parameter_code)
            continue
        source = _source_for(parameter_code)
        row = service.create_minijob_midijob_parameter_record(
            db, GermanyMinijobMidijobParameterCreate(
                parameter_code=parameter_code, value=value, value_type=value_type,
                label=f"{label} (from hardcoded_defaults.{constant_name})",
                effective_from=date(2026, 1, 1), authority_source_id=source.id if source else None,
                jurisdiction_pack_id=jurisdiction_pack_id,
            ), actor_id=maker_id,
        )
        published = _walk_to_published(
            db, row.id, service.set_minijob_midijob_parameter_status,
            service.set_minijob_midijob_parameter_approver, maker_id, checker_id,
        )
        created_and_published.append({
            "parameter_code": parameter_code, "value": str(value), "id": published.id,
            "source_constant": constant_name,
        })

    return {
        "migrated": created_and_published,
        "skipped_already_present": skipped_already_present,
        "not_migrated_out_of_scope": _SKIPPED_CHURCH_TAX_LAND_CODES,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish seeded Germany 2026 statutory registry rows (DRAFT -> PUBLISHED) "
                    "and migrate Minijob/Midijob parameters, using real, distinct Super Admin actors.",
    )
    parser.add_argument("--maker-id", type=int, required=True, help="Real, active Super Admin user id (maker).")
    parser.add_argument("--checker-id", type=int, required=True, help="Real, active Super Admin user id (checker). Must differ from --maker-id.")
    parser.add_argument(
        "--jurisdiction-pack-id", type=int, required=True,
        help="Phase 8DL: REQUIRED — the payroll_jurisdiction_packs.id row (e.g. DE-PAYROLL-CY2026-V1) "
             "the newly-created Minijob/Midijob parameter rows will be linked to. The other 8 registries "
             "were already linked at seed time by seed_germany_2026_registries.py's own --jurisdiction-pack-id.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Phase 8DF: guard against a non-UTF8 Windows console crashing on a
    # non-ASCII character in printed evidence/registry text (see the
    # identical fix + rationale in seed_germany_source_evidence.py).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Phase 8BY: enforce the "isolated database only" instruction this
    # script's docstring already carried, BEFORE initialize_database()
    # creates an engine (and possibly create_all) against the target.
    assert_local_database("publish_seeded_germany_registries")
    initialize_database()
    db = SessionLocal()
    try:
        # Phase 8DF: no hardcoded placeholder actor ids — both must
        # resolve to real, active, distinct Super Admin users, or this
        # refuses to run before touching any registry row.
        maker, checker = resolve_and_authorize_maker_checker(db, args.maker_id, args.checker_id)
        print(f"[publish_seeded_germany_registries] maker={maker.id} ({maker.email}), "
              f"checker={checker.id} ({checker.email}) — both verified active Super Admin users.")

        from app.modules.payroll.models import JurisdictionPack
        pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == args.jurisdiction_pack_id).first()
        if pack is None:
            print(f"REFUSING TO RUN — no JurisdictionPack row exists with id={args.jurisdiction_pack_id}.", file=sys.stderr)
            raise SystemExit(2)
        print(f"[publish_seeded_germany_registries] Minijob/Midijob rows will link to pack: "
              f"{pack.pack_id} v{pack.version} (id={pack.id}).")

        registry_results = publish_all_draft_registry_rows(db, maker.id, checker.id)
        print("=== Registry DRAFT -> PUBLISHED walk ===")
        for label, result in registry_results.items():
            print(f"{label}: published {result['published_count']} row(s) -> ids {result['published_ids']}")

        minijob_results = migrate_and_publish_minijob_midijob_parameters(db, maker.id, checker.id, jurisdiction_pack_id=pack.id)
        print("\n=== Minijob/Midijob parameter migration ===")
        for entry in minijob_results["migrated"]:
            print(f"  created+published [{entry['id']}] {entry['parameter_code']} = {entry['value']} "
                  f"(from hardcoded_defaults.{entry['source_constant']})")
        if minijob_results["skipped_already_present"]:
            print(f"  already present (skipped): {minijob_results['skipped_already_present']}")
        print(f"  not migrated — out of scope ({len(minijob_results['not_migrated_out_of_scope'])} codes): "
              "church_tax_rate_de_* — real source is CHURCH_TAX_LAND_RATES in "
              "engine/jurisdictions/germany/pap/core.py, not hardcoded_defaults.py.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
