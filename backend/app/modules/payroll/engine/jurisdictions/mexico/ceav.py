"""
engine/jurisdictions/mexico/ceav.py
-----------------------------------
Employer Cesantía en Edad Avanzada y Vejez (spec §9, MX-029): the band of the
year in force is chosen by the SBC expressed in the band's own units — "UMA"
= the daily UMA, "SM" = the minimum wage named by
`mx_ceav_lowest_band_min_wage_ref` — and its employer % applies to SBC × days.

- An SBC that falls between two bands BLOCKS (no band boundary is guessed).
- The lowest band's minimum-wage reference stays [PENDING G2]: a ZLFN
  employee in the lowest band BLOCKS (Phase 0 decision 4).
The employee CEAV % is an IMSS branch row (imss.py).
"""

from __future__ import annotations

from decimal import Decimal

from .errors import MXBlock

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def _unit_amount(content, unit: str, uma_daily: Decimal) -> Decimal:
    if unit == "UMA":
        return uma_daily
    ref = content.text("mx_ceav_lowest_band_min_wage_ref").upper()
    return content.min_wage(ref)


def band_for(sbc: Decimal, bands: list, content, uma_daily: Decimal) -> tuple:
    """(band, index) whose [lower, upper] — in its units — contains the SBC."""
    for i, b in enumerate(bands):
        lower = b["lower"] * _unit_amount(content, b["lower_unit"], uma_daily)
        if sbc < lower:
            continue
        if b["upper"] is None or sbc <= b["upper"] * _unit_amount(content, b["upper_unit"], uma_daily):
            return b, i
    raise MXBlock("MX_CEAV_BAND_GAP", f"SBC {sbc} falls in no CEAV employer band in force")


def employer(sbc_segments, zone: str) -> dict:
    lines = []
    for seg in sbc_segments:
        c, sbc = seg["content"], seg["sbc"]
        band, index = band_for(sbc, c.ceav_bands(), c, seg["uma_daily"])
        if index == 0 and zone == "ZLFN":
            raise MXBlock("MX_CEAV_LOWEST_BAND_PENDING_G2",
                          "a ZLFN employee in the lowest CEAV band — its minimum-wage reference is [PENDING G2]")
        lines.append({"branch": "CEAV", "side": "employer", "segment": seg["start"].isoformat(),
                      "band": band["label"], "base": sbc, "days": seg["days"], "rate_pct": band["rate_pct"],
                      "amount": sbc * seg["days"] * band["rate"]})
    return {"lines": lines, "employer": sum((l["amount"] for l in lines), _ZERO)}
