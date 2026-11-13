import { useCallback, useEffect, useState } from "react";
import { getPlSigningStatus } from "../../../service/superAdminService";
import { card } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import { GROUPS } from "./plContent";
import { SeedDraftPanel } from "./PLOverviewDashboard";

// Every item that still blocks activation of this Poland pack version, grouped
// by the tab where it is edited and signed (gate G1).

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

  const byGroup = {};
  status.pendingRates.forEach((key) => { (byGroup[groupOf(key)] ||= []).push(key); });
  const pendingSlabs = Object.values(status.pendingSlabsByRuleType || {}).reduce((a, b) => a + b, 0);
  const approved = Boolean(pack.approvedById) && !status.editors.includes(pack.approvedById);
  const steps = [
    { label: "Draft pack seeded from the specification", done: true },
    { label: `Parameters signed (${status.pendingRates.length} still pending)`, done: status.pendingRates.length === 0,
      where: "the parameter tabs — Edit / sign each row" },
    { label: `Empty values filled (${status.emptyValues.length} left)`, done: status.emptyValues.length === 0,
      where: "values the specification does not give — from the signed authority source" },
    { label: `Policies decided (${status.pendingPolicies.length} still PENDING_G1)`, done: status.pendingPolicies.length === 0,
      where: "a signed value, or NOT_SUPPORTED to keep the feature blocked" },
    { label: `PIT scale rows signed (${pendingSlabs} pending)`, done: pendingSlabs === 0, where: "the PIT tab" },
    { label: "Approved by a Super Admin who made none of the edits", done: approved,
      where: "Approve in the pack header (an editor is refused)" },
    { label: "Activated", done: pack.status === "Active",
      where: status.activationRefusal ? "refused until the steps above are done" : "Activate in the pack header" },
  ];

  return (
    <div className="space-y-4" data-testid="pl-signing-status">
      <div className={card} data-testid="pl-activation-checklist">
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Activation checklist (gate G1)</h3>
        <ol className="space-y-1.5">
          {steps.map((step, index) => (
            <li key={step.label} className="flex items-start gap-2 text-[12px]">
              <span className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                step.done ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>{step.done ? "✓" : index + 1}</span>
              <span className="text-foreground">
                {step.label}
                {!step.done && step.where && <span className="block text-foreground-muted">Where: {step.where}</span>}
              </span>
            </li>
          ))}
        </ol>
        {status.activationRefusal && (
          <p className="mt-3 rounded-lg border border-warning/30 bg-warning/5 p-2 text-[12px] text-warning">{status.activationRefusal}</p>
        )}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Pending by tab</h3>
        {Object.keys(byGroup).length === 0
          ? <p className="text-[12px] text-success">Every parameter is signed.</p>
          : Object.entries(byGroup).map(([group, keys]) => (
            <p key={group} className="mb-1 text-[12px] text-foreground">
              <strong>{group}:</strong> <span className="font-mono text-[11px] text-foreground-muted">{keys.join(", ")}</span>
            </p>
          ))}
        {status.notSupported.length > 0 && (
          <p className="mt-2 text-[12px] text-foreground-muted">
            Signed NOT_SUPPORTED (stays blocked): <span className="font-mono text-[11px]">{status.notSupported.join(", ")}</span>
          </p>
        )}
        <p className="mt-2 text-[12px] text-foreground-muted">
          Earning classes still REVIEW: {status.reviewClasses} (each blocks only when its amount is non-zero).
        </p>
        {status.editors.length > 0 && (
          <p className="mt-2 text-[12px] text-foreground-muted">Editors of this version (refused as approver): {status.editors.join(", ")}</p>
        )}
      </div>
    </div>
  );
}
