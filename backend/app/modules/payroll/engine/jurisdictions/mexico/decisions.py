"""
engine/jurisdictions/mexico/decisions.py
----------------------------------------
Decisions as configuration (Mexico engineering sweep S1). A switch the sources
leave open (DECISIONS_PENDING D-xx) is read through `switch(code, fallback)`:
the APPROVED answer in the decision register when one is in force for this
calculation, otherwise the module constant (None in production = the case that
needs it BLOCKS with its own code — never a guess).

The answers in force are set for one calculation by `applied(answers)` — the
service loads them from the register (mexico_decision_config) and the run
records them in the payslip's input components, so every result says which
decision versions produced it. A context variable keeps concurrent requests
apart; nothing here touches the database.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_ANSWERS: ContextVar = ContextVar("mx_decision_answers", default=None)


def switch(code: str, fallback=None):
    """The approved answer of `code` for this calculation, else `fallback`."""
    answers = _ANSWERS.get()
    if answers and code in answers:
        return answers[code]["value"]
    return fallback


def in_force() -> dict:
    """{code: {"value", "version", "id", "raw"}} applied to this calculation."""
    return dict(_ANSWERS.get() or {})


@contextmanager
def applied(answers: Optional[dict]):
    """Apply `answers` (from mexico_decision_config.answers_in_force) for the
    duration of the block; the previous answers are restored afterwards."""
    token = _ANSWERS.set(dict(answers) if answers else None)
    try:
        yield
    finally:
        _ANSWERS.reset(token)
