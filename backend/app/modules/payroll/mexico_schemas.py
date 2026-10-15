"""
payroll/mexico_schemas.py
-------------------------
Pydantic schemas for the Mexico payroll API (ZP-MX-ENG-001) — camelCase
responses, like netherlands_schemas.py.

Phase 0: the readiness document only.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel


class MXGateState(BaseModel):
    gate: str
    label: str
    state: str  # OPEN / SUBMITTED / SIGNED


class MXReadinessResponse(BaseModel):
    jurisdiction: str
    spec: str
    available: bool
    engineVersion: str
    phase: int
    gates: List[MXGateState]
    note: str
