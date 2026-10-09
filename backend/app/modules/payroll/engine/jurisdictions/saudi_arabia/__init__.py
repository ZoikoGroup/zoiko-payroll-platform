"""
engine/jurisdictions/saudi_arabia/__init__.py
---------------------------------------------
Saudi Arabia jurisdiction helpers (ZP-SA-ENG-001) — pure, ORM-free modules
that hold the Labour-Law shapes the monthly GOSI engine
(engine/countries/saudi_arabia.py) and the settlement workflows share:

* labour.py — working-hours limits, overtime premium and the Art. 91/92
  deduction caps (per-type loan cap + the 50% aggregate cap);
* eos.py — the end-of-service award accrual and the resignation fraction.

Nothing here imports the framework, the ORM or another jurisdiction.
"""
