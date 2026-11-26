import { useCallback, useEffect, useState } from "react";
import { getPlSigningStatus } from "../../../service/superAdminService";
import { card } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import { GROUPS } from "./plContent";
import { SeedDraftPanel } from "./PLOverviewDashboard";

// Missing content for this Poland pack version. There is no signing step since
// the gate removal (owner decision 2026-11-25): a saved value is in force, and
// a value not yet provided blocks only the calculation that needs it.

const groupOf = (key) => Object.values(GROUPS).find((g) => g.keys.includes(key))?.title || "Other";

export default function PLSigningStatusTab({ pack }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    if (!pack) return;
    getPlSigningStatus(pack.id).then(setStatus).catch((e) => setError(e.message || "Could not load."));
  }, [pack]);
  useEffect(() => { load(); }, [load]);

  // With no Poland pack the layout has nothing to select: the governed
  // "create the Draft from the specification" action lives here.
  if (!pack) return <SeedDraftPanel />;
  if (error) return <ErrorNote message={error} />;
  if (!status) return <p className="text-[12px] text-foreground-muted">Loading…</p>;

  const missing = [...status.emptyValues, ...status.pendingPolicies];
  const byGroup = {};
  missing.forEach((key) => { (byGroup[groupOf(key)] ||= []).push(key); });
  const steps = [
    { label: "Pack seeded from the specification", done: true },
    { label: "Approved by a Super Admin other than its last editor", done: Boolean(pack.approvedById),
      where: "Approve in the pack header" },
    { label: "Activated", done: pack.status === "Active",
      where: status.activationRefusal || "Activate in the pack header" },
  ];

  return (
    <div className="space-y-4" data-testid="pl-signing-status">
      <div className={card} data-testid="pl-activation-checklist">
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
      <div className={card} data-testid="pl-missing-content">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Missing content</h3>
        <p className="mb-2 text-[12px] text-foreground-muted">
          Each item blocks only the calculation that needs it, with a named reason. Fill it in its tab.
        </p>
        {Object.keys(byGroup).length === 0
          ? <p className="text-[12px] text-success">Every value is provided.</p>
          : Object.entries(byGroup).map(([group, keys]) => (
            <p key={group} className="mb-1 text-[12px] text-foreground">
              <strong>{group}:</strong> <span className="font-mono text-[11px] text-foreground-muted">{keys.join(", ")}</span>
            </p>
          ))}
        {status.notSupported.length > 0 && (
          <p className="mt-2 text-[12px] text-foreground-muted">
            Set NOT_SUPPORTED (feature stays blocked): <span className="font-mono text-[11px]">{status.notSupported.join(", ")}</span>
          </p>
        )}
        <p className="mt-2 text-[12px] text-foreground-muted">
          Earning classes still REVIEW: {status.reviewClasses} (each blocks only when its amount is non-zero).
        </p>
      </div>
    </div>
  );
}
