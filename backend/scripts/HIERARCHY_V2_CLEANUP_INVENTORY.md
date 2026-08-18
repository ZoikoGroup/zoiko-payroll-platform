# Hierarchy v2 — Phase 9 Cleanup Inventory

Status as of this writing: **zero organizations are cut over to the jurisdiction
tax hierarchy engine (`app/modules/payroll/hierarchy/`)**. Every item below is
therefore explicitly **not yet actionable** — nothing in this file has been
removed, renamed, or functionally deprecated. This is a tracking list only,
written so the eventual cleanup doesn't require re-deriving "what's safe to
touch" from scratch.

Do not act on any row until its "Unblocks when" condition is actually true.
Cutover is per-organization (see `migrate_tax_hierarchy.py` and
`CompanyComplianceDetails.tax_hierarchy_v2_enabled`) — this file should be
revisited each time another org cuts over, not treated as all-or-nothing.

## Removal candidates

| Item | Location | Superseded by | Unblocks when |
|---|---|---|---|
| `PayrollEnterpriseJurisdiction` + its own contribution-rate storage | `app/modules/payroll/enterprise/` (models/service/router) | `OrganizationJurisdictionAssignment` (multiple assignments = "Enterprise" UI state) | Every org currently using Enterprise mode has a working, verified hierarchy-engine assignment covering everything its current jurisdictions cover. |
| `EnterpriseJurisdictionsTab.jsx`, `JurisdictionConfigPanel.jsx` as standalone components | `frontend/src/modules/payroll/Compliances/EnterpriseOnboarding/` | A derived "multiple jurisdiction assignments" UI state inside the ordinary Compliance page | Same as above, plus a frontend UI actually built for managing multiple assignments (today's `HierarchyComplianceTab.jsx` only manages a single primary assignment). |
| JurisdictionPack-based Super Admin Compliance CRUD | `app/modules/super_admin/router.py` "Compliance" section (`/compliance/policies`, `/compliance/jurisdiction-packs`, canonical rate/slab endpoints) | `hierarchy_super_admin_router` (`/super-admin/tax-hierarchy/*`) | All organizations sourcing rates from a given jurisdiction are validated and cut over; even then, keep read paths alive forever for historical payslip reproducibility — only the write/CRUD paths are real removal candidates. |
| `CompanyComplianceDetails.active_pack_id` | `app/modules/payroll/models.py` | Tax half: `OrganizationJurisdictionAssignment` (already dynamic, not pinned). Policy half: stays exactly as-is. | Never fully removed — at most renamed to `active_policy_pack_id` once every remaining reader/writer of the tax-assignment meaning of this column is confirmed gone (grep `active_pack_id` across the codebase first). |
| Old `engine/tax_resolver.py` (v1) | `app/modules/payroll/engine/tax_resolver.py` | `engine/tax_resolver_v2.py` | **Never** — this must stay forever. Frozen historical payslips (`PayslipItem.tax_policy_pack_id` / `tax_rule_snapshot`) resolve through v1's data shape permanently, even after every org is on v2 for new payroll runs. |
| `TaxConfigurationAudit` (old audit table) | `app/modules/payroll/models.py` | `TaxVersionAudit` | **Never** — coexists permanently with `TaxVersionAudit`, one per system, by design (see `hierarchy/models.py::TaxVersionAudit` docstring). Not a removal candidate, listed here only so it isn't mistaken for one later. |

## How to actually execute a row above, when its time comes

1. Confirm the "Unblocks when" condition with a real query (e.g. `SELECT DISTINCT organization_id FROM ... WHERE tax_hierarchy_v2_enabled = false` should return nothing relevant to that row).
2. Grep every caller of what you're about to touch — this codebase's convention throughout the hierarchy build has been to verify zero remaining external references before moving/renaming/deleting anything.
3. Re-run the full backend `pytest` suite and `npm run build` after the change, exactly as done throughout Phases 3–8.
4. Prefer deprecate-in-place (routes return 410/log a warning) over hard deletion for at least one release cycle, matching this project's "reversible before destructive" convention.

## Explicitly not on this list

Anything not mentioned above (in particular the whole `hierarchy/` module, `tax_resolver_v2.py`, and the new frontend hierarchy components) is net-new and was never a duplicate of anything — there is nothing to "clean up" about the new system itself, only about the old system once it's genuinely safe to retire pieces of it.
