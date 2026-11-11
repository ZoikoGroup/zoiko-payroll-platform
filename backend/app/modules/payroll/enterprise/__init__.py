from app.modules.payroll.enterprise.models import EnterpriseJurisdiction

# Enterprise Payroll setup was removed (2026-10-29) — superseded by the
# per-country entitlement ledger (billing/jurisdiction_entitlement.py) and
# per-employee country engines. Only the table model remains, so existing
# payroll_enterprise_jurisdictions rows and migrations stay consistent.

__all__ = ["EnterpriseJurisdiction"]
