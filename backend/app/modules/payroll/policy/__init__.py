from app.modules.payroll.policy.models import (
    PayrollPolicy,
    PolicyEmployeeCategory as PayrollPolicyEmployeeCategory,
    PolicyLeaveRule as PayrollPolicyLeaveRule,
    PolicyOvertimeRule as PayrollPolicyOvertimeRule,
    PolicyIntegration as PayrollPolicyIntegration,
)
# Deliberately NOT importing the router here. app.database imports
# app.modules.payroll.policy.models for table registration before any
# service module is fully loaded; eagerly importing the router from the
# package __init__ pulls in policy.service, which imports log_activity from
# payroll.service while that module is still mid-import — a pre-existing
# circular ImportError that broke `import app.modules.payroll.service` from
# tests. The router is mounted explicitly by payroll/router.py, so no
# behavior changes.
