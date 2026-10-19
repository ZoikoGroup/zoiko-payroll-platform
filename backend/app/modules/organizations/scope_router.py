"""
modules/organizations/scope_router.py
-------------------------------------
Tenant scoping administration (ZP-PRIV B02 / C.1 / C.3), org admins only:

  GET/POST  /api/organization-admin/pay-groups
  PUT       /api/organization-admin/pay-groups/{pay_group_id}
  GET/PUT   /api/organization-admin/users/{user_id}/scope
  PUT       /api/organization-admin/employees/{employee_id}/placement

A payroll admin with scope assignments sees ONLY the workers of the
assigned legal entities / pay groups (core/authz/scopes.py); one with none is
organization-wide. Every id in a request is checked against the caller's own
organization (404 otherwise) - the organization itself always comes from the
login.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin
from app.core.exceptions import AlreadyExistsException, BadRequestException, NotFoundException
from app.database import get_db

router = APIRouter(prefix="/organization-admin", tags=["Organization scoping"])


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PayGroupBody(_Camel):
    name: str = Field(..., min_length=1, max_length=120)
    legal_entity_id: Optional[int] = Field(None, alias="legalEntityId")
    is_active: bool = Field(True, alias="isActive")


class ScopeBody(_Camel):
    legal_entity_ids: List[int] = Field(default_factory=list, alias="legalEntityIds")
    pay_group_ids: List[int] = Field(default_factory=list, alias="payGroupIds")


class PlacementBody(_Camel):
    legal_entity_id: Optional[int] = Field(None, alias="legalEntityId")
    pay_group_id: Optional[int] = Field(None, alias="payGroupId")


def _z(value: Optional[datetime]) -> Optional[str]:
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


def _group_view(g) -> dict:
    return {"id": g.id, "name": g.name, "legalEntityId": g.legal_entity_id, "isDefault": g.is_default,
            "isActive": g.is_active, "createdAt": _z(g.created_at)}


def _own_entity(db: Session, org_id: int, entity_id: Optional[int]):
    from app.modules.organizations.models import LegalEntity

    if entity_id is None:
        return None
    row = db.query(LegalEntity).filter(LegalEntity.id == entity_id).first()
    if row is None or row.organization_id != org_id:
        raise NotFoundException("Legal entity")
    return row


def _own_group(db: Session, org_id: int, group_id: Optional[int]):
    from app.modules.organizations.models import PayGroup

    if group_id is None:
        return None
    row = db.query(PayGroup).filter(PayGroup.id == group_id).first()
    if row is None or row.organization_id != org_id:
        raise NotFoundException("Pay group")
    return row


@router.get("/pay-groups", summary="Your organization's pay groups")
def list_pay_groups(current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.organizations.models import PayGroup

    rows = (db.query(PayGroup).filter(PayGroup.organization_id == current_user.organization_id)
            .order_by(PayGroup.name).all())
    return [_group_view(g) for g in rows]


@router.post("/pay-groups", summary="Create a pay group")
def create_pay_group(body: PayGroupBody, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.modules.organizations.models import PayGroup

    org = current_user.organization_id
    _own_entity(db, org, body.legal_entity_id)
    if db.query(PayGroup).filter(PayGroup.organization_id == org, PayGroup.name == body.name.strip()).first():
        raise AlreadyExistsException("Pay group", "name")
    group = PayGroup(organization_id=org, legal_entity_id=body.legal_entity_id, name=body.name.strip(),
                     is_active=body.is_active)
    db.add(group)
    db.commit()
    db.refresh(group)
    return _group_view(group)


@router.put("/pay-groups/{pay_group_id}", summary="Rename, re-home or deactivate a pay group")
def update_pay_group(pay_group_id: int, body: PayGroupBody, current_user=Depends(get_current_org_admin),
                     db: Session = Depends(get_db)):
    org = current_user.organization_id
    group = _own_group(db, org, pay_group_id)
    _own_entity(db, org, body.legal_entity_id)
    group.name = body.name.strip()
    group.legal_entity_id = body.legal_entity_id
    group.is_active = body.is_active
    db.commit()
    return _group_view(group)


@router.get("/users/{user_id}/scope", summary="A team member's entity / pay-group scope")
def get_user_scope(user_id: int, current_user=Depends(get_current_org_admin), db: Session = Depends(get_db)):
    from app.core.authz.scopes import assigned_scope

    _team_member(db, current_user, user_id)
    entities, groups = assigned_scope(db, user_id, current_user.organization_id)
    return {"userId": user_id, "legalEntityIds": sorted(entities), "payGroupIds": sorted(groups),
            "organizationWide": not entities and not groups}


def _team_member(db: Session, admin, user_id: int):
    from app.modules.auth.models import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or user.organization_id != admin.organization_id or user.is_temporary:
        raise NotFoundException("User")
    return user


@router.put("/users/{user_id}/scope", summary="Replace a payroll admin's entity / pay-group scope")
def set_user_scope(user_id: int, body: ScopeBody, current_user=Depends(get_current_org_admin),
                   db: Session = Depends(get_db)):
    from app.modules.organizations.models import UserScopeAssignment

    org = current_user.organization_id
    user = _team_member(db, current_user, user_id)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "payroll_admin" and (body.legal_entity_ids or body.pay_group_ids):
        raise BadRequestException("Scope applies to payroll admins; organization admins are always organization-wide.")
    for eid in body.legal_entity_ids:
        _own_entity(db, org, eid)
    for gid in body.pay_group_ids:
        _own_group(db, org, gid)
    db.query(UserScopeAssignment).filter(UserScopeAssignment.user_id == user_id).delete(synchronize_session=False)
    for eid in sorted(set(body.legal_entity_ids)):
        db.add(UserScopeAssignment(user_id=user_id, organization_id=org, legal_entity_id=eid,
                                   created_by_user_id=current_user.id))
    for gid in sorted(set(body.pay_group_ids)):
        db.add(UserScopeAssignment(user_id=user_id, organization_id=org, pay_group_id=gid,
                                   created_by_user_id=current_user.id))
    db.commit()
    return get_user_scope(user_id, current_user, db)


@router.put("/employees/{employee_id}/placement", summary="Place a worker in a legal entity and pay group")
def set_employee_placement(employee_id: int, body: PlacementBody, current_user=Depends(get_current_org_admin),
                           db: Session = Depends(get_db)):
    from app.core.authz.principal import principal_from_user
    from app.core.authz.scopes import tenant_scoped
    from app.modules.payroll.models import PayrollEmployee

    org = current_user.organization_id
    employee = (tenant_scoped(db, PayrollEmployee, principal_from_user(current_user))
                .filter(PayrollEmployee.id == employee_id).first())
    if employee is None:
        raise NotFoundException("Employee")
    _own_entity(db, org, body.legal_entity_id)
    group = _own_group(db, org, body.pay_group_id)
    if group is not None and group.legal_entity_id and body.legal_entity_id and \
            group.legal_entity_id != body.legal_entity_id:
        raise BadRequestException("That pay group belongs to a different legal entity.")
    employee.legal_entity_id = body.legal_entity_id
    employee.pay_group_id = body.pay_group_id
    db.commit()
    return {"employeeId": employee.id, "legalEntityId": employee.legal_entity_id, "payGroupId": employee.pay_group_id}
