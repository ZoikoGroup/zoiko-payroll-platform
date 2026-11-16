"""PCB / MTD (ZP-MY-ENG-001 §5; MY-009) — Phase 3 guard.

The production engine must implement HASiL's 2026 computerised calculation
specification exactly (normal and additional remuneration, TP1 / TP3, EPF in
the formula, zakat, statutory rounding) and reconcile to HASiL's official test
questions. That document (S1) is not archived yet, so this module computes
NOTHING: every payslip on which PCB applies is blocked with
MY_PCB_SPEC_NOT_ARCHIVED. Annual tax brackets are never used as a substitute
(MY-009). Phase 4 replaces `compute` with the specification's formula.
"""
from __future__ import annotations

from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack


def compute(pack: MyPack, **_inputs) -> dict:
    pack.block(E.PCB_SPEC_NOT_ARCHIVED,
               "the HASiL 2026 computerised MTD specification is not archived; PCB is never approximated")
