from app.modules.payroll.mail.models import PayrollEmailSettings

# Router deliberately NOT imported here (see payroll/policy/__init__.py for
# the full rationale): app.database imports this package's .models for table
# registration while payroll.models may still be partially initialized, and
# the eager router import drags in mail.service which imports ActivityStatus
# from payroll.models too early. mail_router is mounted explicitly by
# payroll/router.py.

__all__ = ["PayrollEmailSettings"]
