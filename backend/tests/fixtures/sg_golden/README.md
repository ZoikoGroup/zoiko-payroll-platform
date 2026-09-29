# Singapore (CPF Board / IRAS / MOM) golden-test fixtures

ZP-SG-ENG-001 v1.0 §17 ("Worked fixtures and QA acceptance matrix") —
run through the shared harness in `app/modules/payroll/hmrc_golden_harness.py`
by `tests/test_sg_golden.py` and by Super Admin's Test Certification
console (`run_golden_test_certification(jurisdiction_country="SG")`).

Singapore is fail-closed (no engine fallback), so every case supplies its
own `rate_map`/`slabs` — the same values `scripts/seed_singapore_canonical_pack.py`
seeds from the spec.

## What's here today

- `f1_citizen_le55_ow_6000.json` — F1: citizen ≤55, S$6,000 OW → CPF
  S$1,200 / S$1,020, SDL capped S$11.25.
- `f2_citizen_le55_ow_10000_ceiling.json` — F2: S$10,000 OW capped at the
  S$8,000 OW ceiling → S$1,600 / S$1,360.
- `f3_annual_aw_ceiling.json` — F3: YTD OW S$96,000 + S$20,000 bonus → only
  S$6,000 AW CPF-subject. The CPF amounts on that S$14,000 base are derived
  by the engine (not stated in the spec) and labelled as such.
- `f4_foreign_employment_pass.json` — F4: EP holder, S$9,000 → no CPF,
  SDL S$11.25.

### Official-source vectors (CPF Board, retrieved 2026-09-23)

The AW-ceiling cases reproduce the CPF Board's own worked figures from
"Examples for computation of Additional Wage (AW) Ceiling" (sha256
98fc7777…1220) — the method approved as Option A in place of SG-007's
year-to-date reading. Rates come from the CPF Board rate tables from
1 January 2026 (sha256 7ab21a34…9496).

- `cpfb_ex1_january_aw_estimated_ceiling.json` — estimated ceiling $6,000
  (not $94,000 under a year-to-date reading) → 2,380 / 2,800.
- `cpfb_ex2_february_ow_below_ceiling.json` — estimated ceiling $48,000.
- `cpfb_ex6_last_month_shortfall.json` — last-month re-calculation,
  $32,000 shortfall at January's rates → 6,800 / 8,000.
- `cpfb_ex9_june_last_month_shortfall_decimal_aw.json` /
  `cpfb_ex9_july_aw_after_leaving.json` — decimal AW chunks, then AW paid
  after leaving (official 5,377/6,325 and 2,784/3,274).
- `cpf_low_wage_phase_in_600.json`, `cpf_spr1_graduated_6000.json`,
  `cpf_spr2_full_employer_6000.json` — Tables 1, 2 and 5.
- `cpf_age_55_month_after_birthday.json` — the month-after-birthday rule.

## Incomplete month (Phase 5.2)

MOM "Monthly and daily salary": salary for an incomplete month = monthly
gross rate of pay ÷ working days in the month × days actually worked
(working days per MOM's `incomplete-month.xls`, June 2026 = 22 / 24 / 26 for
5 / 5.5 / 6-day weeks). Expected figures are computed independently of the
engine by the Phase 5.2 generator from that formula, CPF Board Table 1, SDL
0.25% ($2–$11.25) and the CDAC bands.

- `im_a_full_month.json` — complete month, no reduction.
- `im_b_joiner_mid_month.json`, `im_c_leaver_mid_month.json` — 11 / 10 of 22.
- `no_pay_leave_10_days.json` — RECOMPUTED in Phase 5.2 (was the platform's
  calendar-day formula): 12 of 22 → 3,272.73; a Saturday no-pay record is
  not a working day.
- `im_e_joiner_plus_no_pay.json`, `im_f_leaver_plus_no_pay.json`.
- `im_g_joiner_cpf_ceiling_on_payable.json` — CPF on the payable OW.
- `im_h_joiner_sdl_floor_low_wage.json` — employer-only CPF band, SDL $2 floor.
- `im_i_joiner_shg_band_on_payable.json` — CDAC band on the payable wage.
- `im_k_joiner_aw_not_prorated.json`, `im_l_joiner_overtime_ow_not_prorated.json`.
- `im_joiner_on_weekend.json`, `im_joiner_first_working_day_full_salary.json`,
  `im_joiner_5_5_day_week.json`, `im_leaver_6_day_week.json`.

Correction, replay-after-rate-change, YTD-after-correction and PWM for a
joiner are service-level scenarios (a persisted run is needed) and live in
`tests/test_singapore.py` (Phase 5.2 section).

- `wp_services_tier2_cancelled_mid_month.json` — Work Permit CANCELLED 15 Oct
  2026: MOM "Cancel a Work Permit" (sha256 2bc8e148…) — levy stops 1 day before
  cancellation → 1–14 Oct × S$19.73 = S$276.22.

## Not golden vectors (and why)

- F5 (IR21 hold) — the IR21 hold/release workflow is NOT BUILT in this
  phase; there is no calculation output to certify.
- F6 (LQS boundary) — LQS is a compliance threshold, not a payroll
  figure; its 1 Jul 2026 effective-date split is tested in
  `tests/test_singapore.py`.

Production certification (gate G1) additionally requires validation
against the CPF Board's own calculator and official tables — these
fixtures only reproduce the spec's own worked numbers.
