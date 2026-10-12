"""
scripts/rehash_hk_identity_tokens.py
------------------------------------
Re-derives legacy (v1, unkeyed SHA-256) Hong Kong identity tokens on
``payroll_employee_statutory_profiles.hk_identity_token`` as the keyed,
versioned v2 token (gap-closure D-19, ``hong_kong_service.identity_token``).

* DRY RUN by default: reports what would change and writes nothing.
* ``--write`` applies the change. Each re-derived row is audited.
* Refuses non-local databases (scripts/_local_db_guard). A production run needs
  the owner's explicit ZOIKO_ALLOW_NONLOCAL_DB_WRITES override, and must use the
  production HK_IDENTITY_TOKEN_KEY.
* The raw HKID / passport is read from the employee's compliance fields and is
  never printed. A token that is not reproducible from the current identifier
  (the identifier changed) is reported and left untouched.

* ``--rotate`` (key rotation, release-closure audit): also re-derives v2 tokens
  that were keyed with a PREVIOUS ``HK_IDENTITY_TOKEN_KEY``. The current
  identifier is the source of truth; the old key is not needed. Dry run unless
  ``--write`` is also given.

Nothing looks a worker up by this token, so re-deriving it changes no lookup.

Usage (from backend/):
  PAYROLL_DATABASE_URL=sqlite:///<scratch>.db python -m scripts.rehash_hk_identity_tokens
  PAYROLL_DATABASE_URL=sqlite:///<scratch>.db python -m scripts.rehash_hk_identity_tokens --write
  PAYROLL_DATABASE_URL=sqlite:///<scratch>.db python -m scripts.rehash_hk_identity_tokens --rotate [--write]
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._local_db_guard import assert_local_database  # noqa: E402


def rehash(db, write: bool = False, rotate: bool = False) -> dict:
    from app.modules.payroll.hong_kong_service import identity_token, identity_token_version
    from app.modules.payroll.models import EmployeeStatutoryProfile, PayrollEmployee
    from app.modules.payroll.service import record_tax_audit

    summary = {"examined": 0, "legacy": 0, "rederived": 0, "notReproducible": 0, "staleKey": 0,
               "write": write, "rotate": rotate}
    rows = (db.query(EmployeeStatutoryProfile)
            .filter(EmployeeStatutoryProfile.country_code == "HK", EmployeeStatutoryProfile.hk_identity_token.isnot(None))
            .all())
    for profile in rows:
        summary["examined"] += 1
        version = identity_token_version(profile.hk_identity_token)
        if version == "v2" and rotate:
            employee = db.get(PayrollEmployee, profile.employee_id)
            cf = (employee.compliance_fields or {}) if employee else {}
            ident = (cf.get("hkid") if profile.hk_identity_document_type != "PASSPORT" else cf.get("passport_number"))
            if not ident:
                summary["notReproducible"] += 1
                continue
            current = identity_token(ident)
            if current == profile.hk_identity_token:
                continue                                   # already keyed with the current key
            summary["staleKey"] += 1
            if write:
                profile.hk_identity_token = current
                record_tax_audit(db, actor_id=None, action="update", entity_type="employee_statutory_profile",
                                 entity_id=profile.id, legal_reference="D-19 keyed HK identity token",
                                 old_value={"tokenVersion": "v2", "key": "previous"},
                                 new_value={"tokenVersion": "v2", "key": "current"},
                                 reason="re-key identity token after HK_IDENTITY_TOKEN_KEY rotation", auto_commit=False)
            continue
        if version != "v1":
            continue
        summary["legacy"] += 1
        employee = db.get(PayrollEmployee, profile.employee_id)
        cf = (employee.compliance_fields or {}) if employee else {}
        ident = (cf.get("hkid") if profile.hk_identity_document_type != "PASSPORT" else cf.get("passport_number"))
        if not ident or hashlib.sha256(str(ident).upper().encode()).hexdigest() != profile.hk_identity_token:
            summary["notReproducible"] += 1
            continue
        summary["rederived"] += 1
        if write:
            profile.hk_identity_token = identity_token(ident)
            record_tax_audit(db, actor_id=None, action="update", entity_type="employee_statutory_profile",
                             entity_id=profile.id, legal_reference="D-19 keyed HK identity token",
                             old_value={"tokenVersion": "v1"}, new_value={"tokenVersion": "v2"},
                             reason="re-derive legacy identity token", auto_commit=False)
    if write:
        db.commit()
    return summary


def main() -> None:
    assert_local_database("rehash_hk_identity_tokens")
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        print(rehash(db, write="--write" in sys.argv, rotate="--rotate" in sys.argv))
    finally:
        db.close()


if __name__ == "__main__":
    main()
