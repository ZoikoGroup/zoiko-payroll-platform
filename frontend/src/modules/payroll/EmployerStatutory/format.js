import { formatDateTime } from "../../../utils/time";

// Primitive values only — objects/arrays are never dumped as raw JSON.
export function display(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return "—";
  return String(value);
}

// Read a response field that may be camelCase or snake_case (the Saudi
// endpoints serialize by their snake_case alias).
export function pick(row, camel, snake) {
  if (!row) return undefined;
  return row[camel] !== undefined ? row[camel] : row[snake];
}

// Timestamps (naive UTC from the API) always go through parseUtc via
// formatDateTime. Plain calendar dates ("2026-01-01") are shown as-is —
// they carry no time zone and must not shift by the viewer's offset.
export const when = (value) => (value ? formatDateTime(value) : "—");
export const day = (value) => (value ? String(value).slice(0, 10) : "—");
export const period = (from, to) => `${day(from)} → ${to ? day(to) : "open"}`;
export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// "" -> null, otherwise trimmed string.
export const opt = (value) => {
  if (value === null || value === undefined) return null;
  const t = String(value).trim();
  return t === "" ? null : t;
};

export const isNumber = (value) => value !== "" && value !== null && value !== undefined && !Number.isNaN(Number(value));
