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
