"""modules/payroll/engine/countries/spain_content.py
--------------------------------------------------
Spain (ZP-ES-ENG-001 v1.0, 22 Sep 2026; docs/spain) — the statutory values the
Spanish canonical pack is seeded with. This is SEED DATA, not engine constants:
scripts/seed_spain_canonical_pack.py writes these rows into
payroll_contribution_rates under pack ES-PAYROLL-2026, Super Admin can edit them
(Compliance → Spain → Contribution Rates) and the engine only ever reads the
pack. A value missing from the pack stops the calculation with a named reason
(ES_RATE_MISSING:<key>); there is no fallback.

Percentages are FRACTIONS (0.047 = 4.70%), like every ContributionRate row.
Every row names the spec section and the official source from the spec's
evidence register (§24: S1 SMI, S2 bases, S3 rates, S4 Orden PJC/297/2026,
S5 solidarity).

Deliberately NOT here because the spec gives no value (docs/spain gaps; the
engine blocks with a clear message until a Super Admin adds the rows from an
official source):
  * G-01 every IRPF withholding parameter (both 2026 AEAT algorithms) — rows
    irpf_a_* (to 9 Sep 2026) / irpf_b_* (from 10 Sep 2026), seeded only from
    the AEAT "Algoritmo de cálculo de retenciones 2026" document;
  * G-02 the minimum contribution bases of groups 1, 2 and 3
    (es_base_min_group_1 / _2 / _3);
  * G-03 the AT/EP premium (employer fact, per the employer's own tariff);
  * G-04 part-time hourly minimum bases.
"""
from datetime import date

PACK_ID = "ES-PAYROLL-2026"
CURRENCY = "EUR"
EFFECTIVE_FROM = date(2026, 1, 1)
REGULATORY_AUTHORITY = "TGSS / Seguridad Social, AEAT"
SOURCE_REFERENCES = ("ZP-ES-ENG-001 v1.0 (22 Sep 2026), evidence register S1 (RD 126/2026), S2-S3 (Seguridad Social "
                     "2026 bases and rates), S4 (Orden PJC/297/2026), S5 (solidarity contribution)")

# (component_key, label, employee fraction, employer fraction, flat amount, text value, row effective_from, source)
RATES = (
    # ── Ordinary Social Security contributions (spec §2, §4; S3, S4) ────────
    ("es_cc", "Common contingencies (contingencias comunes)", "0.047", "0.236", None, None, None, "§2, §4 / S3"),
    ("es_mei", "Intergenerational equity mechanism (MEI)", "0.0015", "0.0075", None, None, None, "§2 / S3"),
    ("es_unemployment_general", "Unemployment — general (indefinite and qualifying contracts)", "0.0155", "0.055",
     None, None, None, "§2, §4 / S3"),
    ("es_unemployment_temporary", "Unemployment — fixed-term (temporary) contract", "0.016", "0.067",
     None, None, None, "§2, §4, F4 / S3"),
    ("es_fogasa", "FOGASA (wage guarantee fund) — employer only", None, "0.002", None, None, None, "§2, §4 / S3"),
    ("es_training", "Professional training (formación profesional)", "0.001", "0.006", None, None, None,
     "§2, §4 / S3"),
    # ── Additional contribution on overtime pay (spec §4; S3) ───────────────
    ("es_overtime_force_majeure", "Overtime contribution — force majeure (fuerza mayor)", "0.02", "0.12",
     None, None, None, "§4 / S3"),
    ("es_overtime_other", "Overtime contribution — other overtime", "0.047", "0.236", None, None, None, "§4 / S3"),
    # ── 2026 solidarity contribution above the maximum base (spec §5; S4, S5) ─
    ("es_solidarity_t1", "Solidarity contribution — tranche 1 (max base to tranche-1 upper bound)", "0.0019",
     "0.0096", None, None, None, "§5, ES-011, F1 / S5"),
    ("es_solidarity_t1_upper", "Solidarity tranche 1 — upper bound (monthly remuneration)", None, None, "5611.32",
     None, None, "§5 / S5"),
    ("es_solidarity_t2", "Solidarity contribution — tranche 2 (tranche-1 upper to tranche-2 upper)", "0.0021",
     "0.0104", None, None, None, "§5, F2 / S5"),
    ("es_solidarity_t2_upper", "Solidarity tranche 2 — upper bound (monthly remuneration)", None, None, "7651.80",
     None, None, "§5 / S5"),
    ("es_solidarity_t3", "Solidarity contribution — tranche 3 (above tranche-2 upper)", "0.0024", "0.0122",
     None, None, None, "§5, F2 / S5"),
    # ── Contribution bases (spec §2, §3; S2) ────────────────────────────────
    ("es_base_max_monthly", "Maximum contribution base (monthly)", None, None, "5101.20", None, None,
     "§2, §3, F1 / S2"),
    ("es_base_max_daily", "Maximum contribution base (daily)", None, None, "170.04", None, None, "§2 / S2"),
    ("es_base_min_group_4_7", "Minimum contribution base — groups 4 to 7 (monthly)", None, None, "1424.40",
     None, None, "§2 / S2"),
    ("es_base_min_group_8_11", "Minimum contribution base — groups 8 to 11 (daily)", None, None, "47.48",
     None, None, "§2 / S2"),
    # ── Minimum wage (SMI, spec §2, §15; S1) ────────────────────────────────
    ("es_smi_monthly", "Minimum interprofessional wage (SMI) — monthly", None, None, "1221", None, None,
     "§2, §15 / S1"),
    ("es_smi_daily", "Minimum interprofessional wage (SMI) — daily", None, None, "40.70", None, None, "§2 / S1"),
    ("es_smi_annual", "Minimum interprofessional wage (SMI) — annual full-time reference", None, None, "17094",
     None, None, "§2, §15 / S1"),
    # ── Short fixed-term contract surcharge (spec §2, ES-010, F4; S4) ───────
    ("es_short_contract_surcharge", "Short fixed-term contract — employer additional contribution at termination",
     None, None, "33.62", None, None, "§2, ES-010, F4 / S4"),
    ("es_short_contract_days", "Short fixed-term contract — length below which the surcharge applies (days)",
     None, None, "30", None, None, "§2, ES-010 / S4"),
)
