"""
core/authz/route_overrides.py
-----------------------------
Hand-reviewed corrections to the generated route policy registry
(ZP-PRIV A03). The generator derives a data class for every route from the
code itself (callgraph.py) plus path heuristics; anything that is wrong or
that must be de-privileged on purpose is listed here WITH A RATIONALE.

Rules enforced by tests/privacy/test_route_registry.py:
  * every override must carry a non-empty ``note``;
  * a route whose static scan reaches worker tables must stay ``worker``
    unless an override explains why the scan is a false positive;
  * no ``worker`` route may list super_admin in its principals.

Choosing ``retired_reason`` (not an empty principal list alone) is what makes
a route deny with ROUTE_RETIRED and shows up as retired in the inventory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Set, Tuple

# Retirement rationales (repeated verbatim in the audit row and the inventory).
R_JIT = "worker-level data requires a live JIT support grant (ZP-PRIV A/B)"
R_TENANT = "statutory action is tenant-run (ZP-PRIV decision 3)"
R_VERIFY = "scan reaches worker tables but the route returns no worker rows; reviewed"


@dataclass(frozen=True)
class Override:
    data_class: Optional[str] = None
    action: Optional[str] = None
    principals: Optional[FrozenSet[str]] = None
    retired_reason: Optional[str] = None
    note: str = ""


OVERRIDES: Dict[Tuple[str, str], Override] = {}


def _retire(method: str, path: str, reason: str, note: str) -> None:
    OVERRIDES[(method, path)] = Override(
        data_class="worker", principals=frozenset(),
        retired_reason=reason, note=note)


def _set(method: str, path: str, *, data_class: str, action: Optional[str] = None,
         principals: Optional[Set[str]] = None, note: str) -> None:
    OVERRIDES[(method, path)] = Override(
        data_class=data_class, action=action,
        principals=frozenset(principals) if principals is not None else None,
        note=note)


# ── Public, token-scoped employee forms ─────────────────────────────────────
# Reachable without a login by design (the emailed token is the capability and
# scopes the request to one employee). Kept public; recorded so the
# scan-vs-classification test has a reviewed rationale.
_set("GET", "/api/payroll/public/employee-forms/{token}", data_class="public",
     principals=set(),
     note="token-scoped single-employee public form; the emailed token is the capability, no enumeration")
_set("POST", "/api/payroll/public/employee-forms/{token}/submit", data_class="public",
     principals=set(),
     note="token-scoped single-employee public form submission; token is the capability")

# ── Tenant self-service billing (was reachable by every role) ───────────────
# Lists payroll_employee_id per invoice for the caller's own organization.
# Restrict to the org's admins; never a platform principal.
_set("GET", "/api/billing/my-subscription/invoice-explanation", data_class="worker",
     principals={"org_admin"},
     note="org-scoped invoice explanation lists worker ids for the caller's own org only")
_set("GET", "/api/billing/my-subscription/invoice-explanation/{invoice_id}", data_class="worker",
     principals={"org_admin"},
     note="org-scoped invoice explanation lists worker ids for the caller's own org only")

# ── Super Admin organization hard delete ────────────────────────────────────
# Destroys a whole tenant; discloses no worker row. Platform lifecycle action.
_set("DELETE", "/api/organizations/{organization_id}", data_class="tenant_lifecycle",
     principals={"super_admin"},
     note="hard delete of a tenant's data; destroys, discloses no worker rows")

# ── Aggregate counts (keep reachable, values suppressed in Part B) ──────────
_set("POST", "/api/super-admin/billing/aggregate-bwm", data_class="aggregate",
     action="read", principals={"super_admin"},
     note="returns billable-worker-month counts only; POST is a query, mapped to read")
_set("GET", "/api/super-admin/compliance/hong-kong/monitoring", data_class="aggregate",
     note="HK compliance monitoring returns counts/statuses only")
_set("GET", "/api/super-admin/compliance/jurisdictions/{country}/statutory-summary",
     data_class="aggregate", note="per-jurisdiction statutory summary returns counts only")
_set("GET", "/api/super-admin/compliance/singapore/statutory-summary", data_class="aggregate",
     note="Singapore statutory summary returns counts only")
_set("GET", "/api/super-admin/compliance/policies/{id}/impact-preview", data_class="aggregate",
     note="policy impact preview returns affected counts only")
_set("GET", "/api/super-admin/dashboard/stats", data_class="aggregate",
     note="platform dashboard totals return counts only")
_set("GET", "/api/super-admin/finance/summary", data_class="aggregate",
     note="per-jurisdiction money is k-suppressed; the payroll_employees scan only "
          "computes the cohort that decides suppression, no worker row is returned")
_set("GET", "/api/super-admin/finance/by-organization", data_class="aggregate",
     note="per-organization money is k-suppressed; the payroll_employees scan only "
          "computes the cohort that decides suppression, no worker row is returned")
_set("GET", "/api/super-admin/finance/overview", data_class="aggregate",
     note="per-run money/headcount is k-suppressed")

# ── Batch B de-privilege: retire worker-level Super Admin routes ────────────
# Each either leaks worker-level rows (R_JIT) or is a statutory action that
# moved to the tenant (R_TENANT, decision 3). Part B converts or removes the
# code and replaces the aggregate ones with suppressed views.

# Reports / dashboard: Part B converted these to k-suppressed aggregates, so
# they are reachable again but never return an identity.
_set("GET", "/api/super-admin/reports/employees", data_class="aggregate",
     note="converted to workforce totals (counts only, k-suppressed); no name/code")
_set("GET", "/api/super-admin/reports/export", data_class="aggregate",
     note="converted to aggregate CSV (counts only, k-suppressed); identity columns removed")
_set("GET", "/api/super-admin/reports/organizations", data_class="aggregate",
     note="org report now returns registry identity + k-suppressed headcount buckets only")
_set("GET", "/api/super-admin/dashboard/charts", data_class="aggregate",
     note="charts return platform trends and k-suppressed per-jurisdiction cells")
_set("GET", "/api/super-admin/compliance/exceptions", data_class="aggregate",
     note="billing reconciliation (plan-limit overages, invoice quantity mismatches per organization) "
          "plus stuck-run COUNTS; no run, worker or payroll detail")
_retire("GET", "/api/super-admin/billing/organizations/{organization_id}/invoices/{invoice_id}/explanation",
        R_JIT, "invoice explanation lists payroll_employee_id across tenants")

# India
_retire("GET", "/api/super-admin/india/forms", R_JIT,
        "renders per-employee tax certificates")
_retire("GET", "/api/super-admin/india/salary-tds-claims", R_JIT,
        "per-employee TDS claims")
_retire("GET", "/api/super-admin/india/salary-tds-declarations", R_JIT,
        "per-employee TDS declarations")

# France
_retire("GET", "/api/super-admin/compliance/france/pas-rates", R_JIT,
        "PAS rates are per-employee worker data")
_retire("POST", "/api/super-admin/compliance/france/pas-rates", R_JIT,
        "PAS rates are per-employee worker data")
_set("GET", "/api/super-admin/compliance/france/readiness", data_class="platform",
     note="verified: org-level readiness/status checks with counts; no per-employee rows")
_set("POST", "/api/super-admin/compliance/france/go-live", data_class="platform",
     note="verified: returns org-level France readiness metadata; no per-employee rows")

# Ireland
_retire("GET", "/api/super-admin/compliance/ireland/rpn-snapshots", R_JIT,
        "RPN snapshots are per-employee tax data")
_retire("POST", "/api/super-admin/compliance/ireland/rpn-snapshots", R_JIT,
        "RPN snapshots are per-employee tax data")
_retire("DELETE", "/api/super-admin/compliance/ireland/rpn-snapshots/{snapshot_id}", R_JIT,
        "RPN snapshot hard delete is un-audited; retired with the rest of the RPN surface")

# Netherlands (tenant-run statutory, decision 3)
_retire("GET", "/api/super-admin/compliance/netherlands/employees", R_JIT,
        "NL employee list is worker-level; tenant route exists")
_retire("GET", "/api/super-admin/compliance/netherlands/expat-decisions", R_TENANT,
        "expat decisions are tenant-run statutory data")
_retire("POST", "/api/super-admin/compliance/netherlands/expat-decisions", R_TENANT,
        "expat decisions are tenant-run statutory data")
_retire("PUT", "/api/super-admin/compliance/netherlands/expat-decisions/{decision_id}/{action}", R_TENANT,
        "expat decisions are tenant-run statutory data")
_retire("POST", "/api/super-admin/compliance/netherlands/loonaangifte/build", R_TENANT,
        "loonaangifte build moves to the tenant (decision 3); SA keeps status/metadata")
_retire("GET", "/api/super-admin/compliance/netherlands/loonaangifte/{return_id}", R_TENANT,
        "loonaangifte lines are tenant-run worker data; SA keeps status/metadata only")
_retire("POST", "/api/super-admin/compliance/netherlands/loonaangifte/{return_id}/correction", R_TENANT,
        "loonaangifte correction moves to the tenant (decision 3)")
_retire("PUT", "/api/super-admin/compliance/netherlands/loonaangifte/{return_id}/reconcile", R_TENANT,
        "loonaangifte reconcile moves to the tenant (decision 3)")
_set("GET", "/api/super-admin/compliance/netherlands/organizations", data_class="aggregate",
     note="derives which organizations have NL workers (a distinct scan of payroll_employees) and returns "
          "organization id/name only; no worker row or count leaves the route")
# Saudi Arabia (tenant-run statutory, decision 3)
_retire("GET", "/api/super-admin/compliance/saudi-arabia/employees/{employee_id}/contracts", R_TENANT,
        "employee contracts move to the tenant; no tenant route exists yet (Part B gap)")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/employees/{employee_id}/contracts", R_TENANT,
        "employee contracts move to the tenant; no tenant route exists yet (Part B gap)")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/employees/{employee_id}/contracts/{contract_id}/approve", R_TENANT,
        "contract approval moves to the tenant (decision 3)")
_retire("GET", "/api/super-admin/compliance/saudi-arabia/eos-ledger", R_TENANT,
        "EOS ledger is tenant-run statutory data")
_retire("GET", "/api/super-admin/compliance/saudi-arabia/final-settlements", R_TENANT,
        "final settlements are tenant-run statutory data")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/final-settlements", R_TENANT,
        "final settlements are tenant-run statutory data")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/final-settlements/{settlement_id}/approve", R_TENANT,
        "final settlement approval moves to the tenant (decision 3)")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/final-settlements/{settlement_id}/pay", R_TENANT,
        "final settlement payment moves to the tenant (decision 3)")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/payslips/{payslip_id}/correction", R_TENANT,
        "payslip correction moves to the tenant (decision 3)")
_retire("GET", "/api/super-admin/compliance/saudi-arabia/payslips/{payslip_id}/corrections", R_TENANT,
        "payslip corrections are tenant-run statutory data")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/runs/{run_id}/eos-accrual", R_TENANT,
        "EOS accrual moves to the tenant (decision 3)")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/runs/{run_id}/gosi-liability", R_TENANT,
        "GOSI liability is tenant-run statutory data")
_retire("POST", "/api/super-admin/compliance/saudi-arabia/runs/{run_id}/wps-file", R_TENANT,
        "WPS file generation moves to the tenant (decision 3); SA keeps status only")
_retire("GET", "/api/super-admin/compliance/saudi-arabia/wps-files/{wps_file_id}/observations", R_TENANT,
        "WPS observations are tenant-run statutory data")
_retire("GET", "/api/super-admin/compliance/saudi-arabia/runs/{run_id}/fingerprint", R_JIT,
        "run fingerprint reads per-employee rows with no org filter (cross-tenant)")
_retire("GET", "/api/super-admin/compliance/saudi-arabia/runs/{run_id}/preflight", R_JIT,
        "run preflight reads per-employee rows with no org filter (cross-tenant)")

# Switzerland
_retire("GET", "/api/super-admin/compliance/switzerland/qst-tariffs/{tariff_file_id}/affected-payslips", R_JIT,
        "affected-payslips takes no org filter and is cross-tenant")
_retire("POST", "/api/super-admin/compliance/switzerland/calculation-preview", R_JIT,
        "loads a real PayrollEmployee and returns its employeeId (verified worker rows)")

# RTI
_retire("GET", "/api/super-admin/compliance/rti-forms", R_JIT,
        "per-employee RTI forms are worker-level")

# ── Verified scan false positives (no worker rows in the response) ──────────
# Each verified by reading the handler + its service return (see notes).
# These stay reachable by Super Admin and are platform config/certification.

_set("POST", "/api/super-admin/compliance/hong-kong/calculation-preview",
     data_class="platform",
     note="verified synthetic: preview computes from inline synthetic facts; no employee fields returned")
_set("GET", "/api/super-admin/compliance/hong-kong/configuration/compare",
     data_class="platform", note="verified config: returns statutory pack row diffs only")
_set("GET", "/api/super-admin/compliance/hong-kong/configuration/packs/{pack_row_id}",
     data_class="platform", note="verified config: returns statutory pack rows only")
_set("POST", "/api/super-admin/compliance/hong-kong/configuration/packs/{pack_row_id}/new-version",
     data_class="platform", note="verified metadata: creates/clones a pack, returns id/version/status")
_set("GET", "/api/super-admin/compliance/hong-kong/packs/{pack_row_id}/golden-check",
     data_class="platform", note="verified synthetic: runs golden fixtures; returns pass/fail counts")
_set("GET", "/api/super-admin/compliance/saudi-arabia/packs/{pack_row_id}/golden-check",
     data_class="platform", note="verified synthetic: same golden-vector harness as HK; pass/fail counts only")
_set("GET", "/api/super-admin/compliance/hong-kong/readiness-center",
     data_class="platform", note="verified metadata: readiness gates/status counts only")
_set("POST", "/api/super-admin/compliance/hong-kong/service-registry",
     data_class="platform", note="verified metadata: returns country/availability/updatedAt only")
_set("POST", "/api/super-admin/compliance/jurisdictions/{country}/service-registry",
     data_class="platform", note="verified metadata: returns country/availability/updatedAt only")
_set("POST", "/api/super-admin/compliance/italy/calculation-preview",
     data_class="platform", note="verified synthetic: inline synthetic facts; returns gross/deductions/netPay only")
_set("POST", "/api/super-admin/compliance/saudi-arabia/calculation-preview",
     data_class="platform", note="verified synthetic: inline synthetic facts; employeeId is input, not echoed")
_set("POST", "/api/super-admin/compliance/singapore/calculation-preview",
     data_class="platform", note="verified synthetic: inline synthetic facts; returns CPF/SDL/etc. only")
_set("POST", "/api/super-admin/compliance/singapore/service-registry",
     data_class="platform", note="verified metadata: returns country/availability/updatedAt only")
_set("POST", "/api/super-admin/compliance/sweden/calculation-preview",
     data_class="platform", note="verified synthetic: inline synthetic facts; returns totals only")
_set("PUT", "/api/super-admin/compliance/policies", data_class="platform",
     note="verified config: upserts a jurisdiction pack; returns the pack, no worker rows")
_set("POST", "/api/super-admin/compliance/tax-configuration/state-import",
     data_class="platform", note="verified config: imports a state tax pack; returns the pack")
_set("PUT", "/api/super-admin/compliance/germany/pap-releases/{id}/golden-vectors",
     data_class="platform", note="verified metadata: PAP release certification fields only")
_set("POST", "/api/super-admin/compliance/germany/pap-releases/{id}/activate",
     data_class="platform", note="verified metadata: PAP release status only")
_set("GET", "/api/super-admin/compliance/germany/pap-releases/{id}/gate-status",
     data_class="platform", note="verified metadata: gate evaluation flags only")
_set("DELETE", "/api/super-admin/compliance/switzerland/schemes/{scheme_id}",
     data_class="platform", note="verified config: deletes a DRAFT scheme; returns the scheme view")
_set("POST", "/api/super-admin/compliance/switzerland/qst-tariffs/{tariff_file_id}/activate",
     data_class="platform", note="verified config: tariff activation with aggregate impact counts")
_set("DELETE", "/api/super-admin/report-templates/{id}", data_class="platform",
     note="verified metadata: deletes a template; returns success only")
_set("PUT", "/api/super-admin/finance/organizations/{organization_id}/currency",
     data_class="platform",
     note="platform config write (org currency setting); not a worker aggregate")

# Aggregate-only certification/count routes (action read: POST is a query).
_set("POST", "/api/super-admin/compliance/test-certification/run", data_class="aggregate",
     action="read", note="verified aggregate: returns case pass/fail counts, no worker rows")

# ── Batch C (2026-10-19 audit): tenant-owned employer configuration and
# tenant workflow surfaces still reachable by Super Admin ───────────────────
# Each moved to a tenant route under /api/payroll/... (tenant_statutory_router
# or an existing tenant route) where the organization comes from the login.
_SA = "/api/super-admin/compliance"
_NL = "/api/super-admin/compliance/netherlands"

for _m, _p, _n in (
    ("GET", f"{_SA}/france/employer-profile", "France employer identity is tenant data; tenant route /api/payroll/france/employer-profile"),
    ("PUT", f"{_SA}/france/employer-profile", "France employer identity is tenant data; tenant route /api/payroll/france/employer-profile"),
    ("POST", f"{_SA}/france/effectif", "governed effectif (exact headcount) is tenant data; tenant route exists"),
    ("POST", f"{_SA}/france/effectif/corrections", "effectif correction moves to the tenant"),
    ("GET", f"{_SA}/france/establishments", "SIRET registry is tenant data; tenant route exists"),
    ("POST", f"{_SA}/france/establishments", "SIRET registry is tenant data; tenant route exists"),
    ("PUT", f"{_SA}/france/establishments/{{establishment_id}}", "SIRET registry is tenant data; tenant route exists"),
    ("GET", f"{_SA}/france/establishment-rate-packs", "AT/MP rate packs are tenant data; tenant route exists"),
    ("PUT", f"{_SA}/france/establishment-rate-packs", "AT/MP rate packs are tenant data; tenant route exists"),
    ("PATCH", f"{_SA}/france/establishment-rate-packs/{{pack_id}}", "AT/MP rate packs are tenant data; tenant route exists"),
    ("POST", f"{_SA}/france/establishment-rate-packs/{{pack_id}}/close", "AT/MP rate packs are tenant data; tenant route exists"),
    ("POST", f"{_SA}/france/go-live", "go-live is a tenant action; tenant route /api/payroll/france/go-live"),
    ("GET", f"{_SA}/france/readiness", "per-organization readiness detail carries tenant counts; tenant route exists"),
    ("GET", f"{_SA}/france/dsn-submissions", "DSN submissions are tenant filings; tenant route /api/payroll/france/dsn-submissions"),
    ("GET", f"{_SA}/france/dsn-outbox", "DSN outbox payloads are tenant filings; tenant route exists"),
    ("GET", f"{_SA}/germany/accident-insurance-profiles", "employer accident-insurance profile is tenant config; tenant route exists"),
    ("POST", f"{_SA}/germany/accident-insurance-profiles", "employer accident-insurance profile is tenant config; tenant route exists"),
    ("GET", f"{_SA}/germany/accident-insurance-profiles/{{id}}", "employer accident-insurance profile is tenant config"),
    ("PUT", f"{_SA}/germany/accident-insurance-profiles/{{id}}/approve", "approval moves to a second tenant user"),
    ("PUT", f"{_SA}/germany/accident-insurance-profiles/{{id}}/status", "lifecycle moves to the tenant"),
    ("GET", f"{_SA}/saudi-arabia/employer-profiles", "GOSI employer registration is tenant config; tenant route exists"),
    ("POST", f"{_SA}/saudi-arabia/employer-profiles", "GOSI employer registration is tenant config; tenant route exists"),
    ("POST", f"{_SA}/saudi-arabia/employer-profiles/{{profile_id}}/approve", "approval moves to the tenant"),
    ("GET", f"{_SA}/saudi-arabia/gosi-liabilities", "monthly GOSI liabilities are one tenant's wages; tenant route exists"),
    ("POST", f"{_SA}/saudi-arabia/gosi-liabilities/{{liability_id}}/paid", "liability payment is a tenant action; tenant route exists"),
    ("GET", f"{_SA}/saudi-arabia/wps-files", "WPS files are tenant filings; tenant route exists"),
    ("POST", f"{_SA}/saudi-arabia/wps-files/{{wps_file_id}}/accepted", "WPS outcome is recorded by the tenant; tenant route exists"),
    ("POST", f"{_SA}/saudi-arabia/wps-files/{{wps_file_id}}/rejected", "WPS outcome is recorded by the tenant; tenant route exists"),
    ("GET", f"{_SA}/employer-tax-profiles", "employer SUI rates/accounts are tenant config; tenant route exists"),
    ("PUT", f"{_SA}/employer-tax-profiles", "employer SUI rates/accounts are tenant config; tenant route exists"),
    ("DELETE", f"{_SA}/employer-tax-profiles/{{id}}", "employer SUI rates/accounts are tenant config; tenant route exists"),
    ("PUT", f"{_SA}/filings-remittances/{{organization_id}}", "statutory filing records are written by the tenant (/api/payroll/filings/records)"),
    ("DELETE", f"{_SA}/filings-remittances/{{organization_id}}/{{filing_id}}", "statutory filing records are managed by the tenant"),
    ("GET", f"{_NL}/loonaangifte", "NL returns are tenant filings; tenant route /api/payroll/netherlands/loonaangifte"),
    ("POST", f"{_NL}/loonaangifte/{{return_id}}/file", "filing is a tenant action (decision 3)"),
    ("PUT", f"{_NL}/loonaangifte/{{return_id}}/accept", "filing outcome is recorded by the tenant"),
    ("PUT", f"{_NL}/loonaangifte/{{return_id}}/reject", "filing outcome is recorded by the tenant"),
    ("POST", f"{_NL}/digipoort/submit", "Digipoort submission is a tenant action (decision 3)"),
    ("POST", f"{_NL}/authority-payments/prepare", "authority payments are a tenant action; tenant route exists"),
    ("GET", f"{_NL}/employer-profile", "NL employer identity is tenant data; tenant route exists"),
    ("POST", f"{_NL}/employer-profile", "NL employer identity is tenant data; tenant route exists"),
    ("GET", f"{_NL}/premium-decisions", "employer premium decisions are tenant config; tenant route exists"),
    ("POST", f"{_NL}/premium-decisions", "employer premium decisions are tenant config; tenant route exists"),
    ("PUT", f"{_NL}/premium-decisions/{{decision_id}}/activate", "activation moves to the tenant"),
    ("GET", "/api/super-admin/statutory-rates/organization-rates",
     "an organization's own contribution-rate rows are tenant config; tenant route /api/payroll/compliance/contribution-rates"),
):
    _retire(_m, _p, R_TENANT, _n)

_retire("GET", f"{_NL}/vcr", R_JIT, "per-employee cumulative wage snapshots (takes employee_id)")

# Converted in place (counts only; see the handlers' docstrings).
_set("GET", "/api/super-admin/payroll/runs", data_class="aggregate",
     note="converted: run counts by jurisdiction/status + at-risk counts; no run, org name, date or money")
_set("GET", "/api/super-admin/compliance/filings-remittances", data_class="aggregate",
     note="converted: filing counts by jurisdiction; no organization, period or filing row")
_set("GET", "/api/super-admin/alerts", data_class="aggregate",
     note="tenant workflow alerts are counts only; platform/billing alerts unchanged")


# ── Part D: the legacy Assisted Access API is retired (superseded by JIT
# Support Access). Kept in the code base for its history tables only.
R_ASSISTED = "assisted access is retired; JIT Support Access replaces it (ZP-PRIV Part D)"
for _m, _p in (
    ("POST", "/api/super-admin/assisted-access/{organization_id}/request"),
    ("POST", "/api/super-admin/assisted-access/{organization_id}/start"),
    ("POST", "/api/super-admin/assisted-access/{session_id}/approve-break-glass"),
    ("POST", "/api/super-admin/assisted-access/{session_id}/activate"),
    ("POST", "/api/super-admin/assisted-access/{session_id}/end"),
    ("GET", "/api/super-admin/assisted-access/active"),
    ("POST", "/api/super-admin/assisted-access/sweep"),
    ("GET", "/api/organization-admin/assisted-access/status"),
    ("GET", "/api/organization-admin/assisted-access/requests"),
    ("POST", "/api/organization-admin/assisted-access/requests/{session_id}/approve"),
    ("POST", "/api/organization-admin/assisted-access/requests/{session_id}/reject"),
):
    OVERRIDES[(_m, _p)] = Override(data_class="support", principals=frozenset(),
                                   retired_reason=R_ASSISTED, note="legacy assisted access retired")


# ── Mexico / Brazil Super Admin routes (merged from main, 2026-10-19) ───────
# Employee lists and records are worker data: the organization sees its own,
# Zoiko staff only through an approved Support Access grant.
_MX = "/api/super-admin/compliance/mexico"
_BR = "/api/super-admin/compliance/brazil"
_retire("GET", f"{_MX}/employees", R_JIT, "lists Mexican employees (names, codes) of one organization")
_retire("GET", f"{_MX}/employees/{{employee_id}}", R_JIT, "one Mexican employee's record and readiness")
_retire("GET", f"{_BR}/employees", R_JIT, "lists Brazilian employees (names, codes) of one organization")
# Registry and counts only - no identity, pay or per-person row.
_set("GET", f"{_MX}/organizations", data_class="aggregate",
     note="reviewed: organization id + name of tenants with Mexico payroll (registry metadata)")
_set("GET", f"{_BR}/organizations", data_class="aggregate",
     note="reviewed: organization id + name of tenants with Brazil payroll (registry metadata)")
_set("GET", f"{_MX}/cfdi", data_class="aggregate",
     note="reviewed: CFDI counts by status + schema release; UNKNOWN documents reduced to a count")
_set("GET", f"{_MX}/authorities", data_class="aggregate",
     note="reviewed: IMSS / SUA / ISN counts by status and platform blocks; no movement rows")

