from app.modules.payroll.policy.models import (
    PayrollPolicy,
    PolicyEmployeeCategory as PayrollPolicyEmployeeCategory,
    PolicyLeaveRule as PayrollPolicyLeaveRule,
    PolicyOvertimeRule as PayrollPolicyOvertimeRule,
    PolicyIntegration as PayrollPolicyIntegration,
)

def __getattr__(name):
    if name == "policy_router":
        from app.modules.payroll.policy.router import policy_router
        return policy_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
