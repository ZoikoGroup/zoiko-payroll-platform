"""
tests/privacy/conftest.py
-------------------------
Synthetic fixtures for ZP-PRIV-VERIFY-001 (no real personal data):

  tenants   A (code PRIVA) and B (code PRIVB), each with two legal entities
            and two pay groups
  workers   A1 (entity A-E1 / pay group A-PG1), A2 (A-E2 / A-PG2), B1
  identities
            SA   super_admin                 (platform)
            SP   support_operator            (platform)
            APP  platform_security approver  (platform)
            PS2  a second platform_security  (independent break-glass review)
            TA   org_admin of A
            TB   org_admin of B
            PA   payroll_admin of A, scoped to entity A-E1
            EA   employee persona of A1 (policy only; no self-service login)

Requests use REAL JWTs through the real auth chain - no dependency
overrides - so the PDP, the per-request DB re-check and the MFA claim check
all run. Privileged identities get tokens minted after a second factor
(``mfa_at``), exactly what /auth/mfa/challenge issues.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

import pytest


@dataclass
class World:
    db: object
    orgs: Dict[str, object] = field(default_factory=dict)
    entities: Dict[str, object] = field(default_factory=dict)
    groups: Dict[str, object] = field(default_factory=dict)
    employees: Dict[str, object] = field(default_factory=dict)
    users: Dict[str, object] = field(default_factory=dict)

    def token(self, who: str, *, mfa_at: int | None = None) -> str:
        from app.modules.auth.service import issue_access_token

        user = self.users[who]
        self.db.refresh(user)
        return issue_access_token(user, mfa_at=mfa_at if mfa_at is not None else int(time.time()))

    def headers(self, who: str, **kw) -> dict:
        return {"Authorization": f"Bearer {self.token(who, **kw)}"}

    def tenant_ids(self) -> dict:
        return {k: v.id for k, v in self.orgs.items()}


def _user(db, email, role, organization_id=None, **extra):
    from app.core.security import hash_password
    from app.modules.auth.models import User, UserRole

    user = User(email=email, hashed_password=hash_password("Priv-Test-Password-1!"),
                role=getattr(UserRole, role.upper()), organization_id=organization_id,
                first_name=role, last_name="Synthetic", is_active=True, is_verified=True, **extra)
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def world(db) -> World:
    from app.modules.organizations.models import (
        LegalEntity,
        Organization,
        PayGroup,
        UserScopeAssignment,
    )
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.super_admin import aggregates

    aggregates.reset_guard_state()
    w = World(db=db)
    for key, code in (("A", "PRIVA"), ("B", "PRIVB")):
        org = Organization(organization_name=f"Tenant {key}", organization_code=code,
                           workspace_type="EVALUATION", is_active=True)
        db.add(org)
        db.flush()
        w.orgs[key] = org
        for n in (1, 2):
            ent = LegalEntity(organization_id=org.id, name=f"{key} Entity {n}", country="GB")
            db.add(ent)
            db.flush()
            w.entities[f"{key}-E{n}"] = ent
            grp = PayGroup(organization_id=org.id, legal_entity_id=ent.id, name=f"{key} Group {n}")
            db.add(grp)
            db.flush()
            w.groups[f"{key}-PG{n}"] = grp

    def emp(key, org_key, n, code):
        e = PayrollEmployee(
            organization_id=w.orgs[org_key].id, employee_code=code, name=f"Synthetic Worker {key}",
            email=f"{key.lower()}@worker.example", phone="+440000000000",
            legal_entity_id=w.entities[f"{org_key}-E{n}"].id, pay_group_id=w.groups[f"{org_key}-PG{n}"].id,
            ctc=60000, basic=30000, hra=0, bank_account="GB00SYNTH12345678", pan="SYNTHPAN01",
            date_of_birth=None, address_line1="1 Synthetic Street", tax_code="1257L",
        )
        db.add(e)
        db.flush()
        w.employees[key] = e

    emp("A1", "A", 1, "A-0001")
    emp("A2", "A", 2, "A-0002")
    emp("B1", "B", 1, "B-0001")

    w.users["SA"] = _user(db, "sa@platform.example", "super_admin")
    w.users["SP"] = _user(db, "sp@platform.example", "support_operator")
    w.users["APP"] = _user(db, "app@platform.example", "platform_security")
    w.users["PS2"] = _user(db, "ps2@platform.example", "platform_security")
    w.users["TA"] = _user(db, "ta@tenant-a.example", "org_admin", w.orgs["A"].id)
    w.users["TB"] = _user(db, "tb@tenant-b.example", "org_admin", w.orgs["B"].id)
    w.users["PA"] = _user(db, "pa@tenant-a.example", "payroll_admin", w.orgs["A"].id)
    w.users["EA"] = _user(db, "ea@tenant-a.example", "employee", w.orgs["A"].id,
                          self_service_employee_id=w.employees["A1"].id)
    db.add(UserScopeAssignment(user_id=w.users["PA"].id, organization_id=w.orgs["A"].id,
                               legal_entity_id=w.entities["A-E1"].id))
    db.commit()
    return w


@pytest.fixture()
def client(db):
    """The real app with only the database swapped for the test SQLite."""
    from fastapi.testclient import TestClient

    from app.core.rate_limiter import limiter
    from app.database import get_db
    from app.main import app

    # The login rate limit is process-wide; each test starts from a clean
    # window (the limit itself is unchanged).
    limiter.reset()
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        limiter.reset()  # leave no login-rate state for the next test file
