"""
engine/jurisdictions/brazil/bases.py
------------------------------------
Rubric-incidence bases for Brazil (ZP-BR-ENG-001) — pure, ORM-free.

Phase 5 replaces the draft engine's "gross is every base" shortcut (BR-002) with
bases derived from each earning's eSocial Table 03 incidence codes (BR-005):
the same rubric catalogue that is seeded as the mandatory system rubric matrix.
An earning contributes to a base only when its incidence code marks it as part
of that base, so an exempt earning never inflates INSS, IRRF or FGTS.

The catalogue is passed IN as plain data (the engine hands over
`brazil_content.STANDARD_SYSTEM_RUBRICS`); this module imports nothing from the
framework, the ORM or another jurisdiction, so it can be unit-tested alone.

Incidence codes (eSocial Tabela 03):
    11 — base de cálculo mensal (CP / IRRF remuneração mensal / FGTS)
    00 — não é base de cálculo / isento

An earning whose rubric code is absent from the catalogue is reported back in
`unmapped`; the engine BLOCKS on it (BR_ENGINE_RUBRIC_UNKNOWN) rather than
guessing an incidence, because an unknown incidence would silently mis-state
every base.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Mapping, Tuple

ZERO = Decimal("0.00")

# eSocial Tabela 03 incidence code that marks an earning as part of a base.
INCIDENCE_BASE = "11"
# Codes that explicitly keep an earning OUT of a base (00 not a base, 01 not a
# base / non-taxable). Every other code (12 13th salary, 13 vacation, ...) needs
# its own calculation the monthly engine does not have — it is reported in
# `unsupported` and the engine BLOCKS (BR-E4: it used to be silently dropped
# from every base, so 13th / vacation pay escaped INSS, IRRF and FGTS).
INCIDENCE_EXCLUDED = ("00", "01")


def _r2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def catalogue_by_code(catalogue: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    """{rubric_code: rubric} for a rubric catalogue (last row wins on a dup)."""
    return {row["rubric_code"]: row for row in catalogue}


def resolve_bases(
    earnings: Iterable[Mapping[str, Any]],
    catalogue: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Classify `earnings` into the CP, IRRF and FGTS bases by incidence code.

    Each earning is `{"rubricCode": str, "amount": Decimal-ish}`. Returns:
        base_cp    — CP/INSS-includable total (also the employer CPP/RAT/FPAS
                     and Salário-Família remuneration)
        base_irrf  — IRRF monthly-remuneration total (before deductions)
        base_fgts  — FGTS-deposit-includable total
        lines      — per-earning incidence trace
        unmapped   — rubric codes with no catalogue row (the engine BLOCKS on a
                     non-empty list)
        unsupported — "<rubric>:<cp|irrf|fgts>=<code>" for incidence codes the
                     monthly engine does not calculate (the engine BLOCKS)
    """
    by_code = catalogue_by_code(catalogue)
    base_cp = base_irrf = base_fgts = ZERO
    lines: List[Dict[str, Any]] = []
    unmapped: List[str] = []
    unsupported: List[str] = []

    for item in earnings:
        code = item.get("rubricCode")
        if code is None:
            code = item.get("rubric_code")
        amount = Decimal(str(item.get("amount", "0")))
        row = by_code.get(code)
        if row is None:
            unmapped.append(str(code))
            continue
        for base, key in (("cp", "cod_inc_cp"), ("irrf", "cod_inc_irrf"), ("fgts", "cod_inc_fgts")):
            incidence = row.get(key)
            if incidence != INCIDENCE_BASE and incidence not in INCIDENCE_EXCLUDED:
                unsupported.append(f"{code}:{base}={incidence}")
        in_cp = row.get("cod_inc_cp") == INCIDENCE_BASE
        in_irrf = row.get("cod_inc_irrf") == INCIDENCE_BASE
        in_fgts = row.get("cod_inc_fgts") == INCIDENCE_BASE
        if in_cp:
            base_cp += amount
        if in_irrf:
            base_irrf += amount
        if in_fgts:
            base_fgts += amount
        lines.append({
            "rubric_code": code,
            "amount": str(_r2(amount)),
            "cod_inc_cp": row.get("cod_inc_cp"),
            "cod_inc_irrf": row.get("cod_inc_irrf"),
            "cod_inc_fgts": row.get("cod_inc_fgts"),
            "in_cp": in_cp,
            "in_irrf": in_irrf,
            "in_fgts": in_fgts,
        })

    return {
        "base_cp": _r2(base_cp),
        "base_irrf": _r2(base_irrf),
        "base_fgts": _r2(base_fgts),
        "lines": lines,
        "unmapped": unmapped,
        "unsupported": unsupported,
    }
