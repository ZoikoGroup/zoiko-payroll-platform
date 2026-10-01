"""
app/tasks/__init__.py
----------------------
Task package initialization.
"""
# This package contains all Celery tasks organized by domain:
# - payroll_tasks: Payroll run processing, payslip generation
# - attendance_tasks: Attendance bulk upload, processing
# - employee_tasks: Bulk employee create/update/delete
# - revenue_tasks: Revenue/ROS submissions, monthly returns
# - report_tasks: Report generation, PDF/Excel exports
# - email_tasks: Email sending, notifications
# - billing_tasks: Trial expiry, subscription management
# - auth_tasks: Token cleanup, revoked token cleanup
# - assist_tasks: KB expiry, retention cleanup