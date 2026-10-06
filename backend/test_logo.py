import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

from app.services.email_service import _render_template, _load_template, _BASE_WRAPPER_NAME, LOGO_HEADER_HTML

# Test 1: Render a simple template with logo context
template = """<html><body>{{logo_header_block}}Hello {{name}}</body></html>"""
context = {
    "logo_url": "cid:zoiko-payroll-logo",
    "logo_dimension_attrs": ' width="102" height="36"',
    "name": "Test User",
}

result = _render_template(template, context)
print("Test 1 - Simple template with logo_header_block:")
print(result)
print()

# Test 2: Check what _base_wrapper does with logo
wrapper = _load_template(_BASE_WRAPPER_NAME)
print("Base wrapper loaded:", wrapper is not None)
if wrapper:
    # Check if logo_header_block is in wrapper
    if "{{logo_header_block}}" in wrapper:
        print("Wrapper has {{logo_header_block}} placeholder")
    # Try composing
    rendered_body = _render_template("<p>Hello</p>", context)
    composed = wrapper.replace("{{body_slot}}", rendered_body)
    composed_rendered = _render_template(composed, context)
    print("\nTest 2 - Composed wrapper with logo:")
    # Find logo part
    import re
    logo_matches = re.findall(r'{{logo_header_block}}|<img[^>]+>', composed_rendered)
    print("Logo-related content:", logo_matches[:5])