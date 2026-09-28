"""
engine/jurisdictions/singapore
------------------------------
Singapore statutory support that is not payroll calculation — the same
subsystem-package boundary Germany uses (engine/jurisdictions/germany/:
statutory/deuv.py, statutory/elster.py, pap/production_gate.py). Every
module here is PURE (no database, no session): service.py gathers the
facts and persists results; these modules only evaluate/format.

- `readiness.py`         - Employer Registration readiness (ZP-SG-ENG-001 SG-027).
- `statutory/ezpay.py`   - CPF EZPay (FTP) contribution file — CPF Board
                           "CPF EZPay (FTP) File Specifications" (effective 16 Jan 2025).
- `labour.py`            - Employment Act / Progressive Wage Model / LQS checks.
- `compliance.py`        - Singapore Compliance Centre items.

`engine/countries/singapore.py` remains the country calculator (CPF, SDL,
SHG, levy, per-earning CPF/IRAS classification).
"""
