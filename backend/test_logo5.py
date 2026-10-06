import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

# Monkeypatch _get_smtp_settings to return empty host (like the test conftest does)
import app.services.email_service as es

original_get_smtp = es._get_smtp_settings

def fake_get_smtp_settings(db=None):
    return {
        "host": "",
        "port": 0,
        "username": "",
        "password": "",
        "from_email": "test@example.com",
        "use_tls": False,
    }

es._get_smtp_settings = fake_get_smtp_settings

from app.services.email_service import send_approval_email

print("=== Test: send_approval_email with proper mock SMTP ===")
result = send_approval_email(
    email="ravurirugvedh1@gmail.com",
    template_name="employee_created.html",
    context={
        "subject": "Welcome to Zoiko Payroll",
        "employee_name": "Test User",
    },
    organization_id=None,
)
print(f"Result: {result}")
print("Check the console output above for the mock email log")