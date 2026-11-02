// Japan display helpers only. Statutory values live in the pack's
// canonical ContributionRate / TaxSlab rows, never in the frontend.

export function formatJpyAuto(amount) {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return String(amount);
  return new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n);
}

export function formatJpyCompact(amount) {
  if (amount === null || amount === undefined) return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return String(amount);
  if (n >= 100000000) return `${(n / 100000000).toFixed(1)}B`;
  if (n >= 10000) return `${(n / 10000).toFixed(0)}万`;
  return formatJpyAuto(amount);
}

export function formatPct(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return `${n.toFixed(2)}%`;
}

export function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("ja-JP", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
}

export function describeBand(row) {
  if (!row) return "—";
  const min = row.minAmount != null ? formatJpyAuto(row.minAmount) : "0";
  const max = row.maxAmount != null ? formatJpyAuto(row.maxAmount) : "and above";
  return `${min} – ${max}`;
}

export function rateByKey(rates, key) {
  return (rates || []).find((row) => row.componentKey === key);
}