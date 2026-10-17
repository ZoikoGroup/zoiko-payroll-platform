"""
engine/jurisdictions/mexico/trace.py
------------------------------------
The MX-007 / MX-063 trace: per concept gross / exempt / taxable and its other
bases, the SBC components, each IMSS branch's base × rate, the CEAV band,
INFONAVIT, ISN, subsidy, and every content row read, with the pack id /
version and source codes — so a result is reproducible from its inputs.
Values are strings (JSON-safe, exact).
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal


def plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items() if k != "content"}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def concepts(lines) -> list:
    return [{"code": l["code"], "kind": l["kind"], "gross": l["amount"], "isr_exempt": l["isr_exempt"],
             "isr_taxable": l["isr_taxable"], "sbc": l["sbc"], "infonavit": l["infonavit"], "isn": l["isn"],
             "ptu": l["ptu"], "cfdi_node": l["cfdi_node"], "cfdi_concept_code": l["cfdi_concept_code"],
             "classification_id": l["classification_id"], "classification_version": l["version"]}
            for l in lines]


def content_rows(*contents) -> list:
    seen, out = set(), []
    for c in contents:
        for key, value in c.used:
            item = (c.label, key, value)
            if item not in seen:
                seen.add(item)
                out.append({"content": c.label, "key": key, "value": value})
    return out


def build(**parts) -> dict:
    return plain(parts)
