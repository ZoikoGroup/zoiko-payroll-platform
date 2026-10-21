// UTC-safe time helpers (ZP-PRIV).
//
// The API sends naive UTC timestamps (repo convention) and the newer endpoints
// append a trailing "Z". `new Date("2026-10-19T10:00:00")` would be read as
// LOCAL time and every countdown / "overdue" check would be off by the
// viewer's offset, so always parse API timestamps with parseUtc.

export function parseUtc(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const text = String(value);
  const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(text);
  const date = new Date(hasZone ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function msUntil(value, now = Date.now()) {
  const date = parseUtc(value);
  return date ? date.getTime() - now : null;
}

// "mm:ss" (or "h:mm:ss"), "expired" once the time has passed.
export function formatCountdown(ms) {
  if (ms == null) return "--:--";
  if (ms <= 0) return "expired";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatDateTime(value) {
  const date = parseUtc(value);
  return date ? date.toLocaleString() : "—";
}
