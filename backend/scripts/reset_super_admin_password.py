"""
scripts/reset_super_admin_password.py
--------------------------------------
Resets the password of an EXISTING Super Admin account. Requires SETUP_KEY
in the environment (same guard as seed_super_admin.py). The target user
must already exist with role=super_admin.

Usage:
    set SETUP_KEY=your-setup-key
    set PAYROLL_SUPER_ADMIN_EMAIL=admin@example.com
    set PAYROLL_SUPER_ADMIN_PASSWORD=new-strong-password
    python -m scripts.reset_super_admin_password
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import hash_password
from app.database import SessionLocal
from app.modules.auth.models import User, UserRole

SETUP_KEY = os.environ.get("SETUP_KEY", "").strip()
EMAIL = os.environ.get("PAYROLL_SUPER_ADMIN_EMAIL", "").strip()
PASSWORD = os.environ.get("PAYROLL_SUPER_ADMIN_PASSWORD", "").strip()


def main() -> None:
    if not SETUP_KEY:
        sys.exit("ERROR: SETUP_KEY environment variable is required to reset a Super Admin password.")
    if not EMAIL or not PASSWORD:
        sys.exit("ERROR: PAYROLL_SUPER_ADMIN_EMAIL and PAYROLL_SUPER_ADMIN_PASSWORD are required.")
    if len(PASSWORD) < 8:
        sys.exit("ERROR: PAYROLL_SUPER_ADMIN_PASSWORD must be at least 8 characters.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.email == EMAIL, User.role == UserRole.SUPER_ADMIN
        ).first()
        if not user:
            sys.exit(f"ERROR: no super_admin user found with email {EMAIL}.")

        user.hashed_password = hash_password(PASSWORD)
        db.commit()
        print(f"Super Admin password reset: {EMAIL}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
