"""
modules/payroll/hierarchy/service.py
--------------------------------------
Read-side composition for the new jurisdiction/tax hierarchy engine.

resolve_applicable_compliance_configuration() is the ONE canonical
resolver meant to back every UI surface that needs to answer "what
compliance configuration applies to this organization" — Super Admin
Compliance, Organization Admin Compliance, and (once the payroll engine
is wired up in a later phase) payroll calculation itself. It does not
resolve rates itself; it composes engine.tax_resolver_v2.resolve_tax_version
(the one place per-tax resolution logic actually lives) with the org's
jurisdiction assignments and its approved overrides, so this function can
never disagree with what the engine actually used — the same guarantee
_pack_to_tax_snapshot already gives the old system.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import List, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.modules.payroll.engine.tax_resolver_v2 import (
    activate_tax_version, list_applicable_tax_codes, resolve_tax_version,
)
from app.modules.payroll.hierarchy.models import (
    Country, Jurisdiction, JurisdictionLevel, OrganizationJurisdictionAssignment,
    OrganizationTaxOverride, Tax, TaxParameter, TaxRule, TaxRuleRate, TaxRuleSlab,
    TaxVersion, TaxVersionAudit,
)


def _jurisdiction_chain(db: Session, jurisdiction_id: int) -> list:
    """Most-specific -> root, e.g. [Telangana, India]. Used both for
    resolution (tax_resolver_v2 walks the same chain independently) and
    for display (so the UI can show which level actually supplied each
    tax, per the "layering" requirement)."""
    chain = []
    current = db.query(Jurisdiction).filter(Jurisdiction.id == jurisdiction_id).first()
    while current is not None:
        chain.append(current)
        current = (
            db.query(Jurisdiction).filter(Jurisdiction.id == current.parent_jurisdiction_id).first()
            if current.parent_jurisdiction_id else None
        )
    return chain


def resolve_applicable_compliance_configuration(
    db: Session, organization_id: int, payroll_date: Optional[date_cls] = None,
) -> dict:
    """Returns a dict shaped like:
    {
      "organization_id": ..., "payroll_date": ...,
      "jurisdiction_assignments": [ {id, jurisdiction_id, jurisdiction_name,
                                       level_code, assignment_type, status}, ... ],
      "applicable_taxes": [
        {
          "tax_code", "tax_name", "category",
          "resolved_from": {jurisdiction_id, jurisdiction_name, level_code},
          "tax_version": {id, version_label, tax_year, tax_regime, status,
                           effective_from, effective_to},
          "rules": [ {id, rule_type, label, sort_order,
                       slabs: [...], rates: [...] } ],
          "parameters": [ {id, parameter_key, label, value_numeric,
                             value_text, unit, effective_value, overridden} ],
          "active_overrides": [ {id, status, reason, ...} ],
        }, ...
      ],
    }

    Composition only — every rate/slab/parameter number returned here
    comes straight from whatever engine.tax_resolver_v2.resolve_tax_version
    resolved; nothing is recomputed here.
    """
    as_of = payroll_date or date_cls.today()

    assignments = (
        db.query(OrganizationJurisdictionAssignment)
        .filter(
            OrganizationJurisdictionAssignment.organization_id == organization_id,
            OrganizationJurisdictionAssignment.status.in_(("configured", "verified", "active")),
        )
        .all()
    )

    assignment_views = []
    applicable_taxes = []
    seen_tax_version_ids = set()

    for assignment in assignments:
        chain = _jurisdiction_chain(db, assignment.jurisdiction_id)
        primary_node = chain[0] if chain else None
        assignment_views.append({
            "id": assignment.id,
            "jurisdiction_id": assignment.jurisdiction_id,
            "jurisdiction_name": primary_node.name if primary_node else None,
            "assignment_type": assignment.assignment_type,
            "status": assignment.status,
            "effective_from": assignment.effective_from,
            "effective_to": assignment.effective_to,
        })

        for tax_code in list_applicable_tax_codes(db, assignment.jurisdiction_id):
            version = resolve_tax_version(
                db, assignment.jurisdiction_id, tax_code,
                tax_regime=assignment.tax_regime, payroll_date=as_of,
            )
            if not version or version.id in seen_tax_version_ids:
                # Already resolved (e.g. two assignments sharing an
                # ancestor) or nothing Active for this tax at this date —
                # skip rather than show a duplicate or an empty entry.
                continue
            seen_tax_version_ids.add(version.id)

            tax_row = db.query(Tax).filter(Tax.id == version.tax_id).first()
            resolved_jurisdiction = db.query(Jurisdiction).filter(Jurisdiction.id == version.jurisdiction_id).first()

            rules = (
                db.query(TaxRule).filter(TaxRule.tax_version_id == version.id).order_by(TaxRule.sort_order).all()
            )
            rule_views = []
            for rule in rules:
                slabs = (
                    db.query(TaxRuleSlab).filter(TaxRuleSlab.tax_rule_id == rule.id).order_by(TaxRuleSlab.sort_order).all()
                )
                rates = db.query(TaxRuleRate).filter(TaxRuleRate.tax_rule_id == rule.id).all()
                rule_views.append({
                    "id": rule.id, "rule_type": rule.rule_type, "label": rule.label,
                    "sort_order": rule.sort_order, "formula_expression": rule.formula_expression,
                    "slabs": [
                        {"id": s.id, "min_amount": s.min_amount, "max_amount": s.max_amount,
                         "rate_pct": s.rate_pct, "flat_fee_amount": s.flat_fee_amount, "rate_label": s.rate_label}
                        for s in slabs
                    ],
                    "rates": [
                        {"id": r.id, "employee_rate_pct": r.employee_rate_pct, "employer_rate_pct": r.employer_rate_pct,
                         "employee_flat_amount": r.employee_flat_amount, "employer_flat_amount": r.employer_flat_amount}
                        for r in rates
                    ],
                })

            parameters = db.query(TaxParameter).filter(TaxParameter.tax_version_id == version.id).all()
            overrides = (
                db.query(OrganizationTaxOverride)
                .filter(
                    OrganizationTaxOverride.organization_id == organization_id,
                    OrganizationTaxOverride.tax_version_id == version.id,
                    OrganizationTaxOverride.status != "expired",
                    OrganizationTaxOverride.status != "withdrawn",
                )
                .all()
            )
            override_by_rule = {o.tax_rule_id: o for o in overrides if o.tax_rule_id}
            override_by_param = {o.tax_parameter_id: o for o in overrides if o.tax_parameter_id}

            parameter_views = []
            for param in parameters:
                override = override_by_param.get(param.id)
                effective_value = param.value_numeric
                overridden = False
                if override and override.status == "approved" and override.override_value_numeric is not None:
                    effective_value = override.override_value_numeric
                    overridden = True
                parameter_views.append({
                    "id": param.id, "parameter_key": param.parameter_key, "label": param.label,
                    "value_numeric": param.value_numeric, "value_text": param.value_text, "unit": param.unit,
                    "effective_value": effective_value, "overridden": overridden,
                })

            active_override_views = [
                {"id": o.id, "status": o.status, "reason": o.reason,
                 "tax_rule_id": o.tax_rule_id, "tax_parameter_id": o.tax_parameter_id}
                for o in overrides
            ]

            applicable_taxes.append({
                "tax_code": tax_row.tax_code if tax_row else tax_code,
                "tax_name": tax_row.name if tax_row else tax_code,
                "category": tax_row.category if tax_row else None,
                "resolved_from": {
                    "jurisdiction_id": version.jurisdiction_id,
                    "jurisdiction_name": resolved_jurisdiction.name if resolved_jurisdiction else None,
                    "level_id": resolved_jurisdiction.level_id if resolved_jurisdiction else None,
                },
                "tax_version": {
                    "id": version.id, "version_label": version.version_label, "tax_year": version.tax_year,
                    "tax_regime": version.tax_regime, "status": version.status,
                    "effective_from": version.effective_from, "effective_to": version.effective_to,
                },
                "configuration_source": "organization_override" if override_by_rule or any(
                    p["overridden"] for p in parameter_views
                ) else "platform_managed",
                "rules": rule_views,
                "parameters": parameter_views,
                "active_overrides": active_override_views,
            })

    return {
        "organization_id": organization_id,
        "payroll_date": as_of,
        "jurisdiction_assignments": assignment_views,
        "applicable_taxes": applicable_taxes,
    }


# ── Audit ────────────────────────────────────────────────────────────────
# Separate table from the old TaxConfigurationAudit (payroll/service.py) —
# the two coexist permanently, one per system, never merged (see
# hierarchy/models.py::TaxVersionAudit docstring).

def _json_safe(value):
    """Every upsert function here passes its raw `fields` dict straight
    into old_value/new_value for audit purposes — those dicts routinely
    contain date/Decimal values (effective_from, rate_pct, ...), neither
    of which Python's json module (used by the JSON column type) can
    serialize on its own. Recursively coerces both to JSON-safe forms
    (isoformat / str) instead of crashing the write."""
    import datetime as _dt
    from decimal import Decimal as _Decimal

    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, _Decimal):
        return str(value)
    return value


def record_hierarchy_audit(
    db: Session, actor_id: Optional[int], action: str, entity_type: str, entity_id: int,
    tax_version_id: Optional[int] = None, organization_id: Optional[int] = None,
    old_value: Optional[dict] = None, new_value: Optional[dict] = None, reason: Optional[str] = None,
) -> None:
    db.add(TaxVersionAudit(
        actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
        tax_version_id=tax_version_id, organization_id=organization_id,
        old_value=_json_safe(old_value), new_value=_json_safe(new_value), reason=reason,
    ))
    db.commit()


def list_tax_version_audit(db: Session, tax_version_id: int) -> List[TaxVersionAudit]:
    return (
        db.query(TaxVersionAudit)
        .filter(TaxVersionAudit.tax_version_id == tax_version_id)
        .order_by(TaxVersionAudit.created_at.desc())
        .all()
    )


# ── Countries / Levels (static reference metadata) ──────────────────────

def list_countries(db: Session) -> List[Country]:
    return db.query(Country).order_by(Country.name).all()


def list_jurisdiction_levels(db: Session, country_id: int) -> List[JurisdictionLevel]:
    return (
        db.query(JurisdictionLevel)
        .filter(JurisdictionLevel.country_id == country_id)
        .order_by(JurisdictionLevel.rank)
        .all()
    )


# ── Jurisdiction tree ────────────────────────────────────────────────────

def list_jurisdiction_children(db: Session, parent_id: Optional[int] = None, country_id: Optional[int] = None) -> List[dict]:
    """Direct children only (never a full-tree fetch) — root level (no
    parent_id) requires country_id. has_children/active_tax_version_count
    are pre-aggregated server-side so the tree UI never fetches a node's
    children just to render its expand-arrow or a badge."""
    query = db.query(Jurisdiction).filter(Jurisdiction.is_active == True)  # noqa: E712
    if parent_id is not None:
        query = query.filter(Jurisdiction.parent_jurisdiction_id == parent_id)
    else:
        query = query.filter(Jurisdiction.parent_jurisdiction_id.is_(None))
        if country_id:
            query = query.filter(Jurisdiction.country_id == country_id)
    nodes = query.order_by(Jurisdiction.name).all()

    levels_by_id = {lvl.id: lvl for lvl in db.query(JurisdictionLevel).all()}
    result = []
    for node in nodes:
        has_children = (
            db.query(Jurisdiction.id).filter(Jurisdiction.parent_jurisdiction_id == node.id).first() is not None
        )
        active_count = (
            db.query(sa_func.count(TaxVersion.id))
            .filter(TaxVersion.jurisdiction_id == node.id, TaxVersion.status == "Active")
            .scalar()
        ) or 0
        level = levels_by_id.get(node.level_id)
        result.append({
            "id": node.id, "name": node.name, "code": node.code,
            "level_code": level.level_code if level else "",
            "has_children": has_children, "active_tax_version_count": active_count,
        })
    return result


def get_jurisdiction_detail(db: Session, jurisdiction_id: int) -> dict:
    node = db.query(Jurisdiction).filter(Jurisdiction.id == jurisdiction_id).first()
    if not node:
        raise NotFoundException("Jurisdiction", jurisdiction_id)

    levels_by_id = {lvl.id: lvl for lvl in db.query(JurisdictionLevel).all()}
    chain = []
    current: Optional[Jurisdiction] = node
    while current is not None:
        level = levels_by_id.get(current.level_id)
        chain.append({"id": current.id, "name": current.name, "level_code": level.level_code if level else ""})
        current = (
            db.query(Jurisdiction).filter(Jurisdiction.id == current.parent_jurisdiction_id).first()
            if current.parent_jurisdiction_id else None
        )
    chain.reverse()  # root -> self, for breadcrumb display

    level = levels_by_id.get(node.level_id)
    return {
        "id": node.id, "country_id": node.country_id, "level_id": node.level_id,
        "level_code": level.level_code if level else "",
        "parent_jurisdiction_id": node.parent_jurisdiction_id,
        "name": node.name, "code": node.code, "is_active": node.is_active,
        "breadcrumb": chain,
    }


def upsert_jurisdiction(db: Session, data, actor_id: Optional[int] = None) -> Jurisdiction:
    existing = db.query(Jurisdiction).filter(Jurisdiction.id == data.id).first() if data.id else None
    fields = dict(
        country_id=data.country_id, level_id=data.level_id, parent_jurisdiction_id=data.parent_jurisdiction_id,
        name=data.name, code=data.code, external_ref=data.external_ref, is_active=data.is_active,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = Jurisdiction(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_hierarchy_audit(db, actor_id, "update" if existing else "create", "jurisdiction", row.id, new_value=fields)
    return row


# ── Tax ──────────────────────────────────────────────────────────────────

def list_taxes_for_jurisdiction(db: Session, jurisdiction_id: int) -> List[Tax]:
    """Taxes with at least one TaxVersion at this EXACT jurisdiction node
    (not its ancestors) — the "which taxes are configured here" list for
    the Rates tab's Tax selector. Use engine.tax_resolver_v2.
    list_applicable_tax_codes for the layered "what applies to an
    employee here" question instead; this is narrower, by design, since
    Compliance editing happens at the node that actually owns the data."""
    return (
        db.query(Tax)
        .join(TaxVersion, TaxVersion.tax_id == Tax.id)
        .filter(TaxVersion.jurisdiction_id == jurisdiction_id)
        .distinct()
        .order_by(Tax.name)
        .all()
    )


def upsert_tax(db: Session, data, actor_id: Optional[int] = None) -> Tax:
    existing = db.query(Tax).filter(Tax.id == data.id).first() if data.id else None
    fields = dict(
        country_id=data.country_id, tax_code=data.tax_code, name=data.name,
        category=data.category, description=data.description,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = Tax(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_hierarchy_audit(db, actor_id, "update" if existing else "create", "tax", row.id, new_value=fields)
    return row


# ── TaxVersion ───────────────────────────────────────────────────────────

def list_tax_versions(db: Session, tax_id: int, jurisdiction_id: int) -> List[TaxVersion]:
    return (
        db.query(TaxVersion)
        .filter(TaxVersion.tax_id == tax_id, TaxVersion.jurisdiction_id == jurisdiction_id)
        .order_by(TaxVersion.effective_from.desc())
        .all()
    )


def get_tax_version_detail(db: Session, tax_version_id: int) -> TaxVersion:
    version = db.query(TaxVersion).filter(TaxVersion.id == tax_version_id).first()
    if not version:
        raise NotFoundException("TaxVersion", tax_version_id)
    return version


def upsert_tax_version(db: Session, data, actor_id: Optional[int] = None) -> TaxVersion:
    """Routes ANY attempt to set status="Active" — whether on create or
    on update — through activate_tax_version's overlap guard, never just
    a plain field assignment. This is the direct fix for the confirmed
    bug where creating a pack with status="Active" bypassed every
    duplicate-Active check (how the live two-simultaneously-Active-
    Canada-packs conflict happened)."""
    existing = db.query(TaxVersion).filter(TaxVersion.id == data.id).first() if data.id else None
    target_status = data.status
    fields = dict(
        tax_id=data.tax_id, jurisdiction_id=data.jurisdiction_id, version_label=data.version_label,
        tax_year=data.tax_year, tax_regime=data.tax_regime,
        status="Draft" if target_status == "Active" else target_status,
        effective_from=data.effective_from, effective_to=data.effective_to, currency=data.currency,
        previous_version_id=data.previous_version_id,
        compliance_owner=data.compliance_owner, engineering_owner=data.engineering_owner,
        regulatory_authority=data.regulatory_authority, compliance_category=data.compliance_category,
        source_references=data.source_references, change_summary=data.change_summary,
        next_review_date=data.next_review_date,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = TaxVersion(**fields, created_by_id=actor_id)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_hierarchy_audit(db, actor_id, "update" if existing else "create", "tax_version", row.id, tax_version_id=row.id, new_value=fields)

    if target_status == "Active":
        row = activate_tax_version(db, row.id, actor_id=actor_id)
    return row


def transition_tax_version_status(db: Session, tax_version_id: int, status: str, actor_id: Optional[int] = None) -> TaxVersion:
    if status == "Active":
        return activate_tax_version(db, tax_version_id, actor_id=actor_id)
    version = get_tax_version_detail(db, tax_version_id)
    old_status = version.status
    version.status = status
    db.commit()
    db.refresh(version)
    record_hierarchy_audit(
        db, actor_id, "status_change", "tax_version", version.id, tax_version_id=version.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return version


# ── TaxRule / TaxRuleSlab / TaxRuleRate ─────────────────────────────────

def list_tax_rules_with_children(db: Session, tax_version_id: int) -> List[dict]:
    rules = db.query(TaxRule).filter(TaxRule.tax_version_id == tax_version_id).order_by(TaxRule.sort_order).all()
    result = []
    for rule in rules:
        slabs = db.query(TaxRuleSlab).filter(TaxRuleSlab.tax_rule_id == rule.id).order_by(TaxRuleSlab.sort_order).all()
        rates = db.query(TaxRuleRate).filter(TaxRuleRate.tax_rule_id == rule.id).all()
        result.append({
            "id": rule.id, "tax_version_id": rule.tax_version_id, "rule_type": rule.rule_type,
            "label": rule.label, "formula_expression": rule.formula_expression, "sort_order": rule.sort_order,
            "slabs": slabs, "rates": rates,
        })
    return result


def upsert_tax_rule(db: Session, data, actor_id: Optional[int] = None) -> TaxRule:
    existing = db.query(TaxRule).filter(TaxRule.id == data.id).first() if data.id else None
    fields = dict(
        tax_version_id=data.tax_version_id, rule_type=data.rule_type,
        label=data.label, formula_expression=data.formula_expression, sort_order=data.sort_order,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = TaxRule(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_hierarchy_audit(
        db, actor_id, "update" if existing else "create", "tax_rule", row.id,
        tax_version_id=row.tax_version_id, new_value=fields,
    )
    return row


def delete_tax_rule(db: Session, tax_rule_id: int, actor_id: Optional[int] = None) -> None:
    rule = db.query(TaxRule).filter(TaxRule.id == tax_rule_id).first()
    if not rule:
        raise NotFoundException("TaxRule", tax_rule_id)
    tax_version_id = rule.tax_version_id
    db.query(TaxRuleSlab).filter(TaxRuleSlab.tax_rule_id == tax_rule_id).delete()
    db.query(TaxRuleRate).filter(TaxRuleRate.tax_rule_id == tax_rule_id).delete()
    db.delete(rule)
    db.commit()
    record_hierarchy_audit(db, actor_id, "delete", "tax_rule", tax_rule_id, tax_version_id=tax_version_id)


def upsert_tax_rule_slab(db: Session, data, actor_id: Optional[int] = None) -> TaxRuleSlab:
    existing = db.query(TaxRuleSlab).filter(TaxRuleSlab.id == data.id).first() if data.id else None
    fields = dict(
        tax_rule_id=data.tax_rule_id, min_amount=data.min_amount, max_amount=data.max_amount,
        rate_pct=data.rate_pct, flat_fee_amount=data.flat_fee_amount,
        rate_label=data.rate_label, sort_order=data.sort_order,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = TaxRuleSlab(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    rule = db.query(TaxRule).filter(TaxRule.id == row.tax_rule_id).first()
    record_hierarchy_audit(
        db, actor_id, "update" if existing else "create", "tax_slab", row.id,
        tax_version_id=rule.tax_version_id if rule else None, new_value=fields,
    )
    return row


def delete_tax_rule_slab(db: Session, slab_id: int, actor_id: Optional[int] = None) -> None:
    slab = db.query(TaxRuleSlab).filter(TaxRuleSlab.id == slab_id).first()
    if not slab:
        raise NotFoundException("TaxRuleSlab", slab_id)
    rule = db.query(TaxRule).filter(TaxRule.id == slab.tax_rule_id).first()
    db.delete(slab)
    db.commit()
    record_hierarchy_audit(db, actor_id, "delete", "tax_slab", slab_id, tax_version_id=rule.tax_version_id if rule else None)


def upsert_tax_rule_rate(db: Session, data, actor_id: Optional[int] = None) -> TaxRuleRate:
    existing = db.query(TaxRuleRate).filter(TaxRuleRate.id == data.id).first() if data.id else None
    fields = dict(
        tax_rule_id=data.tax_rule_id,
        employee_rate_pct=data.employee_rate_pct, employer_rate_pct=data.employer_rate_pct,
        employee_flat_amount=data.employee_flat_amount, employer_flat_amount=data.employer_flat_amount,
        display_employee_share=data.display_employee_share, display_employer_share=data.display_employer_share,
        display_total=data.display_total,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = TaxRuleRate(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    rule = db.query(TaxRule).filter(TaxRule.id == row.tax_rule_id).first()
    record_hierarchy_audit(
        db, actor_id, "update" if existing else "create", "tax_rate", row.id,
        tax_version_id=rule.tax_version_id if rule else None, new_value=fields,
    )
    return row


def delete_tax_rule_rate(db: Session, rate_id: int, actor_id: Optional[int] = None) -> None:
    rate = db.query(TaxRuleRate).filter(TaxRuleRate.id == rate_id).first()
    if not rate:
        raise NotFoundException("TaxRuleRate", rate_id)
    rule = db.query(TaxRule).filter(TaxRule.id == rate.tax_rule_id).first()
    db.delete(rate)
    db.commit()
    record_hierarchy_audit(db, actor_id, "delete", "tax_rate", rate_id, tax_version_id=rule.tax_version_id if rule else None)


# ── TaxParameter ─────────────────────────────────────────────────────────

def list_tax_parameters(db: Session, tax_version_id: int) -> List[TaxParameter]:
    return db.query(TaxParameter).filter(TaxParameter.tax_version_id == tax_version_id).order_by(TaxParameter.label).all()


def upsert_tax_parameter(db: Session, data, actor_id: Optional[int] = None) -> TaxParameter:
    existing = db.query(TaxParameter).filter(TaxParameter.id == data.id).first() if data.id else None
    fields = dict(
        tax_version_id=data.tax_version_id, parameter_key=data.parameter_key, label=data.label,
        value_numeric=data.value_numeric, value_text=data.value_text, unit=data.unit,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = TaxParameter(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_hierarchy_audit(
        db, actor_id, "update" if existing else "create", "tax_parameter", row.id,
        tax_version_id=row.tax_version_id, new_value=fields,
    )
    return row


def delete_tax_parameter(db: Session, parameter_id: int, actor_id: Optional[int] = None) -> None:
    param = db.query(TaxParameter).filter(TaxParameter.id == parameter_id).first()
    if not param:
        raise NotFoundException("TaxParameter", parameter_id)
    tax_version_id = param.tax_version_id
    db.delete(param)
    db.commit()
    record_hierarchy_audit(db, actor_id, "delete", "tax_parameter", parameter_id, tax_version_id=tax_version_id)


# ── Applicability ────────────────────────────────────────────────────────

def list_jurisdiction_applicability(db: Session, jurisdiction_id: int) -> List[dict]:
    from app.modules.organizations.models import Organization

    rows = (
        db.query(OrganizationJurisdictionAssignment, Organization.organization_name, Organization.organization_code)
        .join(Organization, Organization.id == OrganizationJurisdictionAssignment.organization_id)
        .filter(OrganizationJurisdictionAssignment.jurisdiction_id == jurisdiction_id)
        .all()
    )
    return [
        {
            "organization_id": a.organization_id, "organization_name": name, "organization_code": code,
            "assignment_type": a.assignment_type, "status": a.status,
        }
        for a, name, code in rows
    ]


# ── Organization jurisdiction assignments ───────────────────────────────

def list_org_jurisdiction_assignments(db: Session, organization_id: int) -> List[OrganizationJurisdictionAssignment]:
    return (
        db.query(OrganizationJurisdictionAssignment)
        .filter(OrganizationJurisdictionAssignment.organization_id == organization_id)
        .order_by(OrganizationJurisdictionAssignment.assignment_type)
        .all()
    )


def upsert_org_jurisdiction_assignment(db: Session, organization_id: int, data, actor_id: Optional[int] = None) -> OrganizationJurisdictionAssignment:
    existing = (
        db.query(OrganizationJurisdictionAssignment).filter(OrganizationJurisdictionAssignment.id == data.id).first()
        if data.id else None
    )
    fields = dict(
        organization_id=organization_id, jurisdiction_id=data.jurisdiction_id,
        assignment_type=data.assignment_type, status=data.status,
        effective_from=data.effective_from or date_cls.today(), effective_to=data.effective_to,
        tax_regime=data.tax_regime,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        row = existing
    else:
        row = OrganizationJurisdictionAssignment(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_hierarchy_audit(
        db, actor_id, "update" if existing else "create", "jurisdiction_assignment", row.id,
        organization_id=organization_id, new_value=fields,
    )
    return row
