"""
engine/jurisdictions/germany/statutory
--------------------------------------
Germany statutory electronic-reporting boundaries (Phase 5 normalization).

Both modules are fail-closed design boundaries (no live connector exists or
is authorized in this codebase):

- `deuv.py`    - DEÜV (Datenübermittlungs-Verordnung) social-insurance
                 notification boundary. Abstract `DeuvTransmitter`,
                 `UnavailableDeuvTransmitter`, `resolve_deuv_transmitter()`.
- `elster.py`  - ELSTER (ELektronische STeuerERklärung) transmission boundary.
                 Abstract `ElsterTransmitter`, `UnavailableElsterTransmitter`,
                 `resolve_elster_transmitter()`.
"""