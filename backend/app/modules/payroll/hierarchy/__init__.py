# Additive submodule for the generic jurisdiction/tax hierarchy engine.
# No router yet (Phase 4+) — importing this package only registers the
# new tables on Base.metadata so `create_all`/`sync_schema` can build them.
from app.modules.payroll.hierarchy import models  # noqa: F401
