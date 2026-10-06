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

# Also monkeypatch the logger to capture output
import logging
original_info = logging.getLogger("zoiko_payroll").info
original_debug = logging.getLogger("zoiko_payroll").debug

captured_messages = []
def capture_info(msg, *args, **kwargs):
    captured_messages.append(("info", msg % args if args else str(msg)))

def capture_debug(msg, *args, **kwargs):
    captured_messages.append(("debug", msg % args if args else str(msg)))

logging.getLogger("zoiko_payroll").info = capture_info
logging.getLogger("zoiko_payroll").debug = capture_debug

from app.services.email_service import send_approval_email

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

# Write log messages to file to avoid encoding issues
with open("captured_logs.txt", "w", encoding="utf-8") as f:
    for level, msg in captured_messages:
        f.write(f"  [{level}] {msg}\n")

print(f"\nLogged {len(captured_messages)} messages to captured_logs.txt")