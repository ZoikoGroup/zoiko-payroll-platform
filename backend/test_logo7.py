import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

# Monkeypatch _get_smtp_settings to return empty host (like the test conftest does)
import app.services.email_service as es

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

# Test WITHOUT passing logo_dimension_attrs in context - let the service resolve it
print("=== Test: send_approval_email WITHOUT logo_dimension_attrs in context ===")
result = send_approval_email(
    email="ravurirugvedh1@gmail.com",
    template_name="employee_created.html",
    context={
        "subject": "Welcome to Zoiko Payroll",
        "employee_name": "Test User",
        # NOTE: NOT passing logo_url or logo_dimension_attrs - let the service resolve them
    },
    organization_id=None,
)
print(f"Result: {result}")
print("Check console for mock email log - should have proper logo img tag with cid: URL")