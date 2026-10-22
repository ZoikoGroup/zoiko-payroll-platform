"""
scripts/seed_netherlands_canonical_packs.py
-------------------------------------------
Seeds the canonical (organization_id IS NULL) Netherlands content as DRAFT:
one NL-PAYROLL-2026 tax JurisdictionPack with every scalar parameter, every
minimum-wage row, every VCR period-maximum row, every WKR band and both
company-car addition rows from engine/countries/netherlands_content.py, a
NL-PAYROLL-2026-07 change-watch pack (the 1 Jul 2026 minimum-wage step — no
rows yet, a statutory-review anchor), plus the Netherlands'
jurisdiction_service_registry row as PLANNED.

Source: ZP-NL-ENG-001 v1.0 — the implementation specification. Every value is
traceable to SOURCE_REFERENCES S1–S20 in netherlands_content.py. String
scalars (WHITE, 1/3) live in ContributionRate.text_value, never flat_amount.

Governance: nothing is ever set Active here, and the registry row is created
only when missing (an existing row is never changed). Re-running refuses to
touch a pack that has left Draft; a Draft pack's rows are replaced wholesale
from the content, so an unchanged re-run produces the same rows.

Strict guard: the Netherlands has not passed gate G1 (spec §19), so this
script refuses to run unless BOTH (a) ZOIKO_ALLOW_NONLOCAL_DB_WRITES=
I_UNDERSTAND is set AND (b) the target database URL has been printed and
confirmed interactively (type CONFIRM). A non-interactive run is refused.

Usage:
    python -m scripts.seed_netherlands_canonical_packs
"""
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database  # noqa: E402
from app.modules.payroll.engine.countries.netherlands_content import (  # noqa: E402
    NL_2026, NL_2026_07, NL_CAR_ADDITION_BANDS, NL_CAR_ADDITION_RULE, NL_MIN_WAGE_RATES,
    NL_MIN_WAGE_RULE, NL_PARAMETER_KEYS, NL_PERIOD_MAX_RULE, NL_PERIOD_MAXIMA, NL_SCALAR_CONTENT,
    NL_WKR_BAND_RULE, NL_WKR_BANDS, SOURCE_REFERENCES,
)
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab  # noqa: E402
from scripts._local_db_guard import describe_target, is_local_database  # noqa: E402

CODE = "NL"
CURRENCY = "EUR"
SPEC = "ZP-NL-ENG-001 v1.0"
AUTHORITY = "Belastingdienst (SBR / Digipoort)"
_OVERRIDE_ENV = "ZOIKO_ALLOW_NONLOCAL_DB_WRITES"
_OVERRIDE_VALUE = "I_UNDERSTAND"

MAIN_PACK_ID = NL_2026[0]
CHANGE_WATCH_PACK_ID = NL_2026_07[0]


def _dec(value):
    return Decimal(str(value)) if value is not None else None


def _pct_display(value):
    return f"{value.normalize():f}%" if value is not None else "—"


def _ensure_service_registry_row(db) -> str:
    """Netherlands' jurisdiction_service_registry row, PLANNED, created only
    when missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == CODE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=CODE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def _upsert_pack(db, *, pack_id, effective_from, effective_to, tax_year, compliance_category,
                 change_summary, source_references) -> JurisdictionPack:
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise SystemExit(f"{pack_id} v1.0 is {pack.status!r}, not Draft — refusing to rewrite "
                         "a pack that has entered review/approval. Create a new version from Super Admin instead.")
    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=CODE, version="1.0")
        db.add(pack)
    pack.jurisdiction_state = None
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from = effective_from
    pack.effective_to = effective_to
    pack.tax_year = tax_year
    pack.currency = CURRENCY
    pack.regulatory_authority = AUTHORITY
    pack.compliance_category = compliance_category
    pack.compliance_owner = "Super Admin — Netherlands build"
    pack.change_summary = change_summary
    pack.source_references = source_references
    db.flush()
    return pack


def _add_rate(db, pack, sort_order, key, label, *, employee_rate_pct=None,
              employer_rate_pct=None, flat_amount=None, text_value=None):
    if key not in NL_PARAMETER_KEYS:
        raise SystemExit(f"{key} is not in engine NL_PARAMETER_KEYS — catalog drift")
    if len(label) > 100:
        raise SystemExit(f"ContributionRate label longer than 100 characters: {label!r}")
    er, ee, flat = _dec(employer_rate_pct), _dec(employee_rate_pct), _dec(flat_amount)
    shown = str(flat) if flat is not None else (text_value if text_value is not None else None)
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        jurisdiction_state=None,
        component_key=key, label=label,
        employee_share=_pct_display(ee) if ee is not None else (shown or "—"),
        employer_share=_pct_display(er) if er is not None else "—",
        total=(_pct_display(er if er is not None else ee) if (er is not None or ee is not None) else (shown or "—")),
        employer_rate_pct=er, employee_rate_pct=ee, flat_amount=flat, text_value=text_value,
        sort_order=sort_order,
    ))


def _add_slab(db, pack, sort_order, *, rule_type, rate_label, tax_formula, rate_pct,
              filing_status=None, min_amount="0", max_amount=None, flat_amount=None,
              effective_from=None, effective_to=None):
    if len(rate_label) > 150:
        raise SystemExit(f"TaxSlab rate_label longer than 150 characters: {rate_label!r}")
    db.add(TaxSlab(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        jurisdiction_state=None,
        rule_type=rule_type, filing_status=filing_status,
        min_amount=_dec(min_amount), max_amount=_dec(max_amount), rate_pct=_dec(rate_pct),
        flat_amount=_dec(flat_amount),
        rate_label=rate_label, tax_formula=tax_formula,
        effective_from=effective_from, effective_to=effective_to,
        sort_order=sort_order,
    ))


def _rewrite_pack_rows(db, pack):
    """A Draft pack's canonical rows are replaced wholesale from the content,
    so an unchanged re-run produces the same rows. Org-scoped rows
    (organization_id IS NOT NULL) are an organisation's overrides and are
    never deleted."""
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()


def _seed_main_pack(db) -> JurisdictionPack:
    pack = _upsert_pack(
        db, pack_id=MAIN_PACK_ID,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31), tax_year="2026",
        compliance_category="Loonheffing / premies volksverzekeringen / werknemersverzekeringen / Zvw / WKR",
        change_summary="v1.0 — ZP-NL-ENG-001 v1.0: 2026 reference Box 1 brackets (35.75/37.56/49.50) and "
                       "tax credits (general 3,115; employment 5,685), AWf 2.74/7.74, Aof 6.27/7.63, Wko 0.50, "
                       "Zvw 6.10 employer / 4.85 employee, WKR free space 2.00/1.18 at 400,000 with an 80% excess "
                       "levy, the 1 Jul 2026 statutory hourly minimum wage by age, the maximum contribution wage "
                       "(79,409/yr; 6,617.41/mo) and the expat 30% facility (48,013 / 36,497; WNT cap 262,000; "
                       "max 78,600). Every value needs_g1 — Draft pending the gate G1 statutory review.",
        source_references=_source_references(),
    )
    _rewrite_pack_rows(db, pack)

    order = 0
    for key, label, ee, er, flat, text, _source, _g1 in NL_SCALAR_CONTENT:
        order += 1
        _add_rate(db, pack, order, key, label,
                  employee_rate_pct=ee, employer_rate_pct=er, flat_amount=flat, text_value=text)

    for cohort, amount, eff_from, eff_to, _source, _g1 in NL_MIN_WAGE_RATES:
        order += 1
        label = f"Statutory minimum wage — {cohort.replace('_', ' ').lower()} (hourly)"
        _add_slab(db, pack, order, rule_type=NL_MIN_WAGE_RULE, filing_status=cohort,
                  min_amount="0", max_amount=None, rate_pct="0", flat_amount=amount,
                  rate_label=f"€{Decimal(amount):.2f}/hour", tax_formula=label,
                  effective_from=eff_from, effective_to=eff_to)

    for period_code, amount, _source, _g1 in NL_PERIOD_MAXIMA:
        order += 1
        label = f"VCR maximum contribution wage — {period_code.lower()}"
        _add_slab(db, pack, order, rule_type=NL_PERIOD_MAX_RULE, filing_status=period_code,
                  min_amount="0", max_amount=None, rate_pct="0", flat_amount=amount,
                  rate_label=f"€{Decimal(amount):.2f}", tax_formula=label)

    for kind, lo, hi, rate, _source, _g1 in NL_WKR_BANDS:
        order += 1
        band = "free space" if kind == "FREE_SPACE" else "final levy on the excess"
        label = f"WKR — {band}"
        _add_slab(db, pack, order, rule_type=NL_WKR_BAND_RULE, filing_status=kind,
                  min_amount=lo, max_amount=hi, rate_pct=rate,
                  rate_label=f"{Decimal(rate):.2f}%", tax_formula=label)

    for car_class, rate, eff_from, eff_to, _source, _g1 in NL_CAR_ADDITION_BANDS:
        order += 1
        label = f"Company-car addition — {car_class.replace('_', ' ').lower()} (bijtelling)"
        _add_slab(db, pack, order, rule_type=NL_CAR_ADDITION_RULE, filing_status=car_class,
                  min_amount="0", max_amount=None, rate_pct=rate,
                  rate_label=f"{Decimal(rate):.2f}%", tax_formula=label,
                  effective_from=eff_from, effective_to=eff_to)

    return pack


def _seed_change_watch_pack(db) -> JurisdictionPack:
    pack = _upsert_pack(
        db, pack_id=CHANGE_WATCH_PACK_ID,
        effective_from=date(2026, 7, 1), effective_to=date(2026, 12, 31), tax_year="2026-07",
        compliance_category="Minimum wage (1 July 2026 step) / change watch",
        change_summary="v1.0 — change-watch pack: the 1 Jul 2026 statutory hourly minimum-wage step is modelled "
                       "as effective-dated rows inside NL-PAYROLL-2026 (this anchor records the review window for "
                       "any further mid-2026 statutory restatement — no rows yet).",
        source_references=_source_references(),
    )
    _rewrite_pack_rows(db, pack)
    return pack


def _source_references() -> str:
    return f"{SPEC}; " + "; ".join(f"[{code}] {title}" for code, title in SOURCE_REFERENCES)


def seed_netherlands(db) -> dict:
    from app.modules.payroll.service import record_tax_audit

    main = _seed_main_pack(db)
    change_watch = _seed_change_watch_pack(db)
    availability = _ensure_service_registry_row(db)

    for pack in (main, change_watch):
        rates = (db.query(ContributionRate)
                 .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                         ContributionRate.organization_id.is_(None)).count())
        slabs = (db.query(TaxSlab)
                 .filter(TaxSlab.jurisdiction_pack_id == pack.id,
                         TaxSlab.organization_id.is_(None)).count())
        record_tax_audit(
            db, actor_id=None, action="seed", entity_type="jurisdiction_pack", entity_id=pack.id,
            jurisdiction_pack_id=pack.id, tax_version=pack.version, legal_reference=SPEC,
            old_value=None, new_value={"status": pack.status, "contribution_rates": str(rates),
                                       "tax_slabs": str(slabs)},
            reason=f"Canonical Netherlands pack {pack.pack_id} v{pack.version} seeded from {SPEC} "
                   "(scripts/seed_netherlands_canonical_packs.py) — Draft, needs_g1.",
            auto_commit=False,
        )
    db.flush()
    return {"main": main, "change_watch": change_watch, "availability": availability}


def _require_confirmed_target() -> None:
    target = describe_target()
    print(f"[seed_netherlands_canonical_packs] TARGET DATABASE: {target or '<not configured>'}")
    if (os.environ.get(_OVERRIDE_ENV) or "").strip() != _OVERRIDE_VALUE:
        print(
            f"\n[seed_netherlands_canonical_packs] REFUSING - the Netherlands has not passed gate G1; a stray run "
            f"of this statutory WRITE script is worse than for other countries.\n"
            f"  Target: {target or '<not configured>'}\n\n"
            f"  Set {_OVERRIDE_ENV}={_OVERRIDE_VALUE} to proceed (this is stricter than assert_local_database - "
            f"required even for a local SQLite target).\n",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not is_local_database():
        print(
            f"[seed_netherlands_canonical_packs] WARNING: the target is NOT a local/isolated database "
            f"({target}). Confirm carefully below.", file=sys.stderr,
        )
    if not sys.stdin.isatty():
        print(
            "[seed_netherlands_canonical_packs] REFUSING - non-interactive run: there is no keyboard to confirm "
            "the printed target database. Re-run in an interactive terminal and type CONFIRM.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print("[seed_netherlands_canonical_packs] The target database is printed above. Type CONFIRM to proceed:")
    if sys.stdin.readline().strip() != "CONFIRM":
        print("[seed_netherlands_canonical_packs] Not confirmed - aborting.", file=sys.stderr)
        raise SystemExit(2)


def main() -> None:
    _require_confirmed_target()
    initialize_database()
    db = SessionLocal()
    try:
        out = seed_netherlands(db)
        db.commit()
        main_pack = out["main"]
        rates = (db.query(ContributionRate)
                 .filter(ContributionRate.jurisdiction_pack_id == main_pack.id).count())
        slabs = (db.query(TaxSlab)
                 .filter(TaxSlab.jurisdiction_pack_id == main_pack.id).count())
        print(f"Seeded {main_pack.pack_id} v{main_pack.version} as Draft "
              f"({rates} ContributionRate rows, {slabs} TaxSlab rows)")
        print(f"Seeded {out['change_watch'].pack_id} v{out['change_watch'].version} as Draft (0 rows, change-watch)")
        print(f"service availability={out['availability']}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
