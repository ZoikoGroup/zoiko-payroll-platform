import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

from app.services.email_service import send_approval_email

# Test sending with organization_id=None (default/standalone mode)
print("=== Test: send_approval_email with org_id=None ===")
result = send_approval_email(
    email="ravurirugvedh1@gmail.com",
    template_name="employee_created.html",
    context={
        "subject": "Welcome to Zoiko Payroll",
        "employee_name": "Test User",
    },
    organization_id=None,  # No organization - uses defaults
)
print(f"Result: {result}")
print("Check console output above for the mock email log - it should show the full email body with logo embedded")

# Test with organization_id (if we had one, but using None for standalone)
print()
print("=== Test: send_approval_email with template that goes through wrapper ===")
result2 = send_approval_email(
    email="ravurirugvedh1@gmail.com",
    template_name="org_admin_invite.html",  # Standalone template
    context={
        "subject": "Test Invite",
        "employee_name": "Test User",
        "action_url": "http://localhost:5173",
        "inviter_name": "Test Inviter",
        "organization_name": "Test Org",
        "role_name": "Admin",
        "reference_id": "TEST-001",
    },
    organization_id=None,
)
print(f"Result: {result2}")