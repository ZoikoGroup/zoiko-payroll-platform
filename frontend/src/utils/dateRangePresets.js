// Shared date-range preset resolver, reused by every Super Admin module
// that needs "Today / This Month / This Quarter / Custom Range" style
// filtering (Finance, Reports, Dashboard). No such utility existed before
// this — each new module would otherwise reimplement the same date math.

export const DATE_RANGE_PRESETS = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "thisWeek", label: "This Week" },
  { id: "thisMonth", label: "This Month" },
  { id: "previousMonth", label: "Previous Month" },
  { id: "thisQuarter", label: "This Quarter" },
  { id: "previousQuarter", label: "Previous Quarter" },
  { id: "thisYear", label: "This Year" },
  { id: "custom", label: "Custom Range" },
];

function pad(n) {
  return String(n).padStart(2, "0");
}

export function toISODate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function startOfWeek(d) {
  const date = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const day = date.getDay(); // 0 (Sun) .. 6 (Sat)
  const diff = (day === 0 ? -6 : 1) - day; // shift back to Monday
  date.setDate(date.getDate() + diff);
  return date;
}

function quarterOf(month) {
  return Math.floor(month / 3); // 0-3
}

/**
 * Resolves a preset id (see DATE_RANGE_PRESETS) into a concrete
 * { startDate, endDate } pair of ISO "YYYY-MM-DD" strings (both
 * inclusive), suitable for the ?start_date=&end_date= query params every
 * new Super Admin endpoint accepts. For "custom", pass through the
 * caller-supplied customStart/customEnd untouched.
 */
export function resolveDateRange(presetId, customStart, customEnd) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  switch (presetId) {
    case "today":
      return { startDate: toISODate(today), endDate: toISODate(today) };

    case "yesterday": {
      const y = new Date(today);
      y.setDate(y.getDate() - 1);
      return { startDate: toISODate(y), endDate: toISODate(y) };
    }

    case "thisWeek": {
      const start = startOfWeek(today);
      return { startDate: toISODate(start), endDate: toISODate(today) };
    }

    case "thisMonth": {
      const start = new Date(today.getFullYear(), today.getMonth(), 1);
      return { startDate: toISODate(start), endDate: toISODate(today) };
    }

    case "previousMonth": {
      const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const end = new Date(today.getFullYear(), today.getMonth(), 0);
      return { startDate: toISODate(start), endDate: toISODate(end) };
    }

    case "thisQuarter": {
      const q = quarterOf(today.getMonth());
      const start = new Date(today.getFullYear(), q * 3, 1);
      return { startDate: toISODate(start), endDate: toISODate(today) };
    }

    case "previousQuarter": {
      const q = quarterOf(today.getMonth());
      const prevQStartMonth = q * 3 - 3;
      const start = new Date(today.getFullYear(), prevQStartMonth, 1);
      const end = new Date(today.getFullYear(), prevQStartMonth + 3, 0);
      return { startDate: toISODate(start), endDate: toISODate(end) };
    }

    case "thisYear": {
      const start = new Date(today.getFullYear(), 0, 1);
      return { startDate: toISODate(start), endDate: toISODate(today) };
    }

    case "custom":
      return { startDate: customStart || "", endDate: customEnd || "" };

    default:
      return { startDate: "", endDate: "" };
  }
}
