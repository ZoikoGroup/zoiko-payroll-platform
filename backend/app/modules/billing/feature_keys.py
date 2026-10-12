"""
modules/billing/feature_keys.py
---------------------------------
Single source of truth for billing_entitlement_flags.feature_key strings.
Every seed/migration script and every require_entitlement()/
require_scope_limit() call site imports these instead of typing the raw
string, so a typo on either side (seeding vs. checking) can't silently
produce a flag that's never read or a check that never matches.
"""

# Numeric scope limits (BillingEntitlementFlag.limit_value is an int cap;
# require_scope_limit compares a computed "current_count + 1" against it).
MAX_ENTITIES = "max_entities"
MAX_JURISDICTIONS = "max_jurisdictions"
MAX_SCHEDULES = "max_schedules"
MAX_BWM = "max_billable_worker_months"

# Boolean capability toggles (limit_value=None means "on"; limit_value=0
# means "explicitly off" — see entitlements.py's _resolve_entitlement).
MULTI_ENTITY = "multi_entity"
MULTI_CURRENCY = "multi_currency"
API_ACCESS = "api_access"
ASSIST = "assist"
PAYROLL_RUNS = "payroll_runs"
