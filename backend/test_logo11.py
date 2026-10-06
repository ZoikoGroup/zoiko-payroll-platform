import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

import app.services.email_service as es

# Monkeypatch _get_smtp_settings
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

from app.services.email_service import _render_template, _compose_email_html, LOGO_CID, _html_to_text, _load_template, _BASE_WRAPPER_NAME

wrapper_name = "_base_wrapper.html"

# Test rendering a template with logo (body-only, like employee_created.html)
template = """<p>Hello {{employee_name}}</p><p>This is a test</p>"""
context = {
    "employee_name": "Test User",
    "logo_url": "cid:zoiko-payroll-logo",
    "logo_dimension_attrs": ' width="102" height="36"',
    "frontend_url": "http://localhost:5173",
    "support_email": "",
    "security_advisory_block": '',
    "accent_bar": '',
}

# Compose through the full pipeline (like send_approval_email does)
body = _compose_email_html(template, context)
print("=== Composed body (first 600 chars) ===")
print(body[:600])
print()

# Check for cid in composed body
has_cid_body = f"cid:{LOGO_CID}" in body
print(f"Has cid:{LOGO_CID} in composed body: {has_cid_body}")

# Check with html_to_text
text = _html_to_text(body)
print(f"\n=== HTML to text (first 200 chars) ===")
print(text[:200])
print()

# Check for cid in text
has_cid_text = f"cid:{LOGO_CID}" in text
print(f"Has cid:{LOGO_CID} in text: {has_cid_text}")

# Now check the MIME condition
print(f"\n=== MIME condition check ===")
print(f"embed_logo would be: True (from resolution)")
print(f"f'cid:{LOGO_CID}' in body: {f'cid:{LOGO_CID}' in body}")
print(f"So the CID image WOULD be embedded: {embed_logo and f'cid:{LOGO_CID}' in body if False else 'N/A'}")