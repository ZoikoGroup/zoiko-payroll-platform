"""
engine/jurisdictions/germany/overtime
-------------------------------------
Germany overtime / shift-premium subsystem (§3b EStG premium categories,
§1 SvEV social-insurance exemption) — Phase 5 normalization.

Four independent calculators are grouped here (NOT merged — each owns a
discrete statutory responsibility and a separate exception hierarchy,
independent caps/formulas/models):

- `classifier.py`               - Phase 8AE: classifies worked time into
                                  §3b EStG premium categories. Never returns
                                  a euro amount.
- `wage_tax.py`                 - Phase 8AF: §3b EStG wage-tax deltas.
- `social_insurance.py`         - Phase 8AG: §1 SvEV social-insurance deltas.
- `premium_component.py`        - Phase 8AH: combines one wage-tax result and
                                  one social-insurance result for the same
                                  time range into a presentable unit.
"""