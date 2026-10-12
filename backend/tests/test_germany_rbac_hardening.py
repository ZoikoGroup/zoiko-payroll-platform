"""
tests/test_germany_rbac_hardening.py
-------------------------------------
Germany-specific RBAC hardening coverage.

Before this file, the only Germany-specific RBAC test in the suite was
test_germany_pap_release_governance.py::test_non_super_admin_cannot_reach_the_write_gate,
which proves only super_admin can pass get_current_super_admin for PAP-
release governance endpoints. No Germany-specific test previously existed
for: the OTHER Germany statutory registries (health funds, contribution
ceilings, minijob/midijob parameters, PV configs, earning-taxability
rules, overtime categories/caps, church-tax exceptions, accident-insurance
profiles), employee statutory profile RBAC, payroll-run approval RBAC,
payslip access/deletion RBAC, PDF/register/summary-report RBAC, or
audit-log RBAC.

This file does NOT invent new roles. Section 0 below reads the real role
model straight from app/core/dependencies.py: three roles exist —
super_admin, org_admin, payroll_admin — and there is no distinct
"reviewer/approver" role, no "read-only" role, and no "statutory
configuration user" role. Every claim below is proven either by:

  (a) introspecting the ACTUAL FastAPI route objects' dependant trees
      (app.modules.payroll.router.payroll_router /
      app.modules.super_admin.router.router) to see exactly which
      dependency function gates a given path+method — not by reading
      the source and trusting a comment, and not via HTTP/TestClient
      (matches this codebase's existing pattern of unit-testing the
      dependency functions directly rather than standing up a client); or
  (b) calling the real dependency function (get_current_super_admin /
      get_current_payroll_operator) directly with a fake user object,
      exactly as test_germany_pap_release_governance.py does; or
  (c) exercising the real service-layer functions against the isolated
      SQLite `db` fixture, exactly as test_germany_tenant_isolation_adversarial.py
      does, to prove a role check succeeding never substitutes for the
      independent tenant (organization_id) check.
"""

import inspect
from datetime import date
from decimal import Decimal

import pytest

from app.core.dependencies import (
    VALID_ROLES,
    ROLE_SUPER_ADMIN,
    ROLE_ORG_ADMIN,
    ROLE_PAYROLL_ADMIN,
    get_current_super_admin,
    get_current_payroll_operator,
    get_current_org_admin,
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem
from app.modules.payroll.router import payroll_router
from app.modules.super_admin.router import router as super_admin_router
from app.modules.organizations.models import Organization


# ── Section 0: the real role model (no invented roles) ──────────────────────

def test_only_three_real_roles_exist_no_reviewer_no_readonly():
    """Ground truth for this whole file. The phase brief's illustrative
    roles ("payroll operator", "reviewer/approver", "statutory
    configuration user", "read-only user") are NOT all real distinct
    roles — see the report for the mapping. Only these three role
    *values* actually exist in the User model/token."""
    assert VALID_ROLES == {ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_PAYROLL_ADMIN}
    assert ROLE_SUPER_ADMIN == "super_admin"
    assert ROLE_ORG_ADMIN == "org_admin"
    assert ROLE_PAYROLL_ADMIN == "payroll_admin"


# ── Fixtures / helpers ───────────────────────────────────────────────────────

def _fake_user(role, organization_id=None):
    return type("FakeUser", (), {"role": role, "organization_id": organization_id})()


def _dependant_calls(dependant, seen=None):
    """Walk a FastAPI route's full dependant tree (including nested
    sub-dependencies and router-level `dependencies=[...]`) and return
    the set of every underlying callable object gating that route. Using
    object identity (not just name) means this catches a shadow/duplicate
    copy of a same-named function being wired in by mistake."""
    if seen is None:
        seen = set()
    if id(dependant) in seen:
        return set()
    seen.add(id(dependant))
    calls = set()
    if dependant.call is not None:
        calls.add(dependant.call)
    for sub in dependant.dependencies:
        calls |= _dependant_calls(sub, seen)
    return calls


def _route(router, path, method):
    matches = [
        r for r in router.routes
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set())
    ]
    assert len(matches) == 1, f"expected exactly one route for {method} {path}, found {len(matches)}"
    return matches[0]


def _gate(router, path, method):
    """Returns the set of dependency callables gating this exact
    endpoint, straight from the live route object."""
    return _dependant_calls(_route(router, path, method).dependant)


# ── Section 1: Germany statutory configuration registries ──────────────────
# All Super-Admin-only per the PAP test. Extends that proof to every OTHER
# Germany registry to confirm they are gated IDENTICALLY (not looser) —
# both for list/read AND for create/approve/status-transition endpoints.

GERMANY_REGISTRY_ENDPOINTS = [
    # PAP assets / releases (already proven at the mechanism level by
    # test_germany_pap_release_governance.py; included here so this file's
    # registry-wide sweep is genuinely complete, not "everything except PAP").
    ("/super-admin/compliance/germany/pap-assets", "GET"),
    ("/super-admin/compliance/germany/pap-assets", "POST"),
    ("/super-admin/compliance/germany/pap-assets/{id}/approve", "PUT"),
    ("/super-admin/compliance/germany/pap-releases", "GET"),
    ("/super-admin/compliance/germany/pap-releases/{id}", "GET"),
    ("/super-admin/compliance/germany/pap-releases/{id}/approve", "PUT"),
    ("/super-admin/compliance/germany/pap-releases/{id}/activate", "POST"),
    # Health funds + U1 tariffs
    ("/super-admin/compliance/germany/health-funds", "GET"),
    ("/super-admin/compliance/germany/health-funds", "POST"),
    ("/super-admin/compliance/germany/health-funds/{id}", "GET"),
    ("/super-admin/compliance/germany/health-funds/{id}/approve", "PUT"),
    ("/super-admin/compliance/germany/health-funds/{id}/status", "PUT"),
    ("/super-admin/compliance/germany/health-funds/u1-tariffs", "GET"),
    ("/super-admin/compliance/germany/health-funds/u1-tariffs", "POST"),
    # Contribution ceilings
    ("/super-admin/compliance/germany/contribution-ceilings", "GET"),
    ("/super-admin/compliance/germany/contribution-ceilings", "POST"),
    ("/super-admin/compliance/germany/contribution-ceilings/{id}/approve", "PUT"),
    ("/super-admin/compliance/germany/contribution-ceilings/{id}/status", "PUT"),
    # Minijob / Midijob parameters
    ("/super-admin/compliance/germany/minijob-midijob-parameters", "GET"),
    ("/super-admin/compliance/germany/minijob-midijob-parameters", "POST"),
    ("/super-admin/compliance/germany/minijob-midijob-parameters/{id}/approve", "PUT"),
    # PV configurations
    ("/super-admin/compliance/germany/pv-configurations", "GET"),
    ("/super-admin/compliance/germany/pv-configurations", "POST"),
    ("/super-admin/compliance/germany/pv-configurations/{id}/approve", "PUT"),
    # Earning taxability rules
    ("/super-admin/compliance/germany/earning-taxability-rules", "GET"),
    ("/super-admin/compliance/germany/earning-taxability-rules", "POST"),
    ("/super-admin/compliance/germany/earning-taxability-rules/{id}/approve", "PUT"),
    # Overtime premium categories / grundlohn caps
    ("/super-admin/compliance/germany/overtime-premium-categories", "GET"),
    ("/super-admin/compliance/germany/overtime-premium-categories", "POST"),
    ("/super-admin/compliance/germany/overtime-grundlohn-caps", "GET"),
    ("/super-admin/compliance/germany/overtime-grundlohn-caps", "POST"),
    # Church tax
    ("/super-admin/compliance/germany/church-tax", "GET"),
    ("/super-admin/compliance/germany/church-tax-exceptions", "GET"),
    ("/super-admin/compliance/germany/church-tax-exceptions", "POST"),
    ("/super-admin/compliance/germany/church-tax-exceptions/{id}/approve", "POST"),
    # Accident insurance profiles
    ("/super-admin/compliance/germany/accident-insurance-profiles", "GET"),
    ("/super-admin/compliance/germany/accident-insurance-profiles", "POST"),
    ("/super-admin/compliance/germany/accident-insurance-profiles/{id}/approve", "PUT"),
]


@pytest.mark.parametrize("path,method", GERMANY_REGISTRY_ENDPOINTS)
def test_every_germany_registry_endpoint_requires_the_real_super_admin_dependency(path, method):
    """Proves — from the live route wiring, not a comment or a guess —
    that every Germany registry endpoint (read AND write) is gated by the
    exact same get_current_super_admin function object, and that no
    looser tenant-role dependency (get_current_payroll_operator /
    get_current_org_admin) is present as an alternate path in."""
    calls = _gate(super_admin_router, path, method)
    assert get_current_super_admin in calls, f"{method} {path} is not gated by get_current_super_admin"
    assert get_current_payroll_operator not in calls, f"{method} {path} unexpectedly also accepts payroll_admin/org_admin"
    assert get_current_org_admin not in calls, f"{method} {path} unexpectedly also accepts org_admin"


def test_non_super_admin_rejected_from_the_shared_registry_gate_list_and_direct_id():
    """The dependency function identity check above proves every listed
    registry endpoint — LIST-shaped (e.g. GET health-funds) and
    DIRECT-ID-shaped (e.g. GET pap-releases/{id}) alike — funnels through
    this one function. So exercising it once, directly, with a
    non-super-admin caller proves rejection for all of them at once,
    consistent with test_germany_pap_release_governance.py's own
    established pattern for this exact dependency."""
    for role in (ROLE_ORG_ADMIN, ROLE_PAYROLL_ADMIN, "auditor", "", None):
        with pytest.raises(ForbiddenException):
            get_current_super_admin(current_user=_fake_user(role, organization_id=1))


# ── Section 2: Employee statutory profile (tenant-owned, NOT super_admin) ──

def test_employee_statutory_profile_write_is_gated_by_payroll_operator_not_super_admin():
    calls = _gate(payroll_router, "/payroll/employees/{employee_id}/statutory-profile", "POST")
    assert get_current_payroll_operator in calls
    assert get_current_super_admin not in calls


def test_employee_statutory_profile_reads_have_no_role_gate_beyond_authentication():
    """Reads (get + history) are tenant-scoped by organization_id inside
    the service layer (see test_germany_tenant_isolation_adversarial.py),
    not by role — any of the three real roles may read within their own
    org. Confirmed from the live route wiring: neither role-dependency
    appears at all on these two GETs."""
    for path in (
        "/payroll/employees/{employee_id}/statutory-profile",
        "/payroll/employees/{employee_id}/statutory-profile/history",
    ):
        calls = _gate(payroll_router, path, "GET")
        assert get_current_super_admin not in calls
        assert get_current_payroll_operator not in calls
        assert get_current_org_admin not in calls


def test_payroll_operator_gate_accepts_every_real_tenant_role_and_rejects_others():
    """get_current_payroll_operator is the actual dependency behind
    employee statutory-profile writes (and payroll-run create/approve,
    payslip delete, etc. — see later sections). Prove its real accept/
    reject boundary directly, matching the existing PAP test's style of
    calling the dependency function with fake user objects."""
    for role in (ROLE_ORG_ADMIN, ROLE_PAYROLL_ADMIN, ROLE_SUPER_ADMIN):
        user = get_current_payroll_operator(current_user=_fake_user(role, organization_id=1))
        assert user.role == role
    for role in ("auditor", "viewer", "", None):
        with pytest.raises(ForbiddenException):
            get_current_payroll_operator(current_user=_fake_user(role, organization_id=1))


def test_cross_tenant_statutory_profile_write_still_blocked_even_with_a_valid_operator_role(db):
    """A role check succeeding must never substitute for the tenant
    check. org_b is a completely legitimate payroll_admin org (role gate
    would pass), but the SERVICE layer must still refuse to let it write
    a statutory profile for org_a's employee — reusing the same
    create_employee_statutory_profile_version entry point the router
    calls after get_current_payroll_operator has already said yes."""
    from app.modules.payroll.schemas import EmployeeStatutoryProfileCreate

    org_a = Organization(organization_name="RBAC Tenant A", organization_code="RBAC_TENANT_A")
    org_b = Organization(organization_name="RBAC Tenant B", organization_code="RBAC_TENANT_B")
    db.add_all([org_a, org_b])
    db.commit()
    db.refresh(org_a)
    db.refresh(org_b)

    emp_a = PayrollEmployee(
        organization_id=org_a.id, employee_code="RBAC_EMP_A", name="RBAC Employee A",
        country_code="DE", ctc=Decimal("6000.00"),
    )
    db.add(emp_a)
    db.commit()
    db.refresh(emp_a)

    # Role gate would say yes for a payroll_admin — this call proves that
    # alone is not sufficient; the org_id argument the service receives
    # (which the router always sets to current_user.organization_id, i.e.
    # org_b's own id here) is what actually decides the outcome.
    get_current_payroll_operator(current_user=_fake_user(ROLE_PAYROLL_ADMIN, organization_id=org_b.id))

    payload = EmployeeStatutoryProfileCreate(
        employee_id=emp_a.id, effective_from=date(2026, 1, 1),
        de_tax_class="I", de_health_fund_code="TK", de_employment_classification="MINIJOB",
    )
    with pytest.raises(NotFoundException):
        service.create_employee_statutory_profile_version(db, emp_a.id, org_b.id, payload, actor_id=99)


# ── Section 3: Payroll run creation vs. approval — same gate, no separate
# approver role exists in this codebase. ────────────────────────────────────

def test_run_creation_and_approval_are_gated_by_the_identical_dependency():
    """The phase brief speculates about a distinct 'reviewer/approver'
    role. It does not exist: create_run and the approve/advance-status
    endpoint are wired to the exact same get_current_payroll_operator
    function object — proven here by identity, not merely by name."""
    create_calls = _gate(payroll_router, "/payroll/runs", "POST")
    approve_calls = _gate(payroll_router, "/payroll/runs/{run_id}/approve", "PUT")
    assert get_current_payroll_operator in create_calls
    assert get_current_payroll_operator in approve_calls
    assert get_current_super_admin not in create_calls
    assert get_current_super_admin not in approve_calls
    # Whatever gates one gates the other — no separate approver tier.
    create_role_gates = {c for c in create_calls if getattr(c, "__name__", "").startswith("get_current")}
    approve_role_gates = {c for c in approve_calls if getattr(c, "__name__", "").startswith("get_current")}
    assert create_role_gates == approve_role_gates


def test_run_approval_role_check_succeeding_does_not_bypass_the_tenant_check(db):
    """Representative tenant-boundary test for the approval transition
    specifically (the existing adversarial suite covers get/download/
    delete/register/list for payslips+runs, but not the approve/advance
    transition). org_b's payroll_admin passes the role gate cleanly, but
    advance_payroll_run_status must still fail closed on org_a's run id,
    and the run's status must be provably unchanged afterward."""
    org_a = Organization(organization_name="RBAC Run Tenant A", organization_code="RBAC_RUN_A")
    org_b = Organization(organization_name="RBAC Run Tenant B", organization_code="RBAC_RUN_B")
    db.add_all([org_a, org_b])
    db.commit()
    db.refresh(org_a)
    db.refresh(org_b)

    run = PayrollRun(
        organization_id=org_a.id, run_code="RBAC-RUN-A-001", period_label="March 2026",
        pay_date=date(2026, 3, 31), period_start=date(2026, 3, 1), period_end=date(2026, 3, 31),
        status="Draft",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Role gate succeeds for org_b's payroll_admin.
    get_current_payroll_operator(current_user=_fake_user(ROLE_PAYROLL_ADMIN, organization_id=org_b.id))

    with pytest.raises(NotFoundException):
        service.advance_payroll_run_status(db, run.id, approver_id=99, organization_id=org_b.id)

    reloaded = db.query(PayrollRun).filter(PayrollRun.id == run.id).first()
    assert reloaded.status == "Draft", "cross-tenant approval attempt must not advance the run's status"


# ── Section 4: Payslip access (read) and deletion ───────────────────────────

def test_payslip_reads_have_no_role_gate_delete_requires_payroll_operator():
    for path, method in [
        ("/payroll/payslips", "GET"),
        ("/payroll/payslips/{payslip_id}", "GET"),
        ("/payroll/payslips/{payslip_id}/download", "GET"),
    ]:
        calls = _gate(payroll_router, path, method)
        assert get_current_super_admin not in calls
        assert get_current_payroll_operator not in calls
        assert get_current_org_admin not in calls

    delete_calls = _gate(payroll_router, "/payroll/payslips/{payslip_id}", "DELETE")
    assert get_current_payroll_operator in delete_calls


def test_payslip_delete_gate_rejects_a_non_real_role():
    """Direct-ID endpoint (a specific payslip_id), role-only check, tenant
    held out of scope here on purpose (tenant isolation for this exact
    endpoint is already proven adversarially in
    test_germany_tenant_isolation_adversarial.py::test_cross_tenant_delete_payslip_rejected)."""
    with pytest.raises(ForbiddenException):
        get_current_payroll_operator(current_user=_fake_user("guest", organization_id=1))


# ── Section 5: PDF download, register, and summary report access ───────────

def test_pdf_register_and_summary_endpoints_have_no_role_gate_only_tenant_scoping():
    """These are all read/export surfaces. None of them require a
    specific elevated role beyond being an authenticated member of the
    org whose data is requested — access control here is entirely the
    tenant (organization_id) check inside the service layer, already
    covered adversarially for the register PDF/CSV in
    test_germany_tenant_isolation_adversarial.py. This test documents
    that finding precisely, from the live route wiring, rather than
    assuming it."""
    for path, method in [
        ("/payroll/payslips/{payslip_id}/download", "GET"),   # payslip PDF
        ("/payroll/reports/{report_id}/download", "GET"),      # register PDF/CSV
        ("/payroll/germany/reports/summary", "GET"),            # Germany summary report
    ]:
        calls = _gate(payroll_router, path, method)
        assert get_current_super_admin not in calls
        assert get_current_payroll_operator not in calls
        assert get_current_org_admin not in calls


# ── Section 6: Audit-log access ─────────────────────────────────────────────

def test_audit_log_endpoints_are_super_admin_only():
    for path, method in [
        ("/super-admin/compliance/tax-configuration/audit", "GET"),
        ("/super-admin/report-templates/{id}/audit", "GET"),
    ]:
        calls = _gate(super_admin_router, path, method)
        assert get_current_super_admin in calls
        assert get_current_payroll_operator not in calls


def test_audit_log_covers_germany_pap_release_entities_and_is_role_gated(db):
    """Sanity that the audit endpoint super_admin gates is the SAME
    mechanism that actually records Germany PAP release governance
    events (TaxConfigurationAudit, entity_type='pap_release') — i.e. this
    isn't a different, uncovered audit trail. Combined with the previous
    test, this proves the real Germany audit-log READ path is
    super_admin-only end to end."""
    asset = service.ingest_pap_asset(
        db, jurisdiction_country="DE", tax_year="2026", pap_version="rbac-audit-test",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
        source_content=b"rbac audit fixture content", source_agency="BMF",
        source_title="RBAC audit fixture", actor_id=1,
    )
    release = service.create_pap_release(db, asset.id, actor_id=1)
    events = service.list_tax_configuration_audit(db, entity_type="pap_release")
    assert any(e.entity_id == release.id for e in events)
    # And the endpoint that serves this data is super_admin-gated (proven
    # by route identity above, re-asserted here to tie the two together).
    calls = _gate(super_admin_router, "/super-admin/compliance/tax-configuration/audit", "GET")
    assert get_current_super_admin in calls


# ── Section 7: Tenant boundary — a legitimate role must never substitute
# for a tenant check; global (non-tenant) registries are a deliberate,
# separate design, not a defect. ─────────────────────────────────────────────

def test_germany_registries_are_deliberately_global_not_tenant_scoped():
    """Contrast: employee statutory profile functions require
    organization_id (tenant-owned data); the Germany REGISTRY functions
    (health funds, etc.) do not take organization_id at all — they are
    global statutory configuration shared by every tenant, gated only by
    super_admin, by design. This is not a tenant-isolation gap: there is
    no tenant dimension to isolate on these rows in the first place."""
    registry_functions = [
        service.list_health_funds,
        service.resolve_germany_health_fund,
        service.list_contribution_ceilings,
        service.list_minijob_midijob_parameters,
    ]
    for fn in registry_functions:
        params = inspect.signature(fn).parameters
        assert "organization_id" not in params, f"{fn.__name__} unexpectedly takes organization_id"

    tenant_scoped_functions = [
        service.create_employee_statutory_profile_version,
        service.get_employee_statutory_profile_as_of,
        service.get_payslip_by_id,
        service.get_payroll_run_by_id,
        service.advance_payroll_run_status,
    ]
    for fn in tenant_scoped_functions:
        params = inspect.signature(fn).parameters
        assert "organization_id" in params, f"{fn.__name__} should be tenant-scoped but takes no organization_id"


def test_super_admin_gate_itself_refuses_a_caller_with_an_organization_id():
    """get_current_super_admin's own second check (organization_id must
    be None) is itself a tenant-shaped safeguard: even a forged token
    claiming role=super_admin cannot ALSO carry a tenant id and pass —
    reinforcing that the global registries' security model has no
    accidental tenant-scoped side door."""
    with pytest.raises(ForbiddenException):
        get_current_super_admin(current_user=_fake_user(ROLE_SUPER_ADMIN, organization_id=1))
    # A real Super Admin (organization_id None) is still admitted.
    admitted = get_current_super_admin(current_user=_fake_user(ROLE_SUPER_ADMIN, organization_id=None))
    assert admitted.role == ROLE_SUPER_ADMIN
