"""Canonical JSON + SHA-256 for New Zealand calculations (NZ-005, NZ-022).

The same inputs, the same pack rows and the same engine build always produce
the same hashes. Only whitelisted, non-identifying fields are hashed: no IRD
vault id, declaration or evidence reference, fund reference or date of birth
(the age at the payday is hashed instead).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from .pack import field, normalise_frequency


def _default(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default)


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


PROFILE_FIELDS = ("id", "tax_code", "tax_code_source", "ird_number_state", "residency_status",
                  "tailored_rate_pct", "tailored_valid_from", "tailored_valid_to", "sl_certificate_type",
                  "sl_certificate_rate_pct", "sl_certificate_valid_from", "sl_certificate_valid_to",
                  "min_wage_category", "effective_from", "effective_to", "status")
KIWISAVER_FIELDS = ("id", "membership_state", "employee_rate_pct", "employer_rate_pct", "reduction_from",
                    "reduction_to", "employer_matches_reduction", "suspension_from", "suspension_to",
                    "esct_rate_pct", "esct_basis", "esct_basis_amount", "employer_contribution_treatment",
                    "settlement_destination", "effective_from", "effective_to", "status")
NOTICE_FIELDS = ("id", "deduction_type", "notice_id", "version", "amount_per_payday", "rate_pct",
                 "effective_from", "effective_to", "status")
EMPLOYER_FIELDS = ("id", "legal_entity_id", "effective_from", "effective_to", "status")


def pick(row, fields):
    if row is None:
        return None
    return {name: field(row, name) for name in fields}


def input_document(ctx, components, age=None) -> dict:
    notices = sorted(ctx.nz_authority_deductions or [], key=lambda n: str(field(n, "id")))
    return {
        "gross": ctx.gross, "basic": ctx.basic, "overtime": ctx.overtime,
        "components": [[name, amount] for name, amount in components],
        "frequency": normalise_frequency(ctx.pay_frequency),
        "payDate": getattr(ctx, "nz_pay_date", None) or ctx.pay_date,
        "paymentKind": ctx.nz_payment_kind or "REGULAR",
        "employer": pick(ctx.nz_employer_profile, EMPLOYER_FIELDS),
        "taxProfile": pick(ctx.nz_tax_profile, PROFILE_FIELDS),
        "kiwisaver": pick(ctx.nz_kiwisaver, KIWISAVER_FIELDS),
        "notices": [pick(n, NOTICE_FIELDS) for n in notices],
        "workPatternId": field(ctx.nz_work_pattern, "id"),
        "accumulators": ctx.nz_accumulators,
        "hours": ctx.nz_hours,
        "hoursSource": ctx.nz_hours_source,
        "ageAtPayday": age,
    }


def hashes(input_doc: dict, used_rows: list, result_without_hashes: dict) -> dict:
    return {"inputHash": sha256(input_doc), "packHash": sha256(used_rows),
            "resultHash": sha256(result_without_hashes)}
