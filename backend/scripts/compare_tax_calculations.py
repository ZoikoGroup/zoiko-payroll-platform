"""
scripts/compare_tax_calculations.py
------------------------------------
Milestone 2 verification gate (Global Payroll Tax Engine refactor): proves
that a payroll calculation fed by the new canonical (Super-Admin-owned,
resolver-sourced) tax configuration produces byte-identical PayrollResult
figures to today's live org-scoped-table path, before anything in the
calculation flow is switched over.

Non-destructive: creates a SCRATCH JurisdictionPack + canonical
ContributionRate/TaxSlab rows that mirror one real org's current values,
runs both paths, diffs every PayrollResult field, then deletes the scratch
rows it created. The org's own live rows are never modified.

Usage:
    python -m scripts.compare_tax_calculations [organization_id] [country]
"""

import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.modules.payroll.models import ContributionRate, TaxSlab, JurisdictionPack
from app.modules.payroll.service import get_contribution_rates, get_tax_slabs, _normalize_country
from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee
from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration


def run(organization_id: int, country: str):
    country = _normalize_country(country)
    db = SessionLocal()
    scratch_pack = None
    scratch_rows = []
    try:
        old_rates = get_contribution_rates(db, organization_id, country=country)
        old_slabs = get_tax_slabs(db, organization_id, country=country)
        old_rate_map = {r.component_key: r for r in old_rates}
        print(f"Org {organization_id} / {country}: live rows -> {len(old_rates)} contribution rate(s), {len(old_slabs)} tax slab(s)")

        # Build a scratch canonical pack that mirrors the org's current values exactly.
        scratch_pack = JurisdictionPack(
            pack_id=f"COMPARE-TEST-{country}", jurisdiction_country=country, jurisdiction_state=None,
            pack_type="tax", version="COMPARE-TEST", status="Active",
        )
        db.add(scratch_pack)
        db.commit()
        db.refresh(scratch_pack)

        for r in old_rates:
            row = ContributionRate(
                organization_id=None, jurisdiction_country=country, jurisdiction_pack_id=scratch_pack.id,
                component_key=r.component_key, label=r.label, employee_share=r.employee_share,
                employer_share=r.employer_share, total=r.total, employee_rate_pct=r.employee_rate_pct,
                employer_rate_pct=r.employer_rate_pct, flat_amount=r.flat_amount, sort_order=r.sort_order,
            )
            db.add(row)
            scratch_rows.append(row)
        for s in old_slabs:
            row = TaxSlab(
                organization_id=None, jurisdiction_country=country, jurisdiction_pack_id=scratch_pack.id,
                min_amount=s.min_amount, max_amount=s.max_amount, rate_pct=s.rate_pct,
                rate_label=s.rate_label, tax_formula=s.tax_formula, sort_order=s.sort_order,
                rule_type=s.rule_type or "MARGINAL_RATE",
            )
            db.add(row)
            scratch_rows.append(row)
        db.commit()

        canon_rates, canon_slabs, pack = resolve_tax_configuration(db, country, payroll_date=None)
        assert pack is not None and pack.id == scratch_pack.id, "resolver did not find the scratch pack"
        new_rate_map = {r.component_key: r for r in canon_rates}
        print(f"Resolver -> {len(canon_rates)} contribution rate(s), {len(canon_slabs)} tax slab(s) from pack {pack.pack_id} v{pack.version}")

        test_cases = [
            ("low income",  Decimal("20000")),
            ("mid income",  Decimal("60000")),
            ("high income", Decimal("250000")),
        ]

        any_mismatch = False
        for label, gross in test_cases:
            basic = (gross * Decimal("0.5")).quantize(Decimal("0.01"))
            hra = (gross * Decimal("0.2")).quantize(Decimal("0.01"))

            old_ctx = build_context_from_employee(
                None, gross=gross, basic=basic, hra=hra, country=country,
                rate_map=old_rate_map, slabs=old_slabs,
            )
            new_ctx = build_context_from_employee(
                None, gross=gross, basic=basic, hra=hra, country=country,
                rate_map=new_rate_map, slabs=canon_slabs,
            )
            old_result = calculate_payroll(old_ctx, "standard")
            new_result = calculate_payroll(new_ctx, "standard")

            diffs = []
            for field_name in old_result.__dataclass_fields__:
                ov, nv = getattr(old_result, field_name), getattr(new_result, field_name)
                if ov != nv:
                    diffs.append((field_name, ov, nv))

            status = "MATCH" if not diffs else "MISMATCH"
            print(f"  [{status}] {label} (gross={gross}): net_pay old={old_result.net_pay} new={new_result.net_pay}")
            if diffs:
                any_mismatch = True
                for field_name, ov, nv in diffs:
                    print(f"      {field_name}: old={ov} new={nv}")

        print("RESULT:", "ALL MATCH — safe to proceed" if not any_mismatch else "MISMATCH FOUND — do not proceed")
        return not any_mismatch
    finally:
        # Clean up scratch data — org's own live rows were never touched.
        # Child rows (FK'd to the pack) must be gone before the pack itself.
        for row in scratch_rows:
            db.delete(row)
        db.commit()
        if scratch_pack is not None:
            db.query(JurisdictionPack).filter(JurisdictionPack.id == scratch_pack.id).delete()
            db.commit()
        db.close()


if __name__ == "__main__":
    org_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    country = sys.argv[2] if len(sys.argv) > 2 else "IN"
    ok = run(org_id, country)
    sys.exit(0 if ok else 1)
