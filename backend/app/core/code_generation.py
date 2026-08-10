"""
core/code_generation.py
-----------------------
Code generators for the standalone Payroll Platform — a slimmed copy of
the main platform's core/code_generation.py holding only what the Payroll
module uses (generate_business_code, generate_employee_code,
derive_organization_code, generate_organization_code, get_org_code).

References the platform's OWN Organization model (modules/organizations),
never app.modules.hr.models. The old generate_employee_code counted both
the HR Employee table and payroll's table; here payroll's table is the
only employee master, so only it is counted.
"""

import re
from datetime import datetime
from typing import Optional, Type

from sqlalchemy import text
from sqlalchemy.orm import Session


def derive_organization_code(name: str) -> str:
    """Derive 2-letter org code from org name (same rules as main platform)."""
    alpha_only = re.sub(r"[^A-Za-z]", "", name or "")
    if len(alpha_only) >= 2:
        return alpha_only[:2].upper()
    if len(alpha_only) == 1:
        return (alpha_only + "X").upper()
    return "OR"


def generate_organization_code(name: str, db: Session) -> str:
    """Generate a 2-letter organization code from name, deduplicated."""
    from app.modules.organizations.models import Organization

    base_code = derive_organization_code(name)
    code = base_code
    suffix = 1
    while db.query(Organization).filter(Organization.organization_code == code).first():
        code = f"{base_code}{suffix}"
        suffix += 1
    return code


def generate_employee_code(db: Session, organization_id: int) -> str:
    """Generate employee code: {OrgCode}E{seq:05d}.

    In the standalone platform the payroll employee table is the only
    employee master, so the sequence counts from it alone (the old version
    counted both HR Employee and payroll rows).
    """
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import PayrollEmployee

    db.execute(
        text("SELECT pg_advisory_xact_lock(:org_key)"),
        {"org_key": organization_id + 9000000},
    )

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org_code = org.organization_code if org and org.organization_code else "UNK"

    payroll_count = db.query(PayrollEmployee.id).filter(
        PayrollEmployee.organization_id == organization_id,
        PayrollEmployee.employee_code.isnot(None),
        PayrollEmployee.employee_code.like(f"{org_code}E%"),
    ).count()

    return f"{org_code}E{payroll_count + 1:05d}"


def generate_business_code(
    db: Session,
    organization_id: int,
    prefix: str,
    table: Type,
    code_column: str,
    date_format: Optional[str] = None,
    seq_width: int = 3,
) -> str:
    """Generic per-org business code generator (same contract as the main
    platform's, but resolving the org code from our own Organization table)."""
    from app.modules.organizations.models import Organization

    db.execute(
        text("SELECT pg_advisory_xact_lock(:org_key)"),
        {"org_key": organization_id + 8000000 + hash(prefix) % 1000000},
    )

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org_code = org.organization_code if org and org.organization_code else "UNK"

    date_part = ""
    if date_format:
        date_part = datetime.now().strftime(date_format)

    prefix_pattern = f"{org_code}{prefix}{date_part}%"
    count = db.query(table).filter(
        table.organization_id == organization_id,
        getattr(table, code_column).like(prefix_pattern),
    ).count()

    return f"{org_code}{prefix}{date_part}{(count + 1):0{seq_width}d}"


def get_org_code(db: Session, organization_id: int) -> str:
    """Get the organization abbreviation code, or 'UNK' if not found."""
    from app.modules.organizations.models import Organization

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    return org.organization_code if org and org.organization_code else "UNK"
