"""modules/payroll/engine/countries/uae_content.py
------------------------------------------------
United Arab Emirates (ZP-AE-ENG-001 v1.0, 22 Sep 2026) — the statutory values
the UAE canonical pack is seeded with. This is SEED DATA, not engine
constants: scripts/seed_uae_canonical_pack.py writes these rows into
payroll_contribution_rates under pack AE-PAYROLL-2026, Super Admin can edit
them (Compliance → United Arab Emirates → Contribution Rates) and the engine
(engine/countries/uae.py) only ever reads the pack. A value missing from the
pack stops the calculation with a named reason; there is no fallback.

Percentages are FRACTIONS (0.11 = 11%), like every ContributionRate row.

Every row names the spec section / fixture and the official source from the
spec's evidence register (§26: S5 Emirati minimum salary, S7 GPSSA, S10/S11
ADPF, S12 end-of-service, S13 savings scheme, S14 overtime, S22 Labour Law).

Deliberately NOT here because the spec gives no value (the engine blocks with
a clear message until a Super Admin adds the rows):
  * GCC home-country contribution rates (spec §8, AE-025) — rows
    ae_gcc_<SA|KW|OM|BH|QA> (employee / employer share) and
    ae_gcc_<cc>_salary_max (optional);
  * the part-time end-of-service formula (AE-030).
"""
from datetime import date

PACK_ID = "AE-PAYROLL-2026"
CURRENCY = "AED"
EFFECTIVE_FROM = date(2026, 1, 1)
REGULATORY_AUTHORITY = "MoHRE / GPSSA / Abu Dhabi Pension Fund"
SOURCE_REFERENCES = "ZP-AE-ENG-001 v1.0 (22 Sep 2026), evidence register S5, S7, S10-S14, S22"

# (component_key, label, employee fraction, employer fraction, flat amount, text value, row effective_from, source)
RATES = (
    # ── GPSSA (spec §6, F4; S7) ─────────────────────────────────────────────
    ("ae_gpssa_law7", "GPSSA pension — Federal Law 7/1999 cohort", "0.05", "0.15", None, None, None, "§6 / S7"),
    ("ae_gpssa_law7_gov_support", "GPSSA Law 7 — government support (part of the 15% employer share)",
     None, "0.025", None, None, None, "§6 / S7"),
    ("ae_gpssa_law7_salary_max", "GPSSA Law 7 — maximum contribution salary (private sector)",
     None, None, "50000", None, None, "§6 / S7"),
    ("ae_gpssa_law57", "GPSSA pension — Federal Law 57/2023 cohort", "0.11", "0.15", None, None, None, "§6, F4 / S7"),
    ("ae_gpssa_law57_gov_support", "GPSSA Law 57 — government support (part of the 15% employer share)",
     None, "0.025", None, None, None, "§6, F4 / S7"),
    ("ae_gpssa_law57_gov_support_limit", "GPSSA Law 57 — government support only below this contribution salary",
     None, None, "20000", None, None, "§6 / S7"),
    ("ae_gpssa_law57_salary_min", "GPSSA Law 57 — minimum contribution salary", None, None, "3000", None, None,
     "§6 / S7"),
    ("ae_gpssa_law57_salary_max", "GPSSA Law 57 — maximum contribution salary", None, None, "70000", None, None,
     "§6 / S7"),
    # ── ADPF (spec §7, F5; S10, S11) ────────────────────────────────────────
    ("ae_adpf_in_service", "ADPF pension — in-service member (registered before 1 Dec 2023)", "0.05", "0.15",
     None, None, None, "§7 / S10"),
    ("ae_adpf_in_service_salary_max", "ADPF in-service — maximum pensionable salary", None, None, "150000",
     None, None, "§7 / S10"),
    ("ae_adpf_new", "ADPF pension — new active member (first registered from 1 Dec 2023)", "0.11", "0.15",
     None, None, None, "§7, F5 / S10"),
    ("ae_adpf_new_salary_max", "ADPF new member — maximum pensionable salary", None, None, "100000", None, None,
     "§7 / S10"),
    # ── Emirati minimum salary (spec §5, F7; S5, S6) — blocking from 1 Jul 2026 ─
    ("ae_emirati_min_salary", "Emirati minimum monthly salary (MoHRE private sector)", None, None, "6000",
     None, date(2026, 7, 1), "§5, AE-014, F7 / S5, S6"),
    # ── Traditional end-of-service gratuity (spec §9, F1, F2; S12) ─────────
    ("ae_eos_min_service_years", "End of service — minimum continuous service (years)", None, None, "1",
     None, None, "§9 / S12"),
    ("ae_eos_band_years", "End of service — years in the first band", None, None, "5", None, None, "§9 / S12"),
    ("ae_eos_days_first_band", "End of service — days of Basic Wage per year (first band)", None, None, "21",
     None, None, "§9, F1 / S12"),
    ("ae_eos_days_after_band", "End of service — days of Basic Wage per year (after the first band)", None, None,
     "30", None, None, "§9, F2 / S12"),
    ("ae_eos_day_divisor", "End of service — days in a month for the daily Basic Wage", None, None, "30",
     None, None, "F1, F2"),
    ("ae_eos_cap_months_wage", "End of service — cap in months of total Wage (two years)", None, None, "24",
     None, None, "§9 / S12"),
    # ── Alternative end-of-service savings scheme (spec §10, F3; S13) ──────
    ("ae_eos_savings_up_to_band", "Savings scheme — employer subscription, service up to the band",
     None, "0.0583", None, None, None, "§10, F3 / S13"),
    ("ae_eos_savings_over_band", "Savings scheme — employer subscription, service over the band",
     None, "0.0833", None, None, None, "§10, F3 / S13"),
    ("ae_eos_savings_band_years", "Savings scheme — service years of the lower band", None, None, "5", None, None,
     "§10 / S13"),
    # ── Overtime premiums on Basic hourly pay (spec §11, F6; S14) ──────────
    ("ae_ot_ordinary", "Overtime premium — ordinary", "0.25", None, None, None, None, "§11, F6 / S14"),
    ("ae_ot_night", "Overtime premium — night (10pm-4am, non-shift)", "0.50", None, None, None, None,
     "§11, F6 / S14"),
    ("ae_ot_rest_day", "Overtime premium — rest day / public holiday (no substitute rest)", "0.50", None, None,
     None, None, "§11 / S14"),
    ("ae_ot_hours_per_day", "Overtime — normal hours per day (Basic hourly pay = daily Basic Wage / this)",
     None, None, "8", None, None, "§11 / S14"),
    # ── Final settlement (spec §9, §19; S12, S22) ──────────────────────────
    ("ae_final_settlement_days", "Final settlement — days from contract end to pay all entitlements",
     None, None, "14", None, None, "§9, §19, AE-032 / S12"),
)
