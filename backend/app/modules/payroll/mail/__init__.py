from app.modules.payroll.mail.models import PayrollEmailSettings

def __getattr__(name):
    if name == "mail_router":
        from app.modules.payroll.mail.router import mail_router
        return mail_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["PayrollEmailSettings", "mail_router"]
