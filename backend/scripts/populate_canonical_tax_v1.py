"""
scripts/populate_canonical_tax_v1.py
--------------------------------------
Milestone 3 (Global Payroll Tax Engine refactor): populates the CANONICAL
(Super-Admin-owned, organization_id IS NULL) ContributionRate/TaxSlab rows
for all 6 jurisdictions' existing "Version 1" tax packs, sourced from the
same _CONTRIBUTION_RATES_BY_COUNTRY/_TAX_SLABS_BY_COUNTRY dicts every org
has been lazily seeded from — i.e. this makes today's already-correct
default values canonical/government-owned instead of ambient Python
constants, without changing a single number.

Also adds the scalar tax PARAMETER rows (standard deduction, 87A rebate,
ESI wage ceiling, US SS wage base, US Medicare Additional threshold, UK
personal allowance/taper/NI thresholds) that engine/standard.py now reads
via rate_map with an identical-value fallback — populating them here makes
them Super-Admin-editable going forward while leaving today's numbers
unchanged.

Idempotent: safe to re-run (updates existing rows by component_key rather
than duplicating).

Usage:
    python -m scripts.populate_canonical_tax_v1
"""

import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack
from app.modules.payroll.service import _CONTRIBUTION_RATES_BY_COUNTRY, _TAX_SLABS_BY_COUNTRY, record_tax_audit

# component_key -> (flat_amount | None, employee_rate_pct | None, employer_rate_pct | None, label)
_PARAMETERS_BY_COUNTRY = {
    "IN": [
        ("standard_deduction", Decimal("75000"), None, None, "Standard Deduction (New Regime)"),
        ("rebate_87a_limit", Decimal("1200000"), None, None, "Section 87A Rebate — Taxable Income Limit"),
        ("rebate_87a_max", Decimal("60000"), None, None, "Section 87A Rebate — Maximum Rebate"),
        ("esi_wage_ceiling", Decimal("21000"), None, None, "ESI Applicability Wage Ceiling (Monthly)"),
    ],
    "US": [
        ("standard_deduction", Decimal("15000"), None, None, "Federal Standard Deduction (Single)"),
        ("ss_wage_base", Decimal("176100"), None, None, "Social Security Wage Base"),
        ("medicare_additional", None, Decimal("0.90"), None, "Additional Medicare Rate"),
        ("medicare_addl_thresh", Decimal("200000"), None, None, "Additional Medicare Threshold"),
    ],
    "UK": [
        ("personal_allowance", Decimal("12570"), None, None, "Personal Allowance"),
        ("pa_taper_threshold", Decimal("100000"), None, None, "Personal Allowance Taper Threshold"),
        ("ni_primary_thresh", Decimal("12570"), None, None, "NI Primary Threshold"),
        ("ni_upper_threshold", Decimal("50270"), None, None, "NI Upper Earnings Limit"),
        ("ni_upper_rate", None, Decimal("2.00"), None, "NI Upper Rate"),
    ],
    "AU": [],
    "DE": [],
    "CA": [],
}


def run():
    db = SessionLocal()
    try:
        packs = {p.jurisdiction_country: p for p in db.query(JurisdictionPack).filter(
            JurisdictionPack.pack_type == "tax", JurisdictionPack.jurisdiction_state.is_(None),
        ).all()}

        tax_years = {"IN": "2025-26", "US": "2025", "UK": "2025-26", "AU": "2025-26", "DE": "2025", "CA": "2025"}
        currencies = {"IN": "INR", "US": "USD", "UK": "GBP", "AU": "AUD", "DE": "EUR", "CA": "CAD"}

        for country, pack in packs.items():
            if pack.tax_year is None:
                pack.tax_year = tax_years.get(country)
            if pack.currency is None:
                pack.currency = currencies.get(country)
        db.commit()

        for country, pack in packs.items():
            rate_count = 0
            for d in _CONTRIBUTION_RATES_BY_COUNTRY.get(country, []):
                existing = db.query(ContributionRate).filter(
                    ContributionRate.organization_id.is_(None),
                    ContributionRate.jurisdiction_country == country,
                    ContributionRate.component_key == d["component_key"],
                ).first()
                fields = dict(d)
                fields["jurisdiction_pack_id"] = pack.id
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                else:
                    db.add(ContributionRate(organization_id=None, jurisdiction_country=country, **fields))
                rate_count += 1

            for key, flat_amount, emp_pct, empr_pct, label in _PARAMETERS_BY_COUNTRY.get(country, []):
                existing = db.query(ContributionRate).filter(
                    ContributionRate.organization_id.is_(None),
                    ContributionRate.jurisdiction_country == country,
                    ContributionRate.component_key == key,
                ).first()
                fields = dict(
                    component_key=key, label=label,
                    employee_share=str(emp_pct) + "%" if emp_pct is not None else "",
                    employer_share=str(empr_pct) + "%" if empr_pct is not None else "",
                    total="", employee_rate_pct=emp_pct, employer_rate_pct=empr_pct,
                    flat_amount=flat_amount, sort_order=100, jurisdiction_pack_id=pack.id,
                )
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                else:
                    db.add(ContributionRate(organization_id=None, jurisdiction_country=country, **fields))
                rate_count += 1

            slab_count = 0
            existing_slabs = db.query(TaxSlab).filter(
                TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_country == country,
            ).all()
            existing_by_sort = {s.sort_order: s for s in existing_slabs}
            for d in _TAX_SLABS_BY_COUNTRY.get(country, []):
                fields = dict(d)
                fields["jurisdiction_pack_id"] = pack.id
                existing = existing_by_sort.get(d["sort_order"])
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                else:
                    db.add(TaxSlab(organization_id=None, jurisdiction_country=country, **fields))
                slab_count += 1

            db.commit()
            record_tax_audit(
                db, actor_id=None, action="create", entity_type="jurisdiction_pack", entity_id=pack.id,
                jurisdiction_pack_id=pack.id, tax_version=pack.version,
                reason="Milestone 3: canonical rate/slab/parameter population from existing engine defaults",
                new_value={"contributionRates": rate_count, "taxSlabs": slab_count},
            )
            print(f"{country}: pack {pack.pack_id} v{pack.version} -> {rate_count} contribution rate row(s), {slab_count} tax slab(s)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
