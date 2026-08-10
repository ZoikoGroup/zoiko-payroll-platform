"""
modules/payroll/policy/service.py
------------------------------------
Business logic for Payroll Policy Management.

Mirrors the get-or-create convention already used in
app/modules/payroll/service.py (see get_company_details) so an organization
that has never configured a policy transparently gets a default one that
matches TODAY'S production behavior — zero behavior change until an admin
explicitly edits it.
"""

from typing import Optional
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.exceptions import NotFoundException
from app.modules.payroll.policy.models import (
    PayrollPolicy, PolicyEmployeeCategory, PolicyLeaveRule,
    PolicyOvertimeRule, PolicyIntegration,
    CalculationMode, EmployeeCategoryType, LeaveRuleType,
)
from app.modules.payroll.policy.schemas import PayrollPolicyUpdate
from app.modules.payroll.service import log_activity
from app.modules.payroll.models import ActivityStatus


# Mirrors current hardcoded production behavior exactly — this is what gets
# seeded for every organization that has never touched policy settings.
DEFAULT_INTEGRATIONS = [
    ("attendance", "zoiko_time", True), ("attendance", "manual_attendance", True),
    ("attendance", "csv_import", True), ("attendance", "biometric", False),
    ("banking", "manual_transfer", True), ("banking", "excel_export", True),
    ("banking", "csv_export", True), ("banking", "bank_api", False),
    ("notifications", "email", True), ("notifications", "sms", False),
    ("notifications", "whatsapp", False), ("notifications", "slack", False),
    ("notifications", "teams", False),
]

DEFAULT_CATEGORY_DEFAULTS = {
    EmployeeCategoryType.FULL_TIME.value:  dict(working_days=5, expected_hours=8, minimum_hours=4, paid_leave_eligible=True),
    EmployeeCategoryType.PART_TIME.value:  dict(working_days=5, expected_hours=4, minimum_hours=2, paid_leave_eligible=True),
    EmployeeCategoryType.INTERN.value:     dict(working_days=5, expected_hours=8, minimum_hours=4, paid_leave_eligible=False),  # never paid leave
    EmployeeCategoryType.CONTRACT.value:   dict(working_days=5, expected_hours=8, minimum_hours=4, paid_leave_eligible=False),
    EmployeeCategoryType.CONSULTANT.value: dict(working_days=5, expected_hours=8, minimum_hours=0, paid_leave_eligible=False),
    EmployeeCategoryType.FREELANCER.value: dict(working_days=0, expected_hours=0, minimum_hours=0, paid_leave_eligible=False),
}


def _policy_query(db: Session):
    # employee_categories/leave_rules/integrations are one-to-many —
    # joinedload-ing all three together in one query produces a cartesian
    # product (~6 x 5 x 13 rows to hydrate ~25 real related rows). selectinload
    # runs them as separate small IN-queries instead, no row multiplication.
    # overtime_rule is a true one-to-one (uselist=False), so joinedload for
    # it alone has no such risk.
    return db.query(PayrollPolicy).options(
        selectinload(PayrollPolicy.employee_categories),
        selectinload(PayrollPolicy.leave_rules),
        joinedload(PayrollPolicy.overtime_rule),
        selectinload(PayrollPolicy.integrations),
    )


def _seed_default_policy(db: Session, organization_id: int) -> PayrollPolicy:
    policy = PayrollPolicy(
        organization_id=organization_id,
        name="Default Policy",
        description="Auto-created default policy — matches pre-policy production behavior.",
        status="active",
        is_default=True,
        calculation_mode=CalculationMode.STANDARD.value,
        effective_date=date.today(),
    )
    db.add(policy)
    db.flush()  # get policy.id without committing yet

    for category, defaults in DEFAULT_CATEGORY_DEFAULTS.items():
        db.add(PolicyEmployeeCategory(policy_id=policy.id, category=category, **defaults))

    for rule_type in LeaveRuleType:
        db.add(PolicyLeaveRule(policy_id=policy.id, rule_type=rule_type.value, config={}))

    db.add(PolicyOvertimeRule(policy_id=policy.id, enabled=False, minimum_overtime_minutes=30, approval_required=True))

    for category, provider_key, enabled in DEFAULT_INTEGRATIONS:
        db.add(PolicyIntegration(policy_id=policy.id, category=category, provider_key=provider_key, enabled=enabled))

    db.commit()
    db.refresh(policy)
    return policy


def get_active_policy(db: Session, organization_id: int) -> PayrollPolicy:
    """Get-or-create, matching the existing get_company_details() convention.

    Called by generate_payslips_for_run() before every run (Step 3) — if this
    is the first time an org touches policy, it transparently gets a default
    policy that reproduces today's exact behavior.
    """
    policy = (
        _policy_query(db)
        .filter(PayrollPolicy.organization_id == organization_id, PayrollPolicy.is_default == True)  # noqa: E712
        .first()
    )
    if not policy:
        policy = _seed_default_policy(db, organization_id)
    return policy


def get_policy_by_id(db: Session, policy_id: int, organization_id: int) -> PayrollPolicy:
    policy = (
        _policy_query(db)
        .filter(PayrollPolicy.id == policy_id, PayrollPolicy.organization_id == organization_id)
        .first()
    )
    if not policy:
        raise NotFoundException("PayrollPolicy", policy_id)
    return policy


def update_policy(db: Session, policy_id: int, data: PayrollPolicyUpdate, organization_id: int) -> PayrollPolicy:
    policy = get_policy_by_id(db, policy_id, organization_id)

    updates = data.model_dump(exclude_unset=True, by_alias=False)
    category_updates = updates.pop("employee_categories", None)
    overtime_update = updates.pop("overtime_rule", None)

    for field, value in updates.items():
        if hasattr(policy, field):
            setattr(policy, field, value)

    if category_updates:
        by_category = {c.category: c for c in policy.employee_categories}
        for cat_data in category_updates:
            cat_key = cat_data["category"]
            # Hard rule: interns can never be granted paid leave, regardless of
            # what the client sends — enforced server-side, not just in the UI.
            if cat_key == EmployeeCategoryType.INTERN.value:
                cat_data["paid_leave_eligible"] = False
            existing = by_category.get(cat_key)
            if existing:
                for field, value in cat_data.items():
                    if hasattr(existing, field):
                        setattr(existing, field, value)
            else:
                db.add(PolicyEmployeeCategory(policy_id=policy.id, **cat_data))

    if overtime_update:
        ot = policy.overtime_rule
        if ot:
            for field, value in overtime_update.items():
                if value is not None and hasattr(ot, field):
                    setattr(ot, field, value)
        else:
            db.add(PolicyOvertimeRule(policy_id=policy.id, **{k: v for k, v in overtime_update.items() if v is not None}))

    # First explicit admin save unlocks the mandatory Payroll onboarding gate
    # (see useFilteredNavigation.js / payroll/index.jsx) — immutable once set,
    # so later edits don't need to touch it again.
    if policy.configured_at is None:
        policy.configured_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(policy)
    log_activity(db, organization_id, f"Payroll policy '{policy.name}' updated.", ActivityStatus.SUCCESS)
    return policy


def set_integration_enabled(
    db: Session, policy_id: int, category: str, provider_key: str,
    enabled: bool, organization_id: int,
) -> PolicyIntegration:
    policy = get_policy_by_id(db, policy_id, organization_id)  # enforces org scoping

    row = (
        db.query(PolicyIntegration)
        .filter(
            PolicyIntegration.policy_id == policy.id,
            PolicyIntegration.category == category,
            PolicyIntegration.provider_key == provider_key,
        )
        .first()
    )
    if not row:
        raise NotFoundException("PolicyIntegration", f"{category}/{provider_key}")

    row.enabled = enabled
    db.commit()
    db.refresh(row)
    action = "enabled" if enabled else "disabled"
    log_activity(
        db, organization_id,
        f"Integration '{provider_key}' ({category}) {action} on policy '{policy.name}'.",
        ActivityStatus.SUCCESS,
    )
    return row