"""
scripts/seed_price_catalog.py
------------------------------
Seed the STANDALONE price book (billing_price_catalog_items) — the ONLY table
a monetary unit_amount may live in across the app (see models.py). One
PUBLISHED RECURRING_BASE row per plan, so GET /billing/plans and POST
/billing/checkout both resolve the exact price from the catalog instead of
any hardcoded application-side dict.

Amounts match the amounts the old hardcoded per-plan price mapping used, so
this is purely a relocation, not a pricing change:
    CORE         $0.00     (0 cents)
    PROFESSIONAL $50.00  (5000 cents)
    BUSINESS     $150.00 (15000 cents)
    ENTERPRISE   $500.00 (50000 cents)

Catalog identity convention (see plan_catalog.py's price helpers): an item's
component_type IS the owning plan code for the flat base price. No plan_id
column exists on billing_price_catalog_items — component_type is the only
per-plan discriminator, so the base row's component_type must equal the plan
code exactly. Add-on components (future) use a suffixed value such as
"BUSINESS:BWM" and are picked up by the sum-based price resolution.

Idempotent: plans that already have a PUBLISHED catalog item (by exact
component_type) are left untouched. A plan with only DRAFT/APPROVED rows
gets its row PUBLISHED appended rather than overwritten.

Usage:
    python -m scripts.seed_price_catalog
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.billing import plan_catalog
from app.modules.billing.models import (
    BillingPriceCatalogItem,
    CatalogItemStatus,
    PlanCode,
)

CATALOG_VERSION = "2026-STANDALONE"
CURRENCY = "USD"

# plan_code -> unit_amount in dollars (cents / 100), matching the amounts
# previously hardcoded in billing/router.py and scripts/sync_stripe_prices.py.
PLAN_BASE_PRICES_USD = {
    PlanCode.CORE.value: Decimal("0.00"),
    PlanCode.PROFESSIONAL.value: Decimal("50.00"),
    PlanCode.BUSINESS.value: Decimal("150.00"),
    PlanCode.ENTERPRISE.value: Decimal("500.00"),
}


def main() -> None:
    initialize_database()

    db = SessionLocal()
    try:
        for plan_code, unit_amount in PLAN_BASE_PRICES_USD.items():
            existing = plan_catalog.get_published_base_catalog_item(db, plan_code)
            if existing is not None:
                print(
                    f"{plan_code}: already has a PUBLISHED price "
                    f"(id={existing.id}, unit_amount={existing.unit_amount}) — nothing to do."
                )
                continue

            item = BillingPriceCatalogItem(
                catalog_version=CATALOG_VERSION,
                component_type=plan_code,
                currency=CURRENCY,
                unit_amount=unit_amount,
                status=CatalogItemStatus.PUBLISHED.value,
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            print(
                f"Published {plan_code}: id={item.id} "
                f"catalog_version={item.catalog_version} "
                f"unit_amount={item.unit_amount} {item.currency}"
            )

        print(
            f"Done. Catalog lookups now cover: "
            f"{', '.join(PLAN_BASE_PRICES_USD)}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()