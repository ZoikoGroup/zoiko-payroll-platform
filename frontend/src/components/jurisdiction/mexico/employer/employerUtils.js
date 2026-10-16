// Non-component helpers for the Mexico employer panels (kept apart for React fast refresh).

// The user's LOCAL calendar date as YYYY-MM-DD — sent explicitly as `on`
// (the API requires it; the server date is never used).
export function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const statusTone = {
  PASS: "bg-success/15 text-success", WARNING: "bg-warning/15 text-warning", BLOCKED: "bg-error/10 text-error",
  NOT_STARTED: "bg-surface-muted text-foreground-muted", FAIL: "bg-error/10 text-error",
  BLOCKED_CONTENT: "bg-warning/15 text-warning", ACTIVE: "bg-success/15 text-success", DRAFT: "bg-surface-muted text-foreground-muted",
  PENDING_PACK: "bg-warning/15 text-warning", SUPERSEDED: "bg-surface-muted text-foreground-muted",
  ROTATED: "bg-surface-muted text-foreground-muted", REVOKED: "bg-error/10 text-error", CLOSED: "bg-surface-muted text-foreground-muted",
  UNRESOLVED: "bg-warning/15 text-warning",
};

export const blankToNull = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v === "" ? null : v]));
