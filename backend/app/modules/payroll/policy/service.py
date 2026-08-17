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

from app.core.exceptions import NotFoundException, BadRequestException
from app.modules.payroll.policy.models import (
    PayrollPolicy, PolicyEmployeeCategory, PolicyLeaveRule,
    PolicyOvertimeRule, PolicyIntegration, PolicyAllowanceComponent,
    CalculationMode, EmployeeCategoryType, LeaveRuleType,
)
from app.modules.payroll.policy.schemas import PayrollPolicyUpdate
from app.modules.payroll.service import log_activity
from app.modules.payroll.models import ActivityStatus, CompanyComplianceDetails, JurisdictionPack


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
        selectinload(PayrollPolicy.allowance_components),
    )


def _resolve_policy_lock(db: Session, organization_id: int) -> dict:
    """The org's currently-assigned JurisdictionPack's policy_defaults, if
    any. Returns {} — "fully overridable" — when the org has no compliance
    pack assigned, or its pack never set policy_defaults, so every org that
    predates this locking mechanism (or simply isn't governed by a pack)
    behaves exactly as before.

    Deliberately does NOT cross-check the pack's jurisdiction_country
    against the org's own jurisdiction_country — no such validation exists
    anywhere else in this codebase (assign_pack_to_organizations() doesn't
    check it either), so "the org's applicable pack" is simply whatever
    CompanyComplianceDetails.active_pack_id currently points to.
    """
    details = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()
    if not details or not details.active_pack_id:
        return {}
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == details.active_pack_id).first()
    return (pack.policy_defaults or {}) if pack else {}


def _check_field_lock(locks: dict, path: tuple, value) -> None:
    """Raises if `path` (e.g. ("calculation_mode",) or
    ("employee_categories", "intern", "working_days")) is locked
    (allowOverride is False in `locks`) and `value` differs from the
    locked default. A no-op wherever `locks` doesn't mention this path at
    all — only fields Super Admin explicitly locked are enforced."""
    node = locks
    for key in path:
        if not isinstance(node, dict):
            return
        node = node.get(key)
        if node is None:
            return
    if not isinstance(node, dict) or node.get("allowOverride", True):
        return
    if value != node.get("value"):
        field_label = ".".join(str(p) for p in path)
        raise BadRequestException(
            f"'{field_label}' is locked by your organization's compliance policy "
            f"and must stay set to {node.get('value')!r}."
        )


def _apply_policy_defaults(policy: PayrollPolicy, locks: dict) -> None:
    """Force every locked field's value onto a freshly-seeded policy so a
    brand-new org under a governed jurisdiction starts compliant on day
    one, rather than only being enforced on its first edit.

    Also applies the Super Admin's default policy name and salary structure
    values (even when not locked) so the Org Admin sees the inherited
    values immediately — they can overwrite them freely unless locked."""
    if not locks:
        return
    # Policy name — inherit from the Super Admin's pack defaults if set.
    name_node = locks.get("name")
    if isinstance(name_node, dict) and name_node.get("value"):
        policy.name = name_node["value"]
    node = locks.get("calculation_mode")
    if isinstance(node, dict) and node.get("value") is not None:
        policy.calculation_mode = node["value"]
    for field in ("basic_pct", "hra_pct"):
        node = locks.get(field)
        if isinstance(node, dict) and node.get("value") is not None:
            setattr(policy, field, node["value"])


def _apply_category_policy_defaults(category_row: "PolicyEmployeeCategory", locks: dict) -> None:
    node = (locks.get("employee_categories") or {}).get(category_row.category)
    if not isinstance(node, dict):
        return
    for field in ("working_days", "expected_hours", "minimum_hours", "paid_leave_eligible", "grace_time_minutes"):
        field_node = node.get(field)
        if isinstance(field_node, dict) and field_node.get("value") is not None:
            setattr(category_row, field, field_node["value"])
    # Interns never get paid leave, regardless of any pack default — same
    # hard rule update_policy() enforces on every edit.
    if category_row.category == EmployeeCategoryType.INTERN.value:
        category_row.paid_leave_eligible = False


def _seed_allowance_components_from_defaults(db: Session, policy: PayrollPolicy, locks: dict) -> None:
    """Unlike employee categories (a fixed 6-value enum, always seeded),
    allowance components are entirely Super-Admin-defined — there is no
    default set at all. An org under a jurisdiction whose compliance pack
    defines components (policy_defaults["allowance_components"], a dict
    keyed by admin-typed slug — see PolicyAllowanceComponent's docstring)
    gets exactly those, seeded read-only or overridable per allowOverride.
    An org with no pack, or a pack that defines none, gets an empty list —
    zero behavior change from before this feature existed."""
    components = locks.get("allowance_components")
    if not isinstance(components, dict):
        return
    for key, node in components.items():
        if not isinstance(node, dict) or not isinstance(node.get("value"), dict):
            continue
        value = node["value"]
        db.add(PolicyAllowanceComponent(
            policy_id=policy.id, key=key,
            label=value.get("label") or key,
            pct=value.get("pct"), flat_amount=value.get("flat_amount"),
            allow_override=node.get("allowOverride", True),
        ))


def _check_allowance_component_lock(locks: dict, key: str, comp_data: dict) -> None:
    """Allowance components lock as a whole unit (one allowOverride per
    component), not per-field like _check_field_lock — a partially-locked
    allowance (e.g. pct fixed but label editable) isn't a real use case, and
    a single gate is simpler to reason about for something an org either
    can or can't customize. No-op if this key isn't mentioned in locks at
    all, matching _check_field_lock's same "unmentioned = unenforced"
    convention."""
    node = (locks.get("allowance_components") or {}).get(key)
    if not isinstance(node, dict) or node.get("allowOverride", True):
        return
    locked_value = node.get("value") or {}
    for field in ("label", "pct", "flat_amount"):
        submitted = comp_data.get(field)
        if submitted is not None and submitted != locked_value.get(field):
            raise BadRequestException(
                f"Allowance component '{key}' is locked by your organization's compliance policy and cannot be changed."
            )


def _apply_overtime_policy_defaults(overtime_row: "PolicyOvertimeRule", locks: dict) -> None:
    node = locks.get("overtime_rule")
    if not isinstance(node, dict):
        return
    for field in ("enabled", "minimum_overtime_minutes", "approval_required"):
        field_node = node.get(field)
        if isinstance(field_node, dict) and field_node.get("value") is not None:
            setattr(overtime_row, field, field_node["value"])


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

    # An org already governed by a compliance pack (assigned before this,
    # its very first, policy row is created) starts compliant immediately —
    # not just enforced on its first edit.
    locks = _resolve_policy_lock(db, organization_id)
    _apply_policy_defaults(policy, locks)

    for category, defaults in DEFAULT_CATEGORY_DEFAULTS.items():
        category_row = PolicyEmployeeCategory(policy_id=policy.id, category=category, **defaults)
        _apply_category_policy_defaults(category_row, locks)
        db.add(category_row)

    for rule_type in LeaveRuleType:
        db.add(PolicyLeaveRule(policy_id=policy.id, rule_type=rule_type.value, config={}))

    overtime_row = PolicyOvertimeRule(policy_id=policy.id, enabled=False, minimum_overtime_minutes=30, approval_required=True)
    _apply_overtime_policy_defaults(overtime_row, locks)
    db.add(overtime_row)

    for category, provider_key, enabled in DEFAULT_INTEGRATIONS:
        db.add(PolicyIntegration(policy_id=policy.id, category=category, provider_key=provider_key, enabled=enabled))

    _seed_allowance_components_from_defaults(db, policy, locks)

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
    # In-memory only (not a mapped column) — lets PayrollPolicyResponse
    # surface which fields the org's compliance pack has locked, without
    # a second round trip from the frontend.
    policy.policy_locks = _resolve_policy_lock(db, organization_id)
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
    allowance_updates = updates.pop("allowance_components", None)

    # Read-only validation pass — reject any field the org's assigned
    # compliance pack has explicitly locked (allowOverride=false) if the
    # client is trying to set it to something other than the locked value.
    # A no-op (locks == {}) for any org with no pack assigned, so this
    # changes nothing for every policy that predates jurisdiction packs.
    locks = _resolve_policy_lock(db, organization_id)
    if locks:
        for field, value in updates.items():
            _check_field_lock(locks, (field,), value)
        for cat_data in (category_updates or []):
            cat_key = cat_data.get("category")
            for field, value in cat_data.items():
                if field in ("category", "id"):
                    continue
                _check_field_lock(locks, ("employee_categories", cat_key, field), value)
        if overtime_update:
            for field, value in overtime_update.items():
                if field != "id" and value is not None:
                    _check_field_lock(locks, ("overtime_rule", field), value)
        for comp_data in (allowance_updates or []):
            _check_allowance_component_lock(locks, comp_data.get("key"), comp_data)

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

    if allowance_updates is not None:
        by_key = {c.key: c for c in policy.allowance_components}
        submitted_keys = {c["key"] for c in allowance_updates}
        # Delete components no longer present in the submitted list — guarded
        # against removing a locked one, since the client shouldn't have been
        # able to drop it from its payload in the first place.
        for key, existing in list(by_key.items()):
            if key in submitted_keys:
                continue
            node = (locks.get("allowance_components") or {}).get(key)
            if isinstance(node, dict) and not node.get("allowOverride", True):
                raise BadRequestException(
                    f"Allowance component '{key}' is locked by your organization's compliance policy and cannot be removed."
                )
            db.delete(existing)
        for comp_data in allowance_updates:
            comp_key = comp_data["key"]
            existing = by_key.get(comp_key)
            if existing:
                for field, value in comp_data.items():
                    if field != "key" and hasattr(existing, field):
                        setattr(existing, field, value)
            else:
                db.add(PolicyAllowanceComponent(policy_id=policy.id, **comp_data))

    # First explicit admin save unlocks the mandatory Payroll onboarding gate
    # (see useFilteredNavigation.js / payroll/index.jsx) — immutable once set,
    # so later edits don't need to touch it again.
    if policy.configured_at is None:
        policy.configured_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(policy)
    log_activity(db, organization_id, f"Payroll policy '{policy.name}' updated.", ActivityStatus.SUCCESS)
    policy.policy_locks = locks
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