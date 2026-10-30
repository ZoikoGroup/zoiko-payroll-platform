import sys
sys.path.insert(0, ".")
from app.core.authz.policy import evaluate, MATRIX, DC_WORKER
from app.core.authz.principal import Principal

p = Principal(user_id=1, role="super_admin", organization_id=None, payroll_employee_id=None)
print("MATRIX super_admin worker:", MATRIX.get("super_admin", {}).get(DC_WORKER))
class FakePolicy:
    data_class = DC_WORKER
    action = "read"
    principals = {"employee", "org_admin", "payroll_admin", "support_temp"}
    retired_reason = None
    path = "/api/payroll/employees/{employee_id}"
    method = "GET"
decision = evaluate(p, FakePolicy(), path_params={"employee_id": "1"}, db=None)
print("decision:", decision.allowed, decision.reason, decision.status_code)
