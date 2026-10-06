import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

import app.services.email_service as es

# Monkeypatch to debug
original_resolve = es._resolve_logger if hasattr(es, '_resolve_logger') else None

# Let's just trace through the actual code
from app.config import settings as _cfg
from app.services.email_service import _resolve_logo, _email_logo_bytes, _get_org_branding, _frontend_base

print("=== Tracing logo resolution ===")

# Simulate what happens in send_approval_email with org_id=None
organization_id = None
db = None

branding = _get_org_branding(organization_id, db=db)
print(f"Branding logo_url: '{branding.get('logo_url')}'")

full_context = {**branding}
print(f"Full context logo_url after branding: '{full_context.get('logo_url')}'")

frontend_base = _frontend_base()
print(f"Frontend base: {frontend_base}")

logo_url, logo_dimension_attrs, embed_logo = _resolve_logo(full_context.get("logo_url"))
print(f"_resolve_logo result:")
print(f"  logo_url: '{logo_url}'")
print(f"  logo_dimension_attrs: '{logo_dimension_attrs}'")
print(f"  embed_logo: {embed_logo}")

print(f"\n_email_logo_bytes(): {len(_email_logo_bytes())} bytes")

if embed_logo and not _email_logo_bytes():
    print(">>> FALLING BACK to hosted logo")
    logo_url, embed_logo = f"{frontend_base}/zoikopayroll-logo-light.png", False
    print(f"  New logo_url: '{logo_url}'")
    print(f"  New embed_logo: {embed_logo}")