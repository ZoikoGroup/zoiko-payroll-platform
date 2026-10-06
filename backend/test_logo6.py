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

from app.services.email_service import send_approval_email, _compose_email_html, _render_template, LOGO_HEADER_HTML, _BASE_WRAPPER_NAME

# Test rendering the template body first
template = """<p>Hello {{employee_name}}</p><p>This is a test</p>"""
context = {
    "employee_name": "Test User",
    "logo_url": "",
    "logo_dimension_attrs": "",
    "frontend_url": "http://localhost:5173",
    "support_email": "",
    "security_advisory_block": "",
    "accent_bar": "",
}

# Compose through the full pipeline
full_context = {**context}
body = _compose_email_html(template, full_context)
print("=== Composed body ===")
print(body)
print()

# Check for logo img tag
import re
logos = re.findall(r'<img[^>]+>', body)
print(f"Logo img tags found: {logos}")
print()

# Now test with the actual send_approval_email 
print("=== Test: send_approval_email ===")
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