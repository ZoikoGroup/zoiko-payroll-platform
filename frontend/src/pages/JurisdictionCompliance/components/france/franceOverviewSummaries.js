// Pure, DOM-free France Compliance label/tone helpers (ZP-FR-ENG-001) so
// the France components stay thin and the mapping rules are unit-testable.

export const DUE_DATE_CLASS_LABELS = {
  M5: "5th of M+1 (>=50 employees)",
  M15: "15th of M+1 (50 employees)",
  DEFERRED_M15: "Deferred M15",
};

export const READINESS_STATUS_LABELS = {
  NOT_CONFIGURED: "Not configured",
  NOT_READY: "Not ready",
  READY: "Ready",
  LIVE: "Live",
};

// Tailwind chip classes per DSN lifecycle state (FR-032).
export const DSN_STATUS_CHIP = {
  DRAFT: "bg-surface-muted text-foreground-muted",
  VALIDATED: "bg-blue-100 text-blue-700",
  QUEUED: "bg-indigo-100 text-indigo-700",
  TRANSMITTED: "bg-purple-100 text-purple-700",
  ACKNOWLEDGED: "bg-teal-100 text-teal-700",
  BUSINESS_REJECTED: "bg-red-100 text-red-700",
  CRM_RESOLVED: "bg-amber-100 text-amber-700",
  UNKNOWN: "bg-orange-100 text-orange-700",
  SETTLED: "bg-green-100 text-green-700",
};

export const OUTBOX_STATUS_CHIP = {
  PENDING: "bg-surface-muted text-foreground-muted",
  SENT: "bg-blue-100 text-blue-700",
  ACKNOWLEDGED: "bg-green-100 text-green-700",
  UNKNOWN: "bg-orange-100 text-orange-700",
  FAILED: "bg-red-100 text-red-700",
};

export const FNAL_CLASS_LABELS = {
  UNDER_50: "FNAL 0.10% (fewer than 50)",
  OVER_50: "FNAL 0.50% (50+)",
};

export const CFP_CLASS_LABELS = {
  UNDER_11: "CFP 0.55% (fewer than 11)",
  OVER_11: "CFP 1.00% (11+)",
};

export const PAS_RATE_STATUS_CHIP = {
  ACTIVE: "bg-green-100 text-green-700",
  PENDING: "bg-amber-100 text-amber-700",
  STALE: "bg-surface-muted text-foreground-muted",
  CORRECTED: "bg-red-100 text-red-700",
};

export function countLabel(singular, plural) {
  return (n) => `${n} ${n === 1 ? singular : plural}`;
}

export function dueDateClassLabel(cls) {
  return DUE_DATE_CLASS_LABELS[cls] || cls || "—";
}

export function readinessLabel(status) {
  return READINESS_STATUS_LABELS[status] || status || "Not configured";
}

export function readinessChip(status) {
  if (status === "READY" || status === "LIVE") {
    return "bg-green-100 text-green-700";
  }
  return "bg-amber-100 text-amber-700";
}

// Ordered threshold history from the profile's effectifState dict
// ({year: {value, source}, ...}), newest first.
export function effectifHistory(effectifState) {
  if (!effectifState) return [];
  return Object.entries(effectifState)
    .map(([year, info]) => ({
      year: Number(year),
      value: typeof info === "object" ? info.value : info,
      source: typeof info === "object" ? info.source : "DSN",
    }))
    .sort((a, b) => b.year - a.year);
}

export function latestEffectif(effectifState) {
  const history = effectifHistory(effectifState);
  return history.length ? history[0] : null;
}