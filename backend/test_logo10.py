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

from app.services.email_service import _render_template, _compose_email_html, LOGO_CID, _html_to_text

# Test rendering a template with logo
template = """<html><body>{{logo_header_block}}Hello {{name}}</body></html>"""
context = {
    "name": "Test User",
    "logo_url": "cid:zoiko-payroll-logo",
    "logo_dimension_attrs": ' width="102" height="36"',
}

rendered = _render_template(template, context)
print("=== Rendered template ===")
print(rendered)
print()

# Check if cid is in the body
has_cid = f"cid:{LOGO_CID}" in rendered
print(f"Has cid:{LOGO_CID} in rendered: {has_cid}")

# Now test with _compose_email_html (which adds the wrapper)
from app.email_templates._base_wrapper import _BASE_WRAPPER_NAME as wrapper_name
wrapper = es._load_template(wrapper_name)
print(f"\nWrapper has {{logo_header_block}}: {'{{logo_header_block}}' in wrapper}")

# Compose the full email
body = _compose_email_html(template, context)
print(f"\n=== Composed body (first 500 chars) ===")
print(body[:500])
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