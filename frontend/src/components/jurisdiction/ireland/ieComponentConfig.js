// Ireland Compliance UI config (ZP-IE-ENG-001) — plain component-key
// lists grouping the statutory rows each tab displays. Mirrors
// auComponentConfig.js's own role for Australia: key lists only, no
// component logic, no values.
//
// The keys are exactly the 41 IE_PARAMETER_KEYS entries that
// backend/app/modules/payroll/engine/countries/ireland.py reads out of
// rate_map. A key missing here would be invisible in the UI yet still
// hard-block every Ireland run (IE_STATUTORY_CONTENT_NOT_CONFIGURED) —
// tests/test_ireland_statutory_catalog.py asserts the backend catalog and
// this grouping cover the same key set.

// PAYE statutory rates (IE-003). The per-employee standard-rate band and
// tax credit are NOT here: they come from Revenue's own frozen RPN
// instruction per employee (IE-005), never from pack content.
export const IE_PAYE_COMPONENT_KEYS = [
  "ie_tax_standard_pct",
  "ie_tax_higher_pct",
];

// Universal Social Charge (IE-009/IE-010). The band limits are annual
// totals; the engine divides them by periods-per-year itself.
export const IE_USC_COMPONENT_KEYS = [
  "ie_usc_band1_limit",
  "ie_usc_band1_pct",
  "ie_usc_band2_limit",
  "ie_usc_band2_pct",
  "ie_usc_band3_limit",
  "ie_usc_band3_pct",
  "ie_usc_above_pct",
];

// PRSI, Class A only for the certified launch cohort (IE-001/IE-016).
// The six rate keys each carry TWO dated rows — to 30 September 2026 and
// from 1 October 2026 — selected by pay date, never by earning period.
export const IE_PRSI_COMPONENT_KEYS = [
  "ie_prsi_a0_ee_pct",
  "ie_prsi_a0_er_pct",
  "ie_prsi_ax_ee_pct",
  "ie_prsi_ax_er_pct",
  "ie_prsi_al_ee_pct",
  "ie_prsi_al_er_pct",
  "ie_prsi_a1_ee_pct",
  "ie_prsi_a1_er_pct",
  "ie_prsi_band_a0_max",
  "ie_prsi_band_ax_max",
  "ie_prsi_band_al_max",
  "ie_prsi_ax_credit_max",
  "ie_prsi_ax_credit_lower",
];

// The four certified PRSI subclasses, and which key pair each reads.
// The employee's class is an ELIGIBILITY RESULT resolved by preflight
// (IE-016), not a free-form admin choice — this list only labels the
// resulting rows.
export const IE_PRSI_LAUNCH_SUBCLASSES = ["A0", "AX", "AL", "A1"];

// MyFutureFund (IE-018/IE-020). The 0.5% State contribution is
// administered by NAERSA and is never deducted from pay; the engine
// reports it separately as ie_mff_state_topup.
export const IE_MFF_COMPONENT_KEYS = [
  "ie_mff_ee_pct",
  "ie_mff_er_pct",
  "ie_mff_state_topup_pct",
  "ie_mff_earnings_threshold",
];

// Local Property Tax (IE-003). Deducted only when Revenue instructs it on
// the RPN; the rate itself is an authority instruction, not pack content.
// This is the annual exemption threshold only.
export const IE_LPT_COMPONENT_KEYS = ["ie_lpt_exemption_threshold"];

// National Minimum Wage by age band, plus Statutory Sick Pay (IE-035,
// IE-036). The engine blocks rather than warns on an NMW breach.
export const IE_LABOUR_COMPONENT_KEYS = [
  "ie_nmw_hourly_under_18",
  "ie_nmw_hourly_18",
  "ie_nmw_hourly_19",
  "ie_nmw_hourly_20_plus",
  "ie_sick_leave_days",
  "ie_sick_leave_pct",
  "ie_sick_leave_daily_cap",
  "ie_sick_leave_service_weeks",
];

// Emergency PAYE basis (IE-008/IE-031) plus the reference single-person
// figures. The emergency path is used only when Revenue has issued no RPN
// and the employee has a recorded reason and week counter.
export const IE_EMERGENCY_COMPONENT_KEYS = [
  "ie_emergency_standard_cutoff_initial",
  "ie_emergency_weekly_cutoff_increment",
  "ie_emergency_weeks_per_increment",
  "ie_emergency_weekly_tax_credit",
  "ie_reference_standard_band_single",
  "ie_reference_credit_single",
];

// Every key above, for the "Tax Slabs" tab's supplementary configuration
// and for any test that needs the full IE surface.
export const IE_ALL_COMPONENT_KEYS = [
  ...IE_PAYE_COMPONENT_KEYS,
  ...IE_USC_COMPONENT_KEYS,
  ...IE_PRSI_COMPONENT_KEYS,
  ...IE_MFF_COMPONENT_KEYS,
  ...IE_LPT_COMPONENT_KEYS,
  ...IE_LABOUR_COMPONENT_KEYS,
  ...IE_EMERGENCY_COMPONENT_KEYS,
];

export function labelForIePrsiSubclass(subclass) {
  return (
    {
      A0: "A0 — no employee contribution (employer only)",
      AX: "AX — tapered credit applies",
      AL: "AL — lower band",
      A1: "A1 — standard employee contribution",
    }[subclass] || subclass || "—"
  );
}
