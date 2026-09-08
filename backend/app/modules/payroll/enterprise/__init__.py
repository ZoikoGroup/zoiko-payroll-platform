from app.modules.payroll.enterprise.models import EnterpriseJurisdiction

def __getattr__(name):
    if name == "enterprise_router":
        from app.modules.payroll.enterprise.router import enterprise_router
        return enterprise_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["EnterpriseJurisdiction", "enterprise_router"]
