"""
scripts/populate_us_state_tax_v1.py
--------------------------------------
US state-level canonical seed data (ZP-TAX-US-2026-001), Phases 1 & 2 of
the state-level build-out plan:

  Phase 1 (_US_NO_INCOME_TAX_STATES): one Active, zero-TaxSlab
  JurisdictionPack per state confirmed to have no individual wage income
  tax (§4) — an evidence/audit record only. This does not change any
  calculated number: an unconfigured state already resolves
  state_income_tax=0 today (see us.py's own comment on ctx.state_slabs).

  Phase 2 (_US_STATE_TAX_RATES): Colorado & Kentucky's real withholding
  data — one flat-rate TaxSlab row plus a state_standard_deduction
  ContributionRate row (filing-status-tagged where the source specifies
  it). This DOES represent a real number for any employee with
  work_state="CO"/"KY" once _US_STATE_TAX_ENABLED_STATES (shared.py) adds
  that state — deliberately left OUT of that set by this script; enabling
  it is a separate, explicit step. Incremental build-out 2026-09-11
  (ZP-TAX-US-2026-001 §4 Matrix): AZ/IL/MA/MI/PA added with a complete
  literal flat percentage and allowance_by_filing_status={} (the document
  says None for every status), so no state_standard_deduction row is
  seeded for them.

  Phase 3 (_US_STATE_PROGRAMS): state-level statutory payroll programs
  (SDI/Paid Leave/TDI/Universal Paid Leave/WA Cares/NJ's 4-program
  family) — one ContributionRate row per program plus optional
  "<key>_wage_cap"/"<key>_annual_max" companion rows, read by us.py's
  generic per-state-program loop, gated by
  _US_STATE_PROGRAM_ENABLED_STATES (also left OUT of that set here).

  Phase 3C (_US_STATE_HEADCOUNT_PROGRAMS / _US_DE_PAID_LEAVE):
  headcount-conditional programs (CO FAMLI, ME PFML, WA PFML, DE Paid
  Leave's two tiers, MA PFML added 2026-09-11) — same as Phase 3 but with
  an extra "<key>_employer_headcount_min"/"_max" companion row gating the
  EMPLOYER side only, plus an optional "<key>_wage_cap" companion row
  (CO FAMLI and DE Paid Leave both carry the document's $184,500 cap).
  This script seeds the CANONICAL rate/threshold data only —
  it cannot seed any real employer's actual covered_employee_count (a
  genuinely tenant-specific fact, entered per org via the SUI Employer
  Rates screen), so every employer's headcount-gated employer share
  computes as $0 until that org's own Tax Ops enters it.

Deliberately a SEPARATE script from populate_canonical_tax_v1.py: that
script only ever seeds the country-level (jurisdiction_state IS NULL)
pack and upserts ContributionRate rows by component_key alone (no
jurisdiction_state in its matching filter) — feeding it state-scoped data
would attach rows to the wrong pack or let two states' same-keyed rows
overwrite each other. See hardcoded_defaults.py's own comment on this.

Idempotent: safe to re-run (updates existing rows by
(jurisdiction_state, component_key) / (jurisdiction_state, sort_order)
rather than duplicating).

Usage:
    python -m scripts.populate_us_state_tax_v1
"""

import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack, SourceArtifact, LocalityDataset, LocalityRate
from app.modules.payroll.service import record_tax_audit
from app.modules.payroll.hardcoded_defaults import (
    _US_NO_INCOME_TAX_STATES, _US_STATE_TAX_RATES, _US_STATE_PROGRAMS, _US_LOCALITY_DATA,
    _US_STATE_HEADCOUNT_PROGRAMS, _US_DE_PAID_LEAVE,
)

COUNTRY = "US"
TAX_YEAR = "2026"
CURRENCY = "USD"


def _get_or_create_pack(db, state: str, change_summary: str) -> JurisdictionPack:
    pack = (
        db.query(JurisdictionPack)
        .filter(
            JurisdictionPack.pack_type == "tax",
            JurisdictionPack.jurisdiction_country == COUNTRY,
            JurisdictionPack.jurisdiction_state == state,
        )
        .first()
    )
    if pack is None:
        pack = JurisdictionPack(
            pack_id=f"US-{state}-2026-V1",
            jurisdiction_country=COUNTRY,
            jurisdiction_state=state,
            pack_type="tax",
            version="1.0",
            status="Active",
            tax_year=TAX_YEAR,
            currency=CURRENCY,
            regulatory_authority="ZP-TAX-US-2026-001",
            change_summary=change_summary,
        )
        db.add(pack)
        db.flush()
    else:
        pack.change_summary = change_summary
        if pack.status != "Active":
            pack.status = "Active"
    return pack


def _get_or_create_source(db, agency: str, title: str) -> SourceArtifact:
    existing = db.query(SourceArtifact).filter(SourceArtifact.agency == agency, SourceArtifact.title == title).first()
    if existing:
        return existing
    artifact = SourceArtifact(agency=agency, title=title)
    db.add(artifact)
    db.flush()
    return artifact


def _upsert_rate(db, state: str, component_key: str, pack_id: int, **fields) -> None:
    existing = (
        db.query(ContributionRate)
        .filter(
            ContributionRate.organization_id.is_(None),
            ContributionRate.jurisdiction_country == COUNTRY,
            ContributionRate.jurisdiction_state == state,
            ContributionRate.component_key == component_key,
            ContributionRate.filing_status.is_(fields.get("filing_status")),
        )
        .first()
    )
    row_fields = dict(fields, component_key=component_key, jurisdiction_pack_id=pack_id)
    if existing:
        for k, v in row_fields.items():
            setattr(existing, k, v)
    else:
        db.add(ContributionRate(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **row_fields))


def run():
    db = SessionLocal()
    try:
        no_tax_count = 0
        for state, agency in _US_NO_INCOME_TAX_STATES.items():
            pack = _get_or_create_pack(
                db, state,
                change_summary=f"No individual wage income tax (ZP-TAX-US-2026-001 §4) — {agency}.",
            )
            source = _get_or_create_source(db, agency, f"{state}: No individual wage income tax (2026)")
            pack.source_document_id = source.id
            no_tax_count += 1
        db.commit()
        print(f"Phase 1: {no_tax_count} no-income-tax state pack(s) created/updated.")

        for state, d in _US_STATE_TAX_RATES.items():
            pack = _get_or_create_pack(
                db, state,
                change_summary=f"State withholding per ZP-TAX-US-2026-001 §3.1/§4/Appendix A — {d['source_title']}.",
            )
            source = _get_or_create_source(db, d["agency"], d["source_title"])
            pack.source_document_id = source.id

            existing_slab = (
                db.query(TaxSlab)
                .filter(
                    TaxSlab.organization_id.is_(None),
                    TaxSlab.jurisdiction_country == COUNTRY,
                    TaxSlab.jurisdiction_state == state,
                    TaxSlab.sort_order == 1,
                )
                .first()
            )
            slab_fields = dict(
                min_amount=Decimal("0"), max_amount=None, rate_pct=d["rate_pct"],
                rate_label=f"{d['rate_pct']}%", tax_formula=f"Flat {d['rate_pct']}% after state standard deduction",
                rule_type="FLAT_RATE", sort_order=1, jurisdiction_pack_id=pack.id,
            )
            if existing_slab:
                for k, v in slab_fields.items():
                    setattr(existing_slab, k, v)
            else:
                db.add(TaxSlab(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **slab_fields))

            rate_count = 0
            for filing_status, amount in d["allowance_by_filing_status"].items():
                existing_rate = (
                    db.query(ContributionRate)
                    .filter(
                        ContributionRate.organization_id.is_(None),
                        ContributionRate.jurisdiction_country == COUNTRY,
                        ContributionRate.jurisdiction_state == state,
                        ContributionRate.component_key == "state_standard_deduction",
                        ContributionRate.filing_status == filing_status,
                    )
                    .first()
                )
                label = "State Standard Deduction" + (f" ({filing_status})" if filing_status else "")
                rate_fields = dict(
                    component_key="state_standard_deduction", label=label,
                    employee_share="—", employer_share="—", total=f"${amount:,.2f}",
                    flat_amount=amount, filing_status=filing_status, sort_order=1,
                    jurisdiction_pack_id=pack.id,
                )
                if existing_rate:
                    for k, v in rate_fields.items():
                        setattr(existing_rate, k, v)
                else:
                    db.add(ContributionRate(organization_id=None, jurisdiction_country=COUNTRY, jurisdiction_state=state, **rate_fields))
                rate_count += 1

            db.commit()
            record_tax_audit(
                db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                jurisdiction_pack_id=pack.id, tax_version=pack.version,
                reason="US state-level build-out (ZP-TAX-US-2026-001): canonical state withholding data",
                new_value={"taxSlabs": 1, "contributionRates": rate_count},
            )
            print(f"Phase 2: {state} -> pack {pack.pack_id} v{pack.version}, 1 tax slab, {rate_count} contribution rate row(s).")

        for state, programs in _US_STATE_PROGRAMS.items():
            source_titles = {d["source_title"] for d in programs.values()}
            pack = _get_or_create_pack(
                db, state,
                change_summary=(
                    f"State-level statutory payroll program(s) per ZP-TAX-US-2026-001 §5 — {'; '.join(sorted(source_titles))}."
                ),
            )
            row_count = 0
            for key, d in programs.items():
                source = _get_or_create_source(db, d["agency"], d["source_title"])
                if pack.source_document_id is None:
                    pack.source_document_id = source.id
                label = key.replace("_", " ").title()
                rate_desc = []
                if d["employee_rate_pct"] is not None:
                    rate_desc.append(f"{d['employee_rate_pct']}% employee")
                if d["employer_rate_pct"] is not None:
                    rate_desc.append(f"{d['employer_rate_pct']}% employer")
                _upsert_rate(
                    db, state, key, pack.id,
                    label=label, employee_share="—", employer_share="—", total=" + ".join(rate_desc),
                    employee_rate_pct=d["employee_rate_pct"], employer_rate_pct=d["employer_rate_pct"],
                    sort_order=1,
                )
                row_count += 1
                if d["wage_cap"] is not None:
                    _upsert_rate(
                        db, state, f"{key}_wage_cap", pack.id,
                        label=f"{label} — Taxable Wage Cap", employee_share="—", employer_share="—",
                        total=f"${d['wage_cap']:,.2f}", flat_amount=d["wage_cap"], sort_order=2,
                    )
                    row_count += 1
                if d["annual_max"] is not None:
                    _upsert_rate(
                        db, state, f"{key}_annual_max", pack.id,
                        label=f"{label} — Annual Dollar Maximum", employee_share="—", employer_share="—",
                        total=f"${d['annual_max']:,.2f}", flat_amount=d["annual_max"], sort_order=3,
                    )
                    row_count += 1
            db.commit()
            record_tax_audit(
                db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                jurisdiction_pack_id=pack.id, tax_version=pack.version,
                reason="US state-level build-out (ZP-TAX-US-2026-001): canonical state payroll program data",
                new_value={"contributionRates": row_count},
            )
            print(f"Phase 3: {state} -> pack {pack.pack_id} v{pack.version}, {row_count} contribution rate row(s) ({', '.join(programs.keys())}).")

        for state, programs in _US_STATE_HEADCOUNT_PROGRAMS.items():
            source_titles = {d["source_title"] for d in programs.values()}
            pack = _get_or_create_pack(
                db, state,
                change_summary=(
                    f"Headcount-conditional statutory payroll program(s) per ZP-TAX-US-2026-001 §5 — {'; '.join(sorted(source_titles))}."
                ),
            )
            row_count = 0
            for key, d in programs.items():
                source = _get_or_create_source(db, d["agency"], d["source_title"])
                if pack.source_document_id is None:
                    pack.source_document_id = source.id
                label = key.replace("_", " ").title()
                _upsert_rate(
                    db, state, key, pack.id,
                    label=label, employee_share="—", employer_share="—",
                    total=f"{d['employee_rate_pct']}% EE + {d['employer_rate_pct']}% ER at {d['employer_headcount_min']}+",
                    employee_rate_pct=d["employee_rate_pct"], employer_rate_pct=d["employer_rate_pct"], sort_order=1,
                )
                row_count += 1
                _upsert_rate(
                    db, state, f"{key}_employer_headcount_min", pack.id,
                    label=f"{label} — Employer Share Headcount Threshold", employee_share="—", employer_share="—",
                    total=f"{d['employer_headcount_min']} employees", flat_amount=Decimal(d["employer_headcount_min"]), sort_order=2,
                )
                row_count += 1
                if d.get("wage_cap") is not None:
                    _upsert_rate(
                        db, state, f"{key}_wage_cap", pack.id,
                        label=f"{label} — Taxable Wage Cap", employee_share="—", employer_share="—",
                        total=f"${d['wage_cap']:,.2f}", flat_amount=d["wage_cap"], sort_order=3,
                    )
                    row_count += 1
            db.commit()
            record_tax_audit(
                db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                jurisdiction_pack_id=pack.id, tax_version=pack.version,
                reason="US state-level build-out (ZP-TAX-US-2026-001): canonical headcount-conditional program data",
                new_value={"contributionRates": row_count},
            )
            print(f"Phase 3C: {state} -> pack {pack.pack_id} v{pack.version}, {row_count} contribution rate row(s) ({', '.join(programs.keys())}).")

        # Delaware Paid Leave: two tiers, one shared headcount fact (see
        # _US_DE_PAID_LEAVE's own comment and us.py's
        # _headcount_group_aliases — "paid_leave_parental" resolves to the
        # same EmployerTaxProfile.component_code="PAID_LEAVE" as "paid_leave").
        de = _US_DE_PAID_LEAVE
        de_pack = _get_or_create_pack(
            db, "DE",
            change_summary=f"Headcount-conditional statutory payroll program(s) per ZP-TAX-US-2026-001 §5 — {de['source_title']}.",
        )
        de_source = _get_or_create_source(db, de["agency"], de["source_title"])
        if de_pack.source_document_id is None:
            de_pack.source_document_id = de_source.id
        _upsert_rate(
            db, "DE", "paid_leave", de_pack.id,
            label="Paid Leave (Full Coverage)", employee_share="—", employer_share="—",
            total=f"{de['full_coverage_rate_pct']}% employer (at {de['full_coverage_min']}+ employees)",
            employee_rate_pct=None, employer_rate_pct=de["full_coverage_rate_pct"], sort_order=1,
        )
        _upsert_rate(
            db, "DE", "paid_leave_employer_headcount_min", de_pack.id,
            label="Paid Leave (Full Coverage) — Employer Share Headcount Threshold", employee_share="—", employer_share="—",
            total=f"{de['full_coverage_min']} employees", flat_amount=Decimal(de["full_coverage_min"]), sort_order=2,
        )
        _upsert_rate(
            db, "DE", "paid_leave_wage_cap", de_pack.id,
            label="Paid Leave (Full Coverage) — Taxable Wage Cap", employee_share="—", employer_share="—",
            total=f"${de['wage_cap']:,.2f}", flat_amount=de["wage_cap"], sort_order=3,
        )
        _upsert_rate(
            db, "DE", "paid_leave_parental", de_pack.id,
            label="Paid Leave (Parental Only)", employee_share="—", employer_share="—",
            total=f"{de['parental_only_rate_pct']}% employer (at {de['parental_only_min']}-{de['full_coverage_min'] - 1} employees)",
            employee_rate_pct=None, employer_rate_pct=de["parental_only_rate_pct"], sort_order=4,
        )
        _upsert_rate(
            db, "DE", "paid_leave_parental_employer_headcount_min", de_pack.id,
            label="Paid Leave (Parental Only) — Employer Share Headcount Threshold (Min)", employee_share="—", employer_share="—",
            total=f"{de['parental_only_min']} employees", flat_amount=Decimal(de["parental_only_min"]), sort_order=5,
        )
        _upsert_rate(
            db, "DE", "paid_leave_parental_employer_headcount_max", de_pack.id,
            label="Paid Leave (Parental Only) — Employer Share Headcount Threshold (Max, exclusive)", employee_share="—", employer_share="—",
            total=f"{de['full_coverage_min']} employees", flat_amount=Decimal(de["full_coverage_min"]), sort_order=6,
        )
        _upsert_rate(
            db, "DE", "paid_leave_parental_wage_cap", de_pack.id,
            label="Paid Leave (Parental Only) — Taxable Wage Cap", employee_share="—", employer_share="—",
            total=f"${de['wage_cap']:,.2f}", flat_amount=de["wage_cap"], sort_order=7,
        )
        db.commit()
        record_tax_audit(
            db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=de_pack.id,
            jurisdiction_pack_id=de_pack.id, tax_version=de_pack.version,
            reason="US state-level build-out (ZP-TAX-US-2026-001): Delaware Paid Leave two-tier data",
            new_value={"contributionRates": 7},
        )
        print(f"Phase 3C: DE -> pack {de_pack.pack_id} v{de_pack.version}, 7 contribution rate row(s) (paid_leave, paid_leave_parental).")

        for state, d in _US_LOCALITY_DATA.items():
            dataset = (
                db.query(LocalityDataset)
                .filter(LocalityDataset.jurisdiction_country == COUNTRY, LocalityDataset.jurisdiction_state == state)
                .first()
            )
            source = _get_or_create_source(db, d["agency"], d["source_title"])
            if dataset is None:
                dataset = LocalityDataset(
                    jurisdiction_country=COUNTRY, jurisdiction_state=state, version="1.0", status="Active",
                    source_document_id=source.id, effective_from=date(2026, 1, 1),
                )
                db.add(dataset)
                db.flush()
            else:
                dataset.source_document_id = source.id
                if dataset.status != "Active":
                    dataset.status = "Active"

            rate_count = 0
            for r in d["rates"]:
                existing_rate = (
                    db.query(LocalityRate)
                    .filter(LocalityRate.locality_dataset_id == dataset.id, LocalityRate.locality_code == r["locality_code"])
                    .first()
                )
                if existing_rate:
                    for k, v in r.items():
                        setattr(existing_rate, k, v)
                else:
                    db.add(LocalityRate(locality_dataset_id=dataset.id, **r))
                rate_count += 1
            db.commit()
            print(f"Phase 4: {state} -> locality dataset v{dataset.version} ({dataset.status}), {rate_count} locality rate row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
