import os
os.environ["STAGING_MODE"] = "true"
os.environ["STAGING_SANDBOX_EMAIL"] = "ravurirugvedh1@gmail.com"

# Import and check the SMTP settings directly
from app.config import settings as _staging_cfg
print("STAGING_MODE:", _staging_cfg.STAGING_MODE)
print("STAGING_SANDBOX_EMAIL:", _staging_cfg.STAGING_SANDBOX_EMAIL)
print("SMTP_HOST:", _staging_cfg.SMTP_HOST)
print("SMTP_PORT:", _staging_cfg.SMTP_PORT)

# Now check what _get_smtp_settings returns
from app.services.email_service import _get_smtp_settings
smtp = _get_smtp_settings()
print("\n_get_smtp_settings() result:")
print(f"  host: '{smtp['host']}'")
print(f"  port: {smtp['port']}")
print(f"  from_email: {smtp['from_email']}")