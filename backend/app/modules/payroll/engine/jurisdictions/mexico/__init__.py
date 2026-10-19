"""
engine/jurisdictions/mexico/__init__.py
---------------------------------------
Mexico jurisdiction helpers (ZP-MX-ENG-001) — pure, ORM-free modules the
Mexico engine (engine/countries/mexico.py) will compose. Nothing here imports
the framework, the ORM or another jurisdiction.

Phase 5: content (typed pack-row access), period, rounding, classification,
isr, subsidy, sbc, imss, ceav, infonavit, isn, labor, entitlements,
preflight, trace, errors. Every rate, tariff and rule is a pack row; a
missing one BLOCKS. isr_special_pay (aguinaldo, PTU, separation) is Phase 9.
"""
