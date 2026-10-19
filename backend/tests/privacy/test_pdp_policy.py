"""
tests/privacy/test_pdp_policy.py
--------------------------------
ZP-PRIV A04: unit tests for the PDP decision function. No HTTP, no DB - the
Principal is constructed directly, so every role and data class is covered
without a login (decision 2: employee policy + persona only, no login).
"""

from __future__ import annotations



def _mod():
    from app.core.authz import policy as P
    from app.core.authz.principal import Principal
    return P, Principal


def _policy(data_class, action="read", principals=(), retired=None, path="/x"):
    P, _ = _mod()
    return P.RoutePolicy(
        method="GET", path=path, data_class=data_class, action=action,
        resource="t", principals=frozenset(principals),
        scope_level="tenant", retired_reason=retired)


def _principal(role, org=1, emp=None):
    _, Principal = _mod()
    return Principal(user_id=9, role=role, organization_id=org,
                     email="u@example.com", payroll_employee_id=emp)


def test_public_allows_anyone_even_without_principal():
    P, _ = _mod()
    d = P.evaluate(None, _policy(P.DC_PUBLIC, "read", principals=()))
    assert d.allowed and d.reason == "PUBLIC_ROUTE"


def test_unregistered_route_denies_everyone():
    P, _ = _mod()
    d = P.evaluate(_principal("super_admin", org=None),
                   P.unregistered_policy("GET", "/x"))
    assert not d.allowed and d.status_code == 403
    assert d.reason == "ROUTE_NOT_REGISTERED"


def test_no_principal_is_401():
    P, _ = _mod()
    d = P.evaluate(None, _policy(P.DC_WORKER, "read", principals=("org_admin",)))
    assert not d.allowed and d.status_code == 401 and d.reason == "NO_PRINCIPAL"


def test_retired_route_denies_everyone():
    P, _ = _mod()
    for role in ("super_admin", "org_admin", "payroll_admin"):
        pol = _policy(P.DC_WORKER, "read", principals=("org_admin",),
                      retired="tenant-run")
        d = P.evaluate(_principal(role), pol)
        assert not d.allowed and d.reason == "ROUTE_RETIRED"


def test_role_not_in_route_principals_is_denied():
    P, _ = _mod()
    d = P.evaluate(_principal("super_admin", org=None),
                   _policy(P.DC_PLATFORM, "read", principals=("org_admin",)))
    assert not d.allowed and d.reason == "ROLE_NOT_PERMITTED"


def test_super_admin_cannot_read_worker_route():
    P, _ = _mod()
    # Even if a bug put super_admin in the principals, the matrix denies it.
    d = P.evaluate(_principal("super_admin", org=None),
                   _policy(P.DC_WORKER, "read", principals=("super_admin", "org_admin")))
    assert not d.allowed


def test_role_matrix_allows_and_denies_actions():
    P, _ = _mod()
    # org_admin may write worker data
    assert P.evaluate(_principal("org_admin"),
                      _policy(P.DC_WORKER, "update", principals=("org_admin",))).allowed
    # support_operator may not read worker data at all
    assert not P.evaluate(_principal("support_operator", org=None),
                          _policy(P.DC_WORKER, "read", principals=("support_operator",))).allowed
    # employee may read but not update
    assert not P.evaluate(_principal("employee", emp=1),
                          _policy(P.DC_WORKER, "update", principals=("employee",))).allowed


def test_export_action_denial_has_its_own_reason():
    P, _ = _mod()
    # support_temp may read aggregates but may never export.
    d = P.evaluate(_principal("support_temp"),
                   _policy(P.DC_AGGREGATE, "export", principals=("support_temp",)))
    assert not d.allowed and d.reason == "EXPORT_ATTEMPT_DENIED"


def test_tenant_role_without_org_is_denied_on_worker():
    P, _ = _mod()
    d = P.evaluate(_principal("org_admin", org=None),
                   _policy(P.DC_WORKER, "read", principals=("org_admin",)))
    assert not d.allowed and d.reason == "TENANT_SCOPE_MISSING"


def test_platform_role_carrying_org_is_denied_on_worker():
    P, _ = _mod()
    d = P.evaluate(_principal("super_admin", org=5),
                   _policy(P.DC_WORKER, "read", principals=("super_admin", "org_admin")))
    assert not d.allowed


def test_support_temp_denied_until_grant_is_live():
    P, _ = _mod()
    d = P.evaluate(_principal("support_temp"),
                   _policy(P.DC_WORKER, "read", principals=("support_temp",)))
    assert not d.allowed and d.reason == "SUPPORT_GRANT_REQUIRED"


def test_employee_self_only():
    P, _ = _mod()
    own = _policy(P.DC_WORKER, "read", principals=("employee",), path="/e/{employee_id}")
    assert P.evaluate(_principal("employee", emp=7), own,
                      path_params={"employee_id": "7"}).allowed
    d = P.evaluate(_principal("employee", emp=7), own,
                   path_params={"employee_id": "8"})
    assert not d.allowed and d.reason == "EMPLOYEE_SELF_ONLY"


def test_pdp_exception_denies_with_pdp_error(monkeypatch):
    P, _ = _mod()
    pol = _policy(P.DC_WORKER, "read", principals=("org_admin",))

    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(P, "_evaluate", boom)
    d = P.evaluate(_principal("org_admin"), pol)
    assert not d.allowed and d.reason == "PDP_ERROR"


def test_object_scope_out_of_org_is_404():
    P, _ = _mod()

    class _Row:
        def __init__(self, org):
            self._org = org

        def first(self):
            return (self._org,)

    class _Query:
        def __init__(self, org):
            self._org = org

        def filter(self, *a, **k):
            return self

        def first(self):
            return (self._org,)

    class _DB:
        def __init__(self, org):
            self._org = org

        def query(self, *a, **k):
            return _Query(self._org)

    pol = _policy(P.DC_WORKER, "read", principals=("org_admin",), path="/e/{employee_id}")
    # employee 5 belongs to a different org -> 404, no existence leak
    d = P.evaluate(_principal("org_admin", org=1), pol,
                   path_params={"employee_id": 5}, db=_DB(2))
    assert not d.allowed and d.status_code == 404
    assert d.reason == "ACCESS_DENIED_OUT_OF_SCOPE"
    # same org -> allow
    assert P.evaluate(_principal("org_admin", org=2), pol,
                      path_params={"employee_id": 5}, db=_DB(2)).allowed
