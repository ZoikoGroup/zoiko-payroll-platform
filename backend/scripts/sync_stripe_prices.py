"""
scripts/sync_stripe_prices.py
-----------------------------
Sync published plan versions to Stripe to get stripe_price_id.
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stripe
from app.database import SessionLocal, initialize_database
from app.modules.billing import plan_catalog
from app.modules.billing.models import BillingPlanVersion, BillingPlan, PlanVersionStatus
from app.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


def main():
    parser = argparse.ArgumentParser(description="Sync Stripe Prices")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created without making API calls")
    args = parser.parse_args()

    initialize_database()
    db = SessionLocal()
    try:
        versions = (
            db.query(BillingPlanVersion)
            .filter(BillingPlanVersion.status == PlanVersionStatus.PUBLISHED.value)
            .filter(BillingPlanVersion.stripe_price_id.is_(None))
            .all()
        )

        for v in versions:
            plan = db.query(BillingPlan).filter(BillingPlan.id == v.plan_id).first()
            
            product_name = f"{plan.name} v{v.version}"

            # Step 7 — the amount comes from the PUBLISHED price catalog
            # (billing_price_catalog_items), never from a hardcoded mapping.
            # A plan with no published catalog price is skipped with a
            # warning: there is no defensible amount to send to Stripe.
            amount = plan_catalog.resolve_plan_monthly_price_cents(db, plan.code)
            if amount is None:
                print(
                    f"SKIP plan_version_id={v.id} ({plan.code}): no PUBLISHED catalog price. "
                    "Run scripts/seed_price_catalog.py first."
                )
                continue

            if args.dry_run:
                print(f"Would create Stripe Product '{product_name}' and Price {amount} for plan_version_id={v.id}")
            else:
                if not stripe.api_key:
                    print("Error: STRIPE_SECRET_KEY is not set.")
                    return

                print(f"Creating Stripe Product '{product_name}'...")
                product = stripe.Product.create(name=product_name)
                
                print(f"Creating Stripe Price for '{product_name}'...")
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=amount,
                    currency="usd",
                    recurring={"interval": "month"},
                )
                
                v.stripe_price_id = price.id
                db.commit()
                print(f"Updated plan_version_id={v.id} with stripe_price_id={price.id}")
                
    finally:
        db.close()

if __name__ == "__main__":
    main()
