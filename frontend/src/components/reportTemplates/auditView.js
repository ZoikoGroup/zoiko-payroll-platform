// How one report-template audit row reads in the Audit tab.
//  - A key whose value is missing / null / "" on both sides did not change, so
//    it is not listed (an "approvedById: — → —" row said nothing).
//  - A refused lifecycle move ("refused" rows, recorded by the server for an
//    opted-in country) is one line, "Refused: Draft → Active". Before, it was
//    split into "status: Draft → —", "attempted: — → Active" and
//    "result: — → REFUSED", which read like three changes that never happened.
const blank = (v) => v === null || v === undefined || v === "";
const same = (a, b) => (blank(a) && blank(b)) || JSON.stringify(a) === JSON.stringify(b);
const show = (v) => (blank(v) ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
const REFUSAL_KEYS = ["status", "attempted", "result"];

export function describeAuditEntry(entry) {
  const oldValue = entry?.oldValue || {};
  const newValue = entry?.newValue || {};
  const refused = entry?.action === "refused" && !blank(newValue.attempted);
  const summary = refused ? `Refused: ${show(oldValue.status)} → ${show(newValue.attempted)}` : null;
  const rows = Object.keys({ ...oldValue, ...newValue })
    .filter((k) => !(refused && REFUSAL_KEYS.includes(k)))
    .filter((k) => !same(oldValue[k], newValue[k]))
    .map((k) => ({ key: k, from: show(oldValue[k]), to: show(newValue[k]) }));
  return { summary, rows };
}

// Who did it, for the Audit tab: the backend's actorName (first + last name),
// else "User #<id>", else a system process.
export function actorLabel(entry) {
  if (entry?.actorName) return entry.actorName;
  return entry?.actorId != null ? `User #${entry.actorId}` : "System";
}

// Two refused rows are the same attempt repeated when the same actor tried
// the same move from the same status and got the same reason.
const refusalSignature = (e) => (e?.action === "refused"
  ? JSON.stringify([e.actorId ?? null, e.oldValue?.status ?? null, e.newValue?.attempted ?? null, e.reason ?? null])
  : null);

// The Audit tab's rows, in the order given (newest first): consecutive
// identical refusals collapse into one group { kind: "refusals", count,
// latest, entries }; every other row stays { kind: "entry", entry }. Nothing
// is dropped or altered — a group keeps every attempt for its expanded view.
export function groupAuditEntries(entries) {
  const out = [];
  for (const entry of entries || []) {
    const sig = refusalSignature(entry);
    const last = out[out.length - 1];
    if (sig && last && last.signature === sig) {
      last.entries.push(entry);
      last.count += 1;
      continue;
    }
    out.push(sig ? { kind: "refusals", signature: sig, count: 1, latest: entry, entries: [entry] }
      : { kind: "entry", entry });
  }
  return out.map((g) => (g.kind === "refusals" && g.count === 1 ? { kind: "entry", entry: g.latest } : g));
}
