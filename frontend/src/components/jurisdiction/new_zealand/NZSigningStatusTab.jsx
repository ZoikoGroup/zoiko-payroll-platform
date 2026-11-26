import { useCallback, useEffect, useState } from "react";
import { getNzSigningStatus } from "../../../service/superAdminService";
import { card } from "../japan/jpFormat";
import { GROUPS } from "./nzContent";
import { ErrorNote } from "./nzShared";

// Missing content for this New Zealand pack version. There is no signing step
// since the gate removal (owner decision 2026-11-25): a saved value is in
// force, and a value or authority table not yet provided blocks only the
// calculation that needs it.

const groupOf = (key) => Object.entries(GROUPS).find(([, g]) => g.keys.includes(key))?.[1]?.title || "Other";

export default function NZSigningStatusTab({ pack }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    if (!pack) return;
    getNzSigningStatus(pack.id).then(setStatus).catch((e) => setError(e.message || "Could not load."));
  }, [pack]);
  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorNote message={error} />;
  if (!status) return <p className="text-[12px] text-foreground-muted">Loading…</p>;

  const byGroup = {};
  status.emptyValues.forEach((key) => { (byGroup[groupOf(key)] ||= []).push(key); });
  const emptyTables = status.authorityTables.filter((t) => !t.rows && !t.employerContent);
  const steps = [
    { label: "Pack seeded from the specification", done: true },
    { label: "Approved by a Super Admin other than its last editor", done: Boolean(pack.approvedById),
      where: "Approve in the pack header" },
    { label: "Activated", done: pack.status === "Active",
      where: status.activationRefusal || "Activate in the pack header" },
  ];

  return (
    <div className="space-y-4" data-testid="nz-signing-status">
      <div className={card} data-testid="nz-activation-checklist">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Go-live checklist</h3>
        <ol className="space-y-1.5">
          {steps.map((step, index) => (
            <li key={step.label} className="flex items-start gap-2 text-[12px]">
              <span className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                step.done ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>{step.done ? "✓" : index + 1}</span>
              <span className="text-foreground">
                {step.label}
                {!step.done && step.where && <span className="block text-foreground-muted">{step.where}</span>}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className={card} data-testid="nz-missing-content">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Missing values ({status.emptyValues.length})</h3>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Each item blocks only the calculation that needs it, with a named reason. Fill it in its tab.
        </p>
        {status.emptyValues.length === 0 ? (
          <p className="text-[12px] text-success">Every value is provided.</p>
        ) : (
          Object.entries(byGroup).map(([group, keys]) => (
            <div key={group} className="mb-2">
              <p className="text-[12px] font-semibold text-foreground">{group}</p>
              <ul className="mt-1 flex flex-wrap gap-1">
                {keys.map((key) => (
                  <li key={key} className="rounded border border-error/40 bg-error/5 px-1.5 py-0.5 font-mono text-[10px] text-error"
                    title="No value yet">{key}</li>
                ))}
              </ul>
            </div>
          ))
        )}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Empty authority tables ({emptyTables.length})</h3>
        {emptyTables.length === 0 ? (
          <p className="text-[12px] text-success">Every required authority table has rows.</p>
        ) : (
          <ul className="space-y-1 text-[12px]">
            {emptyTables.map((t) => (
              <li key={t.ruleType}>{t.table.replaceAll("_", " ")}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
