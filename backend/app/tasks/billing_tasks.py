"""
app/tasks/billing_tasks.py
---------------------------
Celery tasks for billing and subscription management.

Handles trial expiry, subscription renewals, payment processing, and dunning.
"""
from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    queue="billing",
)
def trial_expiry_sweep_task(self) -> Dict[str, Any]:
    raise NotImplementedError(
        "trial_expiry_sweep_task is not implemented: this task has no trial lifecycle sweep; payroll_service.run_trial_expiry_sweep does not exist. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="billing",
)
def process_subscription_renewals_task(self) -> Dict[str, Any]:
    raise NotImplementedError(
        "process_subscription_renewals_task is not implemented: this task has no renewal processor; no payment provider is wired up. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="billing",
)
def process_payment_task(self, invoice_id: int, payment_method_id: int = None) -> Dict:
    raise NotImplementedError(
        "process_payment_task is not implemented: this task has no payment processor; returning 'succeeded' without charging would corrupt the ledger. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
    queue="billing",
)
def handle_failed_payment_task(self, invoice_id: int, attempt: int = 1) -> Dict:
    raise NotImplementedError(
        "handle_failed_payment_task is not implemented: this task has no dunning engine; no retry schedule or notification path exists. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="billing",
)
def send_invoice_email_task(self, invoice_id: int, email: str, pdf_attachment: bool = True) -> Dict:
    raise NotImplementedError(
        "send_invoice_email_task is not implemented: this task has no invoice mailer; no mail transport is configured. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="billing",
)
def generate_invoice_pdf_task(self, invoice_id: int) -> Dict:
    raise NotImplementedError(
        "generate_invoice_pdf_task is not implemented: this task has no invoice PDF renderer; the returned URL would 404. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="billing",
)
def sync_stripe_customer_task(self, organization_id: int) -> Dict:
    raise NotImplementedError(
        "sync_stripe_customer_task is not implemented: this task has no Stripe client; no Stripe dependency or key is configured. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(
    bind=True,
    queue="billing",
)
def cancel_subscription_task(self, subscription_id: int, at_period_end: bool = True) -> Dict:
    raise NotImplementedError(
        "cancel_subscription_task is not implemented: this task has no subscription canceller; nothing here reaches a provider. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(bind=True, queue="billing")
def daily_billing_sweep_task(self) -> Dict:
    raise NotImplementedError(
        "daily_billing_sweep_task is not implemented: this task has no billing maintenance sweep. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
@shared_task(bind=True, queue="billing")
def monthly_billing_reconciliation_task(self) -> Dict:
    raise NotImplementedError(
        "monthly_billing_reconciliation_task is not implemented: this task has no provider reconciliation; there is no provider-side data to reconcile against. It is kept in the "
        "registry so the intended surface stays visible, but it fails loudly "
        "rather than returning a fabricated result. Implement it before enqueueing it anywhere."
    )
