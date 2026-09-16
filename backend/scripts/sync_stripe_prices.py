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
from app.modules.billing.models import BillingPlanVersion, BillingPlan, PlanVersionStatus
from app.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

# Just dummy amounts for the test
PLAN_PRICES = {
    "CORE": 0,
    "PROFESSIONAL": 5000,
    "BUSINESS": 15000,
    "ENTERPRISE": 50000,
}

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
            amount = PLAN_PRICES.get(plan.code, 5000)

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
