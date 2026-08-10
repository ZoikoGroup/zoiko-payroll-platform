"""
modules/payroll/engine
----------------------
Strategy-based payroll calculation engine.

Architecture:
    PayrollEngine resolves the org's active policy → instantiates the
    correct strategy → calls calculate() → returns a PayrollResult.

Each strategy handles its own compliance logic while sharing the same
Fixed 30-Day attendance model.
"""

from app.modules.payroll.engine.base import (
    PAYROLL_DAYS,
    PayrollContext,
    PayrollResult,
    PayrollStrategy,
)
from app.modules.payroll.engine.simple import SimpleStrategy
from app.modules.payroll.engine.standard import StandardStrategy
from app.modules.payroll.engine.enterprise import EnterpriseStrategy
from app.modules.payroll.engine.resolver import calculate_payroll, resolve_strategy
