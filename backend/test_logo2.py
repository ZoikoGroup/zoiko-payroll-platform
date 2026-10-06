import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

from app.services.email_service import send_approval_email, _compose_email_html, _render_template, LOGO_HEADER_HTML, _BASE_WRAPPER_NAME
from app.config import settings as _cfg

# Test with different template types

# Test 1: Body-only template (employee_created.html style)
print("=== Test 1: Body-only template ===")
template_body = """<p>Hello {{name}}</p><p>This is a test</p>"""
context = {
    "name": "Test User",
    "logo_url": "",
    "logo_dimension_attrs": "",
    "frontend_url": "http://localhost:5173",
    "support_email": "",
    "security_advisory_block": "",
}
try:
    result = _compose_email_html(template_body, context)
    print("Composed result has logo:", "<img" in result or "cid:" in result)
    # Check for logo img tag
    import re
    logos = re.findall(r'<img[^>]+>', result)
    print("Logo img tags found:", logos)
except Exception as e:
    print(f"Error: {e}")

print()

# Test 2: Standalone template (org_admin_invite.html style has its own logo_header_block)
print("=== Test 2: Standalone template with logo_header_block ===")
template_standalone = """<!DOCTYPE html><html><head>{{mobile_styles}}</head><body>{{logo_header_block}}Hello {{name}}</body></html>"""
context2 = {
    "name": "Test User",
    "logo_url": "cid:zoiko-payroll-logo",
    "logo_dimension_attrs": ' width="102" height="36"',
    "mobile_styles": "<style>body{}</style>",
}
try:
    result = _render_template(template_standalone, context2)
    print("Rendered has img tag:", "<img" in result)
    logos = re.findall(r'<img[^>]+>', result)
    print("Logo img tags:", logos)
except Exception as e:
    print(f"Error: {e}")

print()

# Test 3: What _resolve_logo returns for empty logo_url
from app.services.email_service import _resolve_logo
result = _resolve_logo("")
print("=== Test 3: _resolve_logo('') ===")
print(f"logo_url: {result[0]}")
print(f"dimension_attrs: {result[1]}")
print(f"embed_logo: {result[2]}")