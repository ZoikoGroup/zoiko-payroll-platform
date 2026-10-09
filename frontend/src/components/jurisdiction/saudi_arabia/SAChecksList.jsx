// Shared Saudi Arabia BLOCK / WARN / INFO list — renders the server's
// engine/jurisdictions/saudi_arabia/preflight.py check dicts verbatim. The status
// shown is the server's own summarize() result; this component never derives
// a status of its own, so it can never show CLEAR for something the server
// would refuse (a BLOCK makes advance_payroll_run_status return 409).

const SEVERITY_STYLE = {
  BLOCK: "bg-error/10 text-error border-error/30",
  WARN: "bg-warning/10 text-warning border-warning/30",
  INFO: "bg-surface-muted text-foreground-muted border-border",
};
export const SA_STATUS_STYLE = { BLOCKED: "text-error", REVIEW: "text-warning", CLEAR: "text-primary" };
const SEVERITY_LABEL = { BLOCK: "Blocks approval", WARN: "Warning", INFO: "Information" };

export function SAStatusLine({ data }) {
  return (
    <span>
      <span className={`font-semibold ${SA_STATUS_STYLE[data.status] || ""}`}>{data.status}</span>{" "}
      ({data.counts?.BLOCK || 0} block · {data.counts?.WARN || 0} warn · {data.counts?.INFO || 0} info)
    </span>
  );
}

export default function SAChecksList({ checks, empty = "No findings." }) {
  if (!checks?.length) return <p className="text-[12px] text-foreground-muted">{empty}</p>;
  return (
    <ul className="space-y-2">
      {checks.map((c, i) => (
        <li key={`${c.code}-${c.employeeId ?? "org"}-${i}`}
            className={`rounded-[12px] border px-3 py-2 text-[12px] ${SEVERITY_STYLE[c.severity] || ""}`}>
          <span className="font-semibold">{SEVERITY_LABEL[c.severity] || c.severity}</span> · {c.employeeCode ? `${c.employeeCode} · ` : ""}
          {/* The internal check code is a tooltip reference only — never shown as text. */}
          <span title={`Reference: ${c.code}`}>{c.message}</span>
          {c.source && <span className="block text-foreground-muted">Source: {c.source}</span>}
          {c.action && <span className="block text-foreground-muted">Action: {c.action}</span>}
        </li>
      ))}
    </ul>
  );
}