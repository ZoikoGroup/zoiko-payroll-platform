"""
scripts/migrate_tax_hierarchy.py
-----------------------------------
One-time migration: populates the new generic jurisdiction/tax hierarchy
(app/modules/payroll/hierarchy/models.py) FROM the existing canonical
JurisdictionPack/ContributionRate/TaxSlab/CompanyComplianceDetails data.

Purely additive and safe to re-run: old tables are NEVER modified, deleted,
or read as anything but a source — every created row carries a
legacy_pack_id/legacy_component_key bridge back to what it came from, and
a JurisdictionPack already migrated (legacy_pack_id already present on a
TaxVersion) is skipped on a subsequent run rather than duplicated.

Running this script does NOT flip any organization's
tax_hierarchy_v2_enabled flag and does NOT change what any payroll
calculation actually uses — the old resolver (engine/tax_resolver.py)
keeps being the only one used by every org until that flag is explicitly
set for a specific org, one at a time, after its v2-resolved numbers are
validated against its own last real payroll run. This script only makes
data exist in the new tables; it does not turn anything on.

Only `pack_type="tax"` JurisdictionPack rows are migrated — "policy" packs
already have their own working override system (PayrollPolicy/
policy_defaults) and are explicitly out of scope for this submodule.

Defaults to a DRY RUN (prints exactly what it would create, writes
nothing). Pass --commit to actually persist.

Usage:
    python -m scripts.migrate_tax_hierarchy              # dry run
    python -m scripts.migrate_tax_hierarchy --commit      # actually writes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.core.jurisdiction import ALL_CODE_TO_COUNTRY_NAME
from app.modules.payroll.models import (
    JurisdictionPack, ContributionRate, TaxSlab, CompanyComplianceDetails,
)
from app.modules.payroll.hierarchy.models import (
    Country, JurisdictionLevel, Jurisdiction, Tax, TaxVersion, TaxRule,
    TaxRuleSlab, TaxRuleRate, TaxParameter, OrganizationJurisdictionAssignment,
)

# Component keys that are display-only placeholders for the income-tax
# concept already covered by this pack's TaxSlab rows (they carry no
# numeric value in the real data — all of employee_rate_pct/
# employer_rate_pct/flat_amount are None) — never migrated as their own
# Tax/Rule; the slab-derived Tax already represents them.
_INCOME_TAX_ALIAS_KEYS = {"income-tax", "federal-income-tax", "tds"}

# Known named-parameter keys (case-insensitive, lowercased) -> canonical
# parameter_key the engine's _param_amount/_param_pct actually look up
# (engine/standard.py). The real data has inconsistent casing/typos
# (e.g. "Standar_Deduction") for some of these — this map corrects that
# at migration time rather than carrying the typo forward into the new
# table, since the new table's parameter_key is what the engine-facing
# adapter (engine/tax_resolver_v2.py::resolve_engine_inputs_v2) will read
# by exact string match.
_KNOWN_PARAMETER_KEYS = {
    "esi_wage_ceiling": "esi_wage_ceiling",
    "standar_deduction": "standard_deduction",
    "standard_deduction": "standard_deduction",
    "rebate_87a_limit": "rebate_87a_limit",
    "rebate_87a_max": "rebate_87a_max",
    "medicare_addl_thresh": "medicare_addl_thresh",
    "ss_wage_base": "ss_wage_base",
    "medicare_additional": "medicare_additional",
    "ni_upper_threshold": "ni_upper_threshold",
    "personal_allowance": "personal_allowance",
    "pa_taper_threshold": "pa_taper_threshold",
    "ni_primary_thresh": "ni_primary_thresh",
    "ni_upper_rate": "ni_upper_rate",
}

# A pack whose compliance_category mentions this is a state/province-level
# Professional-Tax-style slab table, NOT the country's income tax — a real
# distinction found in the live data (IN-PT-TG-2026-V1 / IN-PT-KA-2026-V1),
# where the TaxSlab rows are flat-fee PT bands (mis-modeled under the old
# schema's rate_pct-only slabs — see the new TaxRuleSlab.flat_fee_amount
# field's own docstring), not a progressive income-tax bracket table.
def _slab_tax_code_and_name(pack) -> tuple:
    category = (pack.compliance_category or "").lower()
    if "professional tax" in category:
        return "PROFESSIONAL_TAX", "Professional Tax"
    return "INCOME_TAX", "Income Tax"


class Migrator:
    def __init__(self, db, commit: bool):
        self.db = db
        self.commit = commit
        self.countries: dict = {}       # code -> Country
        self.levels: dict = {}          # (country_code, level_code) -> JurisdictionLevel
        self.jurisdictions: dict = {}   # (country_code, state_or_None) -> Jurisdiction
        self.taxes: dict = {}           # (country_code, tax_code) -> Tax
        self.report: list = []

    def log(self, msg):
        self.report.append(msg)
        print(msg)

    # ── Step 1: Countries ────────────────────────────────────────────────
    def migrate_countries(self):
        codes = set()
        for row in self.db.query(JurisdictionPack.jurisdiction_country).distinct():
            if row[0]:
                codes.add(row[0])
        for row in self.db.query(ContributionRate.jurisdiction_country).filter(ContributionRate.organization_id.is_(None)).distinct():
            if row[0]:
                codes.add(row[0])
        for row in self.db.query(TaxSlab.jurisdiction_country).filter(TaxSlab.organization_id.is_(None)).distinct():
            if row[0]:
                codes.add(row[0])

        for code in sorted(codes):
            existing = self.db.query(Country).filter(Country.code == code).first()
            if existing:
                self.countries[code] = existing
                continue
            name = ALL_CODE_TO_COUNTRY_NAME.get(code, code)
            country = Country(code=code, name=name)
            self.db.add(country)
            self.db.flush()
            self.countries[code] = country
            self.log(f"[country] created {code} ({name}) id={country.id}")

    # ── Step 2: Jurisdiction Levels (NATIONAL/STATE per country) ────────
    def migrate_levels(self):
        for code, country in self.countries.items():
            existing_levels = {lvl.level_code: lvl for lvl in self.db.query(JurisdictionLevel).filter(JurisdictionLevel.country_id == country.id).all()}
            if "NATIONAL" not in existing_levels:
                lvl = JurisdictionLevel(country_id=country.id, level_code="NATIONAL", label="National", rank=0)
                self.db.add(lvl)
                self.db.flush()
                existing_levels["NATIONAL"] = lvl
                self.log(f"[level] {code}: created NATIONAL id={lvl.id}")
            if "STATE" not in existing_levels:
                lvl = JurisdictionLevel(country_id=country.id, level_code="STATE", label="State/Province", rank=1)
                self.db.add(lvl)
                self.db.flush()
                existing_levels["STATE"] = lvl
                self.log(f"[level] {code}: created STATE id={lvl.id}")
            self.levels[(code, "NATIONAL")] = existing_levels["NATIONAL"]
            self.levels[(code, "STATE")] = existing_levels["STATE"]

    # ── Step 3: Jurisdictions (root per country + one per distinct state) ──
    def migrate_jurisdictions(self):
        states = set()
        for row in self.db.query(JurisdictionPack.jurisdiction_country, JurisdictionPack.jurisdiction_state).filter(JurisdictionPack.jurisdiction_state.isnot(None)).distinct():
            states.add(row)
        for row in self.db.query(ContributionRate.jurisdiction_country, ContributionRate.jurisdiction_state).filter(ContributionRate.organization_id.is_(None), ContributionRate.jurisdiction_state.isnot(None)).distinct():
            states.add(row)
        for row in self.db.query(CompanyComplianceDetails.jurisdiction_country, CompanyComplianceDetails.jurisdiction_state).filter(CompanyComplianceDetails.jurisdiction_state.isnot(None), CompanyComplianceDetails.jurisdiction_state != "").distinct():
            if row[0]:
                states.add(row)

        for code, country in self.countries.items():
            existing_root = (
                self.db.query(Jurisdiction)
                .filter(Jurisdiction.country_id == country.id, Jurisdiction.parent_jurisdiction_id.is_(None))
                .first()
            )
            if existing_root:
                root = existing_root
            else:
                root = Jurisdiction(country_id=country.id, level_id=self.levels[(code, "NATIONAL")].id, parent_jurisdiction_id=None, name=country.name)
                self.db.add(root)
                self.db.flush()
                self.log(f"[jurisdiction] {code}: created root '{country.name}' id={root.id}")
            self.jurisdictions[(code, None)] = root

        for code, state in sorted(states):
            if code not in self.countries:
                continue
            existing = (
                self.db.query(Jurisdiction)
                .filter(Jurisdiction.country_id == self.countries[code].id, Jurisdiction.name == state, Jurisdiction.parent_jurisdiction_id == self.jurisdictions[(code, None)].id)
                .first()
            )
            if existing:
                self.jurisdictions[(code, state)] = existing
                continue
            node = Jurisdiction(
                country_id=self.countries[code].id, level_id=self.levels[(code, "STATE")].id,
                parent_jurisdiction_id=self.jurisdictions[(code, None)].id, name=state,
            )
            self.db.add(node)
            self.db.flush()
            self.jurisdictions[(code, state)] = node
            self.log(f"[jurisdiction] {code}: created state '{state}' id={node.id}")

    # ── Step 4: resolve the known live Canada double-Active conflict ────
    # Manual override for one specific, already-reviewed conflict: the
    # generic tie-break (later effective_from wins) would pick
    # CA-FED-TAX-2026-27 — but that pack only has a CPP rate, no income-tax
    # slabs, while CA-PAYROLL-TY2025 (the pack the generic rule would
    # demote) has the real slab table. Confirmed with the user directly —
    # keep the pack with actual income-tax data Active instead of blindly
    # following the generic "later wins" heuristic for this one case.
    _MANUAL_CONFLICT_WINNERS = {
        ("CA", None, None): "CA-PAYROLL-TY2025",
    }

    def resolve_known_conflicts(self):
        """Winner = later effective_from; tie -> has approved_by_id;
        tie -> higher id — UNLESS this exact (country, state, regime) key
        has a manual override above, in which case that decision wins
        regardless of dates. Loser is migrated too, but forced Deprecated
        in the NEW tables only — the OLD JurisdictionPack row is untouched
        (still whatever status it already had), since this migration
        never writes to old tables."""
        active_tax_packs = self.db.query(JurisdictionPack).filter(JurisdictionPack.pack_type == "tax", JurisdictionPack.status == "Active").all()
        groups: dict = {}
        for p in active_tax_packs:
            key = (p.jurisdiction_country, p.jurisdiction_state, p.tax_regime)
            groups.setdefault(key, []).append(p)

        forced_deprecated_ids = set()
        for key, packs in groups.items():
            if len(packs) <= 1:
                continue
            # Two-or-more rows landed in the same group only because they
            # share (country, state, regime) AND are both status="Active"
            # right now under the old system, which never checked
            # date-range overlap on activation — that alone is the
            # conflict; no further overlap math is needed here.
            manual_winner_pack_id = self._MANUAL_CONFLICT_WINNERS.get(key)
            if manual_winner_pack_id and any(p.pack_id == manual_winner_pack_id for p in packs):
                packs_sorted = sorted(packs, key=lambda p: p.pack_id != manual_winner_pack_id)
            else:
                packs_sorted = sorted(
                    packs, key=lambda p: (p.effective_from, p.approved_by_id is not None, p.id), reverse=True,
                )
            winner, losers = packs_sorted[0], packs_sorted[1:]
            self.log(
                f"[conflict] {key}: {len(packs)} simultaneously-Active tax packs found — "
                f"winner={winner.pack_id} (eff {winner.effective_from}), "
                f"loser(s)={[l.pack_id for l in losers]} forced Deprecated in the NEW hierarchy tables only "
                f"(old JurisdictionPack rows untouched). NEEDS HUMAN COMPLIANCE REVIEW."
            )
            for loser in losers:
                forced_deprecated_ids.add(loser.id)
        return forced_deprecated_ids

    # ── Step 5+6: Tax / TaxVersion / TaxRule / leaf rows, per pack ──────
    def migrate_pack(self, pack, forced_deprecated_ids):
        if pack.pack_type != "tax":
            return
        already = self.db.query(TaxVersion).filter(TaxVersion.legacy_pack_id == pack.id).first()
        if already:
            self.log(f"[pack {pack.id}] {pack.pack_id} already migrated - skipping")
            return

        code = pack.jurisdiction_country
        state = pack.jurisdiction_state
        if code not in self.countries or (code, state) not in self.jurisdictions:
            self.log(f"[pack {pack.id}] {pack.pack_id}: unresolved jurisdiction ({code}, {state}) - skipped")
            return
        jurisdiction = self.jurisdictions[(code, state)]
        pack_status = "Deprecated" if pack.id in forced_deprecated_ids else pack.status

        rates = self.db.query(ContributionRate).filter(ContributionRate.organization_id.is_(None), ContributionRate.jurisdiction_pack_id == pack.id).all()
        slabs = self.db.query(TaxSlab).filter(TaxSlab.organization_id.is_(None), TaxSlab.jurisdiction_pack_id == pack.id).all()

        income_tax_version = None
        if slabs:
            tax_code, tax_name = _slab_tax_code_and_name(pack)
            income_tax_version = self._get_or_create_tax_version(code, jurisdiction, tax_code, tax_name, "income_tax", pack, pack_status)
            rule = TaxRule(tax_version_id=income_tax_version.id, rule_type="FORMULA" if any(s.rule_type == "FORMULA" for s in slabs) else "PROGRESSIVE_BRACKET", label=f"{tax_name} Slabs", sort_order=1)
            self.db.add(rule)
            self.db.flush()
            for s in sorted(slabs, key=lambda s: s.sort_order):
                self.db.add(TaxRuleSlab(
                    tax_rule_id=rule.id, min_amount=s.min_amount, max_amount=s.max_amount,
                    rate_pct=s.rate_pct, rate_label=s.rate_label, sort_order=s.sort_order,
                ))
            self.log(f"[pack {pack.id}] {pack.pack_id}: migrated {tax_code} - {len(slabs)} slab(s), version status={pack_status}")

        for r in rates:
            raw_key = (r.component_key or "").strip()
            lowered = raw_key.lower()
            if lowered in _INCOME_TAX_ALIAS_KEYS:
                continue  # display-only placeholder, no numeric value, already covered by the slabs above
            if lowered in _KNOWN_PARAMETER_KEYS:
                if not income_tax_version:
                    self.log(f"[pack {pack.id}] {pack.pack_id}: parameter '{raw_key}' has no income-tax version to attach to - skipped")
                    continue
                canonical_key = _KNOWN_PARAMETER_KEYS[lowered]
                existing_param = self.db.query(TaxParameter).filter(TaxParameter.tax_version_id == income_tax_version.id, TaxParameter.parameter_key == canonical_key).first()
                if existing_param:
                    continue
                if r.employee_rate_pct is not None:
                    value, unit = r.employee_rate_pct, "percent"
                else:
                    value, unit = r.flat_amount, "currency"
                self.db.add(TaxParameter(tax_version_id=income_tax_version.id, parameter_key=canonical_key, label=r.label, value_numeric=value, unit=unit))
                self.log(f"[pack {pack.id}]   parameter {canonical_key}={value} ({unit})")
                continue

            # A generic, independently-payable component (PF/ESI/PT/CPP/EI/...)
            if r.employee_rate_pct is None and r.employer_rate_pct is None and r.flat_amount is None:
                continue  # nothing to migrate — display-only placeholder with no configured value
            tax_code = raw_key.upper().replace(" ", "_").replace("-", "_")[:50]
            version = self._get_or_create_tax_version(code, jurisdiction, tax_code, r.label, "social_contribution", pack, pack_status)
            rule = TaxRule(tax_version_id=version.id, rule_type="FLAT_RATE" if r.flat_amount is not None and r.employee_rate_pct is None and r.employer_rate_pct is None else "CONTRIBUTION", label=r.label, sort_order=r.sort_order or 0, legacy_component_key=raw_key)
            self.db.add(rule)
            self.db.flush()
            self.db.add(TaxRuleRate(
                tax_rule_id=rule.id, employee_rate_pct=r.employee_rate_pct, employer_rate_pct=r.employer_rate_pct,
                employee_flat_amount=r.flat_amount, display_employee_share=r.employee_share,
                display_employer_share=r.employer_share, display_total=r.total,
            ))
            self.log(f"[pack {pack.id}]   tax {tax_code} ({r.label}) - emp%={r.employee_rate_pct} empr%={r.employer_rate_pct} flat={r.flat_amount}")

    def _get_or_create_tax_version(self, country_code, jurisdiction, tax_code, tax_name, category, pack, status):
        tax_key = (country_code, tax_code)
        if tax_key not in self.taxes:
            existing_tax = self.db.query(Tax).filter(Tax.country_id == self.countries[country_code].id, Tax.tax_code == tax_code).first()
            if not existing_tax:
                existing_tax = Tax(country_id=self.countries[country_code].id, tax_code=tax_code, name=tax_name, category=category)
                self.db.add(existing_tax)
                self.db.flush()
            self.taxes[tax_key] = existing_tax
        tax = self.taxes[tax_key]

        version = TaxVersion(
            tax_id=tax.id, jurisdiction_id=jurisdiction.id, version_label=pack.version,
            tax_year=pack.tax_year, tax_regime=pack.tax_regime, status=status,
            effective_from=pack.effective_from or pack.created_at.date(), effective_to=pack.effective_to,
            currency=pack.currency, compliance_owner=pack.compliance_owner, engineering_owner=pack.engineering_owner,
            regulatory_authority=pack.regulatory_authority, compliance_category=pack.compliance_category,
            source_references=pack.source_references, change_summary=pack.change_summary,
            next_review_date=pack.next_review_date, approved_by_id=pack.approved_by_id,
            legacy_pack_id=pack.id,
        )
        self.db.add(version)
        self.db.flush()
        return version

    # ── Step 7: CompanyComplianceDetails.active_pack_id -> assignments ──
    def migrate_org_assignments(self):
        rows = self.db.query(CompanyComplianceDetails).all()
        for row in rows:
            code = row.jurisdiction_country or None
            state = row.jurisdiction_state or None
            if not code or code not in self.countries:
                continue
            key = (code, state) if (code, state) in self.jurisdictions else (code, None)
            jurisdiction = self.jurisdictions.get(key)
            if not jurisdiction:
                continue
            existing = (
                self.db.query(OrganizationJurisdictionAssignment)
                .filter(OrganizationJurisdictionAssignment.organization_id == row.organization_id, OrganizationJurisdictionAssignment.jurisdiction_id == jurisdiction.id)
                .first()
            )
            if existing:
                continue
            status = "active" if row.configured_at else "draft"
            assignment = OrganizationJurisdictionAssignment(
                organization_id=row.organization_id, jurisdiction_id=jurisdiction.id,
                assignment_type="primary", status=status,
                effective_from=(row.configured_at.date() if row.configured_at else None) or row.created_at.date(),
                legacy_compliance_details_id=row.id,
            )
            self.db.add(assignment)
            self.db.flush()
            self.log(f"[assignment] org={row.organization_id}: {code}/{state or '(country-level)'} status={status}")

    def run(self):
        self.migrate_countries()
        self.migrate_levels()
        self.migrate_jurisdictions()
        forced_deprecated_ids = self.resolve_known_conflicts()
        packs = self.db.query(JurisdictionPack).filter(JurisdictionPack.pack_type == "tax").all()
        for pack in packs:
            self.migrate_pack(pack, forced_deprecated_ids)
        self.migrate_org_assignments()

        if self.commit:
            self.db.commit()
            self.log("\n--commit passed: all changes COMMITTED.")
        else:
            self.db.rollback()
            self.log("\nDRY RUN (no --commit passed): all changes ROLLED BACK. Nothing was written.")


def main():
    parser = argparse.ArgumentParser(description="Migrate canonical JurisdictionPack/ContributionRate/TaxSlab data into the new generic hierarchy tables.")
    parser.add_argument("--commit", action="store_true", help="Actually write changes. Without this flag, runs as a dry run and rolls back.")
    args = parser.parse_args()

    initialize_database()
    db = SessionLocal()
    try:
        migrator = Migrator(db, commit=args.commit)
        migrator.run()
    finally:
        db.close()


if __name__ == "__main__":
    main()
