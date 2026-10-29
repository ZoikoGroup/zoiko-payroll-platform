// South Africa display helpers only. Statutory values live in the pack's
// canonical ContributionRate / TaxSlab rows, never in the frontend.

export function formatZarAuto(amount) {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return String(amount);
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency: "ZAR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatZarCompact(amount) {
  if (amount === null || amount === undefined) return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return String(amount);
  if (n >= 1000000) return `R${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `R${(n / 1000).toFixed(0)}K`;
  return `R${n.toLocaleString()}`;
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
    return new Date(dateStr).toLocaleDateString("en-ZA", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
}

export function describeBand(row) {
  if (!row) return "—";
  const min = row.minAmount != null ? formatZarAuto(row.minAmount) : "0";
  const max = row.maxAmount != null ? formatZarAuto(row.maxAmount) : "and above";
  return `${min} – ${max}`;
}

export function rateByKey(rates, key) {
  return (rates || []).find((row) => row.componentKey === key);
}
