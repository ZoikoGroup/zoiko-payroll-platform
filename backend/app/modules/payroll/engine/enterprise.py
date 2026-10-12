"""
modules/payroll/engine/enterprise
---------------------------------
Enterprise Payroll strategy — multi-country dispatch.

Each employee's payroll jurisdiction is determined from the org's
CompanyComplianceDetails (or their work_state override). The engine
dispatches to the appropriate country calculator via the same
``_COUNTRY_CALC`` table StandardStrategy uses (IN, US, UK, AU, DE, CA;
falls back to a generic progressive-tax calculator otherwise).

Phase 2 architecture consolidation: this class's own ``calculate()`` was
a near-verbatim, independently-maintained copy of StandardStrategy's
(same attendance-deduction math, same country dispatch, same Germany
-partial/India-wage-cap handling) that had drifted to silently omit
``employee_pension`` (UK workplace pension) from both the deduction sum
and the returned result — a real bug for any org on Enterprise mode with
UK employees. EnterpriseStrategy is kept only because
``engine/resolver.py``'s strategy registry and ``engine/__init__.py``
import it by name; its calculation behavior is now StandardStrategy's,
inherited rather than duplicated, so the two can never again silently
diverge.
"""

from app.modules.payroll.engine.standard import StandardStrategy


class EnterpriseStrategy(StandardStrategy):
    """Multi-country payroll for global organizations.

    Identical calculation behavior to StandardStrategy today — kept as
    its own class solely for backward-compatible import paths
    (``engine/resolver.py``'s mode registry, ``engine/__init__.py``).
    """
