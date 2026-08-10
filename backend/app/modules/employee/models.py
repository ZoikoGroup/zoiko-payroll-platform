"""
modules/employee/models.py
--------------------------
Employee master data for the standalone Payroll Platform.

The standalone platform has exactly ONE employee master: the payroll
module's PayrollEmployee (org-scoped, self-contained, multi-tenant). The
old platform's HR `employees` table was the login record too — here the
login record is modules/auth User, and payroll's employee master stays the
single source of truth for payroll employees.

This alias keeps any code that referenced app.modules.employee.Employee
working after the extraction.
"""

from app.modules.payroll.models import PayrollEmployee as Employee

__all__ = ["Employee"]
