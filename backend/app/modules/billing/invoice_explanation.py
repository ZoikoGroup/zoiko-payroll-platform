"""
modules/billing/invoice_explanation.py
------------------------------------------
Part 7 — BWM-to-invoice reconciliation + customer-visible explanation.

Joins one invoice's BillingInvoiceLine rows against the
BillingWorkerMonthRecord rows for the same org/billing-period, so a
customer (or Super Admin) can see exactly who was counted on an invoice,
and who was NOT counted and why.

Honest limitation, disclosed rather than hidden: BillingWorkerMonthRecord
is only ever populated by billing/bwm.py's aggregate_billing_month(),
which — as of this change — still has no scheduled/triggered caller
anywhere in the codebase (see billing/bwm.py's own count_billable_workers
docstring). Until that pipeline is wired up, `employees_counted` below will
legitimately be empty for any org whose BWM rows were never aggregated —
this is surfaced as `bwm_data_available: False`, not silently hidden as
"zero employees".
"""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.billing.models import BillingInvoice, BillingInvoiceLine, BillingWorkerMonthRecord


def _billing_month_for_invoice(invoice: BillingInvoice) -> Optional[date]:
    if invoice.issued_at is None:
        return None
    return invoice.issued_at.date().replace(day=1)


def build_invoice_explanation(db: Session, invoice: BillingInvoice) -> dict:
    lines = db.query(BillingInvoiceLine).filter(BillingInvoiceLine.invoice_id == invoice.id).all()
    billing_month = _billing_month_for_invoice(invoice)

    bwm_records = []
    if billing_month is not None:
        bwm_records = (
            db.query(BillingWorkerMonthRecord)
            .filter(
                BillingWorkerMonthRecord.organization_id == invoice.organization_id,
                BillingWorkerMonthRecord.billing_month == billing_month,
            )
            .all()
        )

    counted = [
        {"payroll_employee_id": r.payroll_employee_id, "employer_entity_id": r.employer_entity_id}
        for r in bwm_records if r.counted
    ]
    excluded = [
        {"payroll_employee_id": r.payroll_employee_id, "reason_code": r.reason_code}
        for r in bwm_records if not r.counted
    ]

    return {
        "invoice_id": invoice.id,
        "organization_id": invoice.organization_id,
        "billing_month": billing_month,
        "total": invoice.total,
        # Zoiko subscription tax only — see BillingInvoice.tax_amount's own
        # column comment. Never mixed with payroll-tax figures.
        "tax_amount": invoice.tax_amount,
        "currency": invoice.currency,
        "lines": [
            {"description": l.description, "component_type": l.component_type, "quantity": l.quantity, "line_total": l.line_total}
            for l in lines
        ],
        "bwm_data_available": billing_month is not None and len(bwm_records) > 0,
        "employees_counted": counted,
        "employees_excluded": excluded,
    }


def find_bwm_invoice_discrepancies(db: Session, organization_id: Optional[int] = None) -> list:
    """Finance-facing discrepancy report: any (org, billing_month) where a
    BWM-priced invoice line's quantity doesn't match the actual
    count(BillingWorkerMonthRecord WHERE counted=true) for that org/month.
    A real billing bug, surfaced not silently accepted — same principle as
    the Super Admin Command Center's Exceptions & Reconciliation page.
    """
    query = db.query(BillingInvoice)
    if organization_id is not None:
        query = query.filter(BillingInvoice.organization_id == organization_id)

    discrepancies = []
    for invoice in query.all():
        billing_month = _billing_month_for_invoice(invoice)
        if billing_month is None:
            continue

        bwm_line = (
            db.query(BillingInvoiceLine)
            .filter(BillingInvoiceLine.invoice_id == invoice.id, BillingInvoiceLine.component_type == "BWM")
            .first()
        )
        if bwm_line is None:
            continue

        actual_count = (
            db.query(BillingWorkerMonthRecord)
            .filter(
                BillingWorkerMonthRecord.organization_id == invoice.organization_id,
                BillingWorkerMonthRecord.billing_month == billing_month,
                BillingWorkerMonthRecord.counted.is_(True),
            )
            .count()
        )
        if actual_count != bwm_line.quantity:
            from app.modules.organizations.models import Organization

            org = db.query(Organization).filter(Organization.id == invoice.organization_id).first()
            discrepancies.append({
                "invoice_id": invoice.id,
                "organization_id": invoice.organization_id,
                "organization_name": org.organization_name if org else None,
                "billing_month": billing_month,
                "invoiced_quantity": bwm_line.quantity,
                "actual_bwm_count": actual_count,
                "difference": actual_count - bwm_line.quantity,
            })
    return discrepancies
