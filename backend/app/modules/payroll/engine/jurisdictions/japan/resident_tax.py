"""Japan resident-tax special collection (ZP-JP-ENG-001, JP-007/JP-008)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.jurisdictions.japan.errors import JapanCalculationBlockedError

ZERO = Decimal("0")


class RTResult(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _field(value, name):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _upper(value):
    return "" if value is None else str(value).strip().upper()


def _month(value):
    if isinstance(value, date):
        return value.year, value.month
    if not value:
        return None
    text = str(value)
    try:
        if len(text) >= 7 and text[4] == "-":
            return int(text[:4]), int(text[5:7])
        parsed = date.fromisoformat(text[:10])
        return parsed.year, parsed.month
    except (ValueError, TypeError):
        return None


def _month_key(year, month):
    return f"{year:04d}-{month:02d}"


def _block(key: str, reason: str, organization_id=None):
    raise JapanCalculationBlockedError(key, reason, organization_id)


# Statuses that may still govern a month: a SUPERSEDED version keeps
# governing the months before its replacement starts (spec section 4: prior
# deductions remain immutable, so replaying an earlier month must find it).
_GOVERNING = ("APPROVED", "SUPERSEDED")


def _start(assessment):
    pair = _month(_field(assessment, "first_deduction_month"))
    return None if pair is None else pair[0] * 12 + pair[1] - 1


def resident_tax_for_month(assessments, pay_month=None, pay_date=None, collection="SPECIAL"):
    """Return the exact notified amount for the single approved assessment."""
    target = _month(pay_date if pay_date is not None else pay_month)
    if target is None:
        _block("jp_resident_tax_pay_month", "a valid pay month is required")
    year, month = target
    key = _month_key(year, month)

    if str(collection or "SPECIAL").strip().upper() == "NOT_APPLICABLE":
        # The worker tax profile records (with evidence) that no special-
        # collection notice applies, e.g. a first year in Japan. Nothing is
        # estimated; nothing is withheld.
        return RTResult(amount=ZERO, municipality=None, notice_year=None, version=None, notice_id=None,
                        trace={"month": key, "status": "NOT_APPLICABLE"})

    target = year * 12 + month - 1
    chains = {}
    for assessment in assessments or []:
        if _upper(_field(assessment, "status")) not in _GOVERNING:
            continue
        start = _start(assessment)
        amounts = _field(assessment, "monthly_amounts") or {}
        in_window = start is not None and 0 <= target - start < 12
        if not (in_window or (start is not None and start <= target and key in amounts)):
            continue
        chain = (_field(assessment, "municipality_code"), _field(assessment, "fiscal_notice_year"))
        chains.setdefault(chain, []).append(assessment)

    if not chains:
        _block("JP_RESIDENT_TAX_NOTICE_MISSING",
               f"no approved resident-tax notice covers {key}; resident tax is never estimated")
    if len(chains) > 1:
        _block("JP_RESIDENT_TAX_NOTICE_AMBIGUOUS",
               f"{len(chains)} resident-tax notices cover {key}; exactly one is required")

    # Within one notice chain the governing version is the latest one that has
    # started by this month; a later change notice never rewrites earlier months.
    versions = sorted(next(iter(chains.values())),
                      key=lambda a: (_start(a), int(_field(a, "version") or 1)))
    if sum(1 for a in versions if _upper(_field(a, "status")) == "APPROVED") > 1:
        # Approving a change notice supersedes the version it replaces; two
        # APPROVED versions in one chain is an inconsistency, never a choice.
        _block("JP_RESIDENT_TAX_NOTICE_AMBIGUOUS",
               f"more than one APPROVED version of the notice covers {key}")
    assessment = versions[-1]
    if sum(1 for a in versions if (_start(a), int(_field(a, "version") or 1))
           == (_start(assessment), int(_field(assessment, "version") or 1))) > 1:
        _block("JP_RESIDENT_TAX_NOTICE_AMBIGUOUS",
               f"two notice versions start in the same month for {key}")
    amounts = _field(assessment, "monthly_amounts") or {}
    if key not in amounts:
        _block("JP_RESIDENT_TAX_NOTICE_MISSING",
               f"the approved notice has no monthly amount for {key}")
    value = amounts[key]
    if value is None or value == "":
        _block("JP_RESIDENT_TAX_NOTICE_MISSING",
               f"the approved notice has no amount for {key}")
    amount = Decimal(str(value))
    if amount < ZERO:
        _block("JP_RESIDENT_TAX_NOTICE_INVALID", "the notified resident-tax amount is negative")

    return RTResult(
        amount=amount,
        municipality=_field(assessment, "municipality_code"),
        notice_year=_field(assessment, "fiscal_notice_year"),
        version=_field(assessment, "version"),
        notice_id=_field(assessment, "notice_id"),
        trace={"month": key, "status": _upper(_field(assessment, "status")),
               "noticeId": _field(assessment, "notice_id"),
               "municipality": _field(assessment, "municipality_code"),
               "noticeYear": _field(assessment, "fiscal_notice_year"),
               "version": _field(assessment, "version")},
    )
