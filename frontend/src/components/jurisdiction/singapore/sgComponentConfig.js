// Singapore-only catalogue: which CPF cohorts / age bands / wage bands and
// SHG funds exist, how each canonical componentKey is presented, and the
// client-side Compliance Health evaluation. Follows the same structure as
// uk/ukComponentConfig.js and india/inComponentConfig.js — nothing shared
// depends on it. Every figure shown comes from the pack's own
// ContributionRate/TaxSlab rows; nothing statutory is hardcoded here.
//
// Row conventions mirror backend engine/countries/singapore.py:
//   CPF_RATE_BAND  filingStatus = cohort, taxRegime = age band,
//                  assessmentBasis = NIL | ER_ONLY | PHASE_IN | FULL,
//                  ratePct = employee % (PHASE_IN: phase-in factor × 100),
//                  employerRatePct = employer %
//   SHG_FUND_BAND  filingStatus = fund code, flatAmount = monthly amount
// ContributionRate percentages are FRACTIONS (0.0025 = 0.25%).

export const CPF_RATE_BAND = "CPF_RATE_BAND";
export const SHG_FUND_BAND = "SHG_FUND_BAND";

export const CPF_COHORTS = [
  { key: "SC_SPR3", label: "Citizen / SPR year 3+" },
  { key: "SPR1_GG", label: "SPR year 1 — graduated (G/G)" },
  { key: "SPR1_FG", label: "SPR year 1 — full employer (F/G)" },
  { key: "SPR1_FF", label: "SPR year 1 — full (F/F)" },
  { key: "SPR2_GG", label: "SPR year 2 — graduated (G/G)" },
  { key: "SPR2_FG", label: "SPR year 2 — full employer (F/G)" },
  { key: "SPR2_FF", label: "SPR year 2 — full (F/F)" },
];

export const CPF_AGE_BANDS = [
  { key: "AGE_LE_55", label: "≤ 55" },
  { key: "AGE_55_60", label: "> 55 – 60" },
  { key: "AGE_60_65", label: "> 60 – 65" },
  { key: "AGE_65_70", label: "> 65 – 70" },
  { key: "AGE_GT_70", label: "> 70" },
];

// Total-wage bands (ZP-SG-ENG-001 §3) — each is its own statutory row; the
// full-rate percentage is never extrapolated downward.
export const CPF_WAGE_BANDS = [
  { basis: "NIL", label: "≤ S$50", min: 0, max: 50 },
  { basis: "ER_ONLY", label: "> S$50 – 500", min: 50, max: 500 },
  { basis: "PHASE_IN", label: "> S$500 – 750", min: 500, max: 750 },
  { basis: "FULL", label: "> S$750", min: 750, max: null },
];

export const SHG_FUNDS = [
  { key: "CDAC", label: "CDAC" },
  { key: "ECF", label: "ECF" },
  { key: "MBMF", label: "MBMF" },
  { key: "SINDA", label: "SINDA" },
];

export const NOT_CONFIGURED = "Statutory rule not configured";
export const CPF_BLOCKED = "Calculation blocked — authoritative CPF rule required.";

// Operational workflows that deliberately do NOT exist in this phase —
// shown as status only, never as actions (ZP-SG-ENG-001 §7/§8/§13).
export const NOT_BUILT = {
  aisApi: "EXPORT ONLY / API NOT READY",
  cpfEzpay: "EXPORT READY — the employer uploads it through CPF EZPay (Corppass)",
  momLevyImport: "NOT BUILT",
};

// The IR8A extract (POST /api/payroll/singapore/reports/ir8a) is an
// export only — it is never reported as submitted to IRAS.
export const IR8A_STATUS = "EXPORT_READY";

// IR21 case lifecycle (backend sgp_ir21_cases, tenant "IR21 Tax Clearance"
// tab): pay is held while DRAFT/FILED/CLEARED/EXCEPTION; RELEASED / EXEMPT /
// CANCELLED lift the hold and need a distinct approver.
export const IR21_STATUSES = ["DRAFT", "FILED", "CLEARED", "RELEASED", "EXEMPT", "CANCELLED", "EXCEPTION"];
export const IR21_WORKFLOW = "TENANT CASE WORKFLOW (hold / clearance / release)";

// ZP-SG-ENG-001 §18 — none can be marked passed from this UI; each needs
// external evidence this phase does not produce.
export const PRODUCTION_GATES = [
  { key: "G1", label: "CPF content certification" },
  { key: "G2", label: "CPF operations (EZPay file, payment, reconciliation)" },
  { key: "G3", label: "IRAS AIS (YA2027 model, API/export, amendments)" },
  { key: "G4", label: "IR21 tax clearance" },
  { key: "G5", label: "Foreign workforce (levy billing, LQS/PWM)" },
  { key: "G6", label: "Labour pay (Employment Act)" },
  { key: "G7", label: "Security / privacy (PDPA, NRIC/FIN masking)" },
  { key: "G8", label: "Two-cycle parallel payroll + AIS simulation" },
];

export function rateByKey(rates, key) {
  return (rates || []).find((r) => r.componentKey === key) || null;
}

export function cpfRows(slabs) {
  return (slabs || []).filter((s) => s.ruleType === CPF_RATE_BAND);
}

export function findCpfCell(slabs, cohort, ageBand, basis) {
  return cpfRows(slabs).filter((s) => s.filingStatus === cohort && s.taxRegime === ageBand && s.assessmentBasis === basis);
}

export function shgRows(slabs, fund) {
  return (slabs || [])
    .filter((s) => s.ruleType === SHG_FUND_BAND && s.filingStatus === fund)
    .sort((a, b) => Number(a.minAmount) - Number(b.minAmount));
}

export function formatSgd(value, { decimals = 2 } = {}) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `S$${n.toLocaleString("en-SG", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

// Whole-dollar amounts render without cents (8,000 not 8,000.00);
// anything with cents (11.25) keeps them.
export function formatSgdAuto(value) {
  const n = Number(value);
  return formatSgd(value, { decimals: Number.isInteger(n) ? 0 : 2 });
}

export function formatPct(value) {
  if (value === null || value === undefined || value === "") return "—";
  return `${Number(value)}%`;
}

export function fractionToPct(value) {
  if (value === null || value === undefined || value === "") return "—";
  return `${Number((Number(value) * 100).toFixed(4))}%`;
}

export function formatDate(value) {
  if (!value) return "—";
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
}

export function describeBand(row) {
  const min = Number(row.minAmount);
  const max = row.maxAmount === null || row.maxAmount === undefined ? null : Number(row.maxAmount);
  if (min === 0 && max !== null) return `≤ ${formatSgdAuto(max)}`;
  if (max === null) return `> ${formatSgdAuto(min)}`;
  return `> ${formatSgdAuto(min)} – ${formatSgdAuto(max)}`;
}

// ── Compliance Health ────────────────────────────────────────────────────
// Client-side, read-only evaluation of the selected pack's own rows —
// never calls Singapore COMPLIANT while any required statutory cohort is
// unconfigured (ZP-SG-ENG-001 §51 / SG-001).
export const HEALTH = { COMPLIANT: "COMPLIANT", WARNING: "WARNING", BLOCKED: "BLOCKED" };

function check(key, label, level, detail) {
  return { key, label, level, detail };
}

function hasOverlaps(rows) {
  const sorted = [...rows].sort((a, b) => Number(a.minAmount) - Number(b.minAmount));
  for (let i = 1; i < sorted.length; i += 1) {
    const prevMax = sorted[i - 1].maxAmount;
    if (prevMax === null || prevMax === undefined || Number(sorted[i].minAmount) < Number(prevMax)) return true;
  }
  return false;
}

export function evaluateSgHealth({ pack, rates, slabs, latestRun, aisCalendarEntry }) {
  const checks = [];
  const has = (key) => {
    const row = rateByKey(rates, key);
    return Boolean(row && (row.flatAmount != null || row.employerRatePct != null || row.employeeRatePct != null || row.textValue));
  };

  checks.push(check("pack", "SG RulePack exists", pack ? HEALTH.COMPLIANT : HEALTH.BLOCKED,
    pack ? `${pack.packId} v${pack.version} (${pack.status})` : "No Singapore tax pack"));
  checks.push(check("approval", "Pack approved and Active", pack?.status === "Active" ? HEALTH.COMPLIANT : HEALTH.WARNING,
    pack?.status === "Active" ? "Active" : `${pack?.status || "—"} — not in force; payroll resolves no Singapore pack`));
  checks.push(check("source", "Source evidence linked", pack?.sourceDocumentId ? HEALTH.COMPLIANT : HEALTH.BLOCKED,
    pack?.sourceDocumentId ? `Source artifact #${pack.sourceDocumentId}` : "No SourceArtifact linked — activation blocked"));

  const datesValid = Boolean(pack?.effectiveFrom) && (!pack?.effectiveTo || pack.effectiveTo >= pack.effectiveFrom)
    && [...(rates || []), ...(slabs || [])].every((r) => !r.effectiveFrom || !r.effectiveTo || r.effectiveTo >= r.effectiveFrom);
  checks.push(check("dates", "Effective dates valid", datesValid ? HEALTH.COMPLIANT : HEALTH.BLOCKED,
    datesValid ? `${formatDate(pack.effectiveFrom)} → ${pack.effectiveTo ? formatDate(pack.effectiveTo) : "open"}` : "Missing or inverted effective dates"));

  const cellCounts = {};
  cpfRows(slabs).forEach((s) => {
    const k = `${s.filingStatus}|${s.taxRegime}|${s.assessmentBasis}`;
    cellCounts[k] = (cellCounts[k] || 0) + 1;
  });
  const overlap = Object.values(cellCounts).some((n) => n > 1) || SHG_FUNDS.some((f) => hasOverlaps(shgRows(slabs, f.key)));
  checks.push(check("overlap", "No overlapping rules", overlap ? HEALTH.BLOCKED : HEALTH.COMPLIANT,
    overlap ? "Duplicate CPF cell or overlapping SHG band" : "No duplicates"));

  const missingCells = (cohorts, bases) => cohorts.flatMap((c) => CPF_AGE_BANDS.flatMap((a) => bases
    .filter((b) => findCpfCell(slabs, c, a.key, b).length === 0).map((b) => `${c}/${a.key}/${b}`)));
  const fullMissing = missingCells(["SC_SPR3"], ["FULL"]);
  checks.push(check("cpfFull", "CPF full-rate rows (Citizen / SPR3+)", fullMissing.length ? HEALTH.BLOCKED : HEALTH.COMPLIANT,
    fullMissing.length ? `${fullMissing.length} of 5 age bands not configured` : "All 5 age bands configured"));
  const lowMissing = missingCells(["SC_SPR3"], ["NIL", "ER_ONLY", "PHASE_IN"]);
  checks.push(check("cpfLow", "CPF low-wage rows", lowMissing.length ? HEALTH.BLOCKED : HEALTH.COMPLIANT,
    lowMissing.length ? `${lowMissing.length} of 15 cells not configured — wages ≤ S$750 BLOCKED` : "All low-wage cells configured"));
  const sprCohorts = CPF_COHORTS.filter((c) => c.key !== "SC_SPR3").map((c) => c.key);
  const sprMissing = missingCells(sprCohorts, CPF_WAGE_BANDS.map((b) => b.basis));
  checks.push(check("cpfSpr", "CPF SPR year 1 / 2 rows", sprMissing.length ? HEALTH.BLOCKED : HEALTH.COMPLIANT,
    sprMissing.length ? `${sprMissing.length} of 120 cells not configured — SPR years 1–2 BLOCKED` : "All SPR cells configured"));
  checks.push(check("owCeiling", "CPF OW ceiling", has("cpf_ow_ceiling_monthly") ? HEALTH.COMPLIANT : HEALTH.BLOCKED,
    has("cpf_ow_ceiling_monthly") ? formatSgdAuto(rateByKey(rates, "cpf_ow_ceiling_monthly").flatAmount) : NOT_CONFIGURED));
  checks.push(check("awCeiling", "CPF annual (AW) ceiling", has("cpf_annual_wage_ceiling") ? HEALTH.COMPLIANT : HEALTH.BLOCKED,
    has("cpf_annual_wage_ceiling") ? formatSgdAuto(rateByKey(rates, "cpf_annual_wage_ceiling").flatAmount) : NOT_CONFIGURED));
  checks.push(check("ageRule", "CPF age-band boundary rule", has("cpf_age_band_semantics") ? HEALTH.COMPLIANT : HEALTH.WARNING,
    has("cpf_age_band_semantics") ? rateByKey(rates, "cpf_age_band_semantics").textValue : "Not configured — employees at age 55/60/65/70 in their boundary year are BLOCKED"));
  checks.push(check("rounding", "CPF rounding", HEALTH.COMPLIANT,
    "Statutory sequence implemented in the engine (total → nearest $, employee → down, employer = residual)"));

  const sdlOk = ["sdl", "sdl_min_monthly", "sdl_max_monthly"].every(has);
  checks.push(check("sdl", "SDL", sdlOk ? HEALTH.COMPLIANT : HEALTH.BLOCKED, sdlOk ? "Rate, minimum and maximum configured" : NOT_CONFIGURED));
  const shgMissing = SHG_FUNDS.filter((f) => shgRows(slabs, f.key).length === 0).map((f) => f.key);
  checks.push(check("shg", "SHG (CDAC / ECF / MBMF / SINDA)", shgMissing.length ? HEALTH.BLOCKED : HEALTH.COMPLIANT,
    shgMissing.length ? `Not configured: ${shgMissing.join(", ")}` : "All four funds configured"));

  // LQS — every row in force for some part of the pack year (the pre-July
  // and from-1-July full-time rows coexist, each with its own window).
  const lqsFt = (rates || []).filter((r) => r.componentKey === "lqs_full_time_monthly");
  const lqsPt = (rates || []).filter((r) => r.componentKey === "lqs_part_time_hourly");
  const earliest = (rows) => rows.map((r) => r.effectiveFrom || pack?.effectiveFrom || "").sort()[0];
  const ftCovers = lqsFt.length > 0 && earliest(lqsFt) <= (pack?.effectiveFrom || "");
  const ptCovers = lqsPt.length > 0 && earliest(lqsPt) <= (pack?.effectiveFrom || "");
  const lqsLevel = lqsFt.length === 0 ? HEALTH.BLOCKED : (ftCovers && ptCovers ? HEALTH.COMPLIANT : HEALTH.WARNING);
  checks.push(check("lqs", "LQS", lqsLevel,
    lqsFt.length === 0 ? NOT_CONFIGURED
      : lqsFt.map((r) => `FT ${formatSgdAuto(r.flatAmount)} from ${formatDate(r.effectiveFrom || pack?.effectiveFrom)}`).join("; ")
        + (ptCovers ? "" : ` — part-time LQS before ${formatDate(earliest(lqsPt) || "")}: BLOCKED — AUTHORITATIVE VALUE REQUIRED`)));
  checks.push(check("pwm", "PWM sector wage tables", HEALTH.WARNING,
    "BLOCKED — AUTHORITATIVE VALUE REQUIRED: no PWM tables configured (an applicable PWM cohort cannot be checked)"));

  checks.push(check("fwl", "Foreign Worker Levy", has("fwl_s_pass_monthly") ? HEALTH.WARNING : HEALTH.BLOCKED,
    has("fwl_s_pass_monthly")
      ? `S Pass ${formatSgdAuto(rateByKey(rates, "fwl_s_pass_monthly").flatAmount)}/month (employer cost), partial month at MOM's daily rate from the pass issue date; a pass ending within a month and Work Permit tiers BLOCKED — AUTHORITATIVE VALUE REQUIRED`
      : "S Pass levy not configured"));

  const unevidenced = [...(rates || []), ...(slabs || [])].filter((r) => !r.sourceDocumentId).length;
  checks.push(check("rowEvidence", "Per-rule source evidence", unevidenced === 0 ? HEALTH.COMPLIANT : HEALTH.WARNING,
    unevidenced === 0 ? "Every rule row links a SourceArtifact"
      : `${unevidenced} row(s) without their own SourceArtifact (specification-only values) — pack-level evidence applies`));

  const aisOk = has("ais_mandatory_employee_threshold") && Boolean(aisCalendarEntry);
  checks.push(check("ais", "IRAS AIS / IR8A", aisOk ? HEALTH.WARNING : HEALTH.BLOCKED,
    aisOk ? `Threshold and ${formatDate(aisCalendarEntry.dueDate)} deadline configured — IR8A extract ${IR8A_STATUS}; AIS-API submission NOT READY`
      : "AIS threshold or filing-calendar deadline missing"));
  checks.push(check("ir21", "IR21 tax clearance", HEALTH.WARNING, `${IR21_WORKFLOW} — not yet validated against current IRAS guidance (gate G4)`));

  const runLevel = latestRun?.status === "PASS" ? HEALTH.COMPLIANT : HEALTH.BLOCKED;
  checks.push(check("golden", "Golden vectors passing", runLevel,
    latestRun ? `Latest run #${latestRun.id}: ${latestRun.status} (${latestRun.passedCases}/${latestRun.totalCases})` : "No certification run yet"));

  const overall = checks.some((c) => c.level === HEALTH.BLOCKED) ? HEALTH.BLOCKED
    : checks.some((c) => c.level === HEALTH.WARNING) ? HEALTH.WARNING : HEALTH.COMPLIANT;
  return { overall, checks };
}
