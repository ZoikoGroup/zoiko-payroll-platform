import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, FileWarning } from "lucide-react";
import { getCompliancePolicyOverview } from "../../service/superAdminService";

// What a pack actually holds, for every country's Overview tab (the field
// grid below it shows only free-text metadata). Read-only, from
// GET /super-admin/compliance/policies/{id}/overview. Counts only: values
// awaiting sign-off are counted, never filled in.

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <p className="text-[11px] font-medium text-foreground-muted">{label}</p>
      <p className="mt-0.5 text-lg font-bold text-foreground">{value}</p>
      {hint ? <p className="text-[11px] text-foreground-muted">{hint}</p> : null}
    </div>
  );
}

function Flag({ ok, children }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
      ok ? "bg-success/10 text-success" : "bg-warning/10 text-warning"
    }`}>
      {ok ? <CheckCircle2 size={12} aria-hidden="true" /> : <CircleAlert size={12} aria-hidden="true" />}
      {children}
    </span>
  );
}

export default function PackOverviewSummary({ pack, refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!pack?.id) return undefined;
    let cancelled = false;
    getCompliancePolicyOverview(pack.id)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError(e.message || "Could not load the pack summary."); });
    return () => { cancelled = true; };
  }, [pack?.id, pack?.status, refreshKey]);

  if (error) return <p className="mb-4 text-xs text-error">{error}</p>;
  if (!data) return <p className="mb-4 text-xs text-foreground-muted">Loading pack summary…</p>;

  const { lifecycle, contributions, taxSlabs, regions, missingMetadata, registrationBlockedReason } = data;
  const pending = contributions.pendingSignOff + taxSlabs.pendingSignOff;

  return (
    <div className="mb-5 space-y-4">
      <div className="flex flex-wrap gap-2">
        <Flag ok={lifecycle.inForceToday}>
          {lifecycle.inForceToday ? "Active and in force today" : lifecycle.isActive ? "Active, outside its effective dates" : `Not active (${data.status})`}
        </Flag>
        <Flag ok={lifecycle.approved}>{lifecycle.approved ? "Approved" : "Not approved yet"}</Flag>
        <Flag ok={lifecycle.sourceDocumentAttached}>
          {lifecycle.sourceDocumentAttached ? "Source document attached" : "No source document"}
        </Flag>
        <span className="inline-flex items-center rounded-full bg-surface-muted px-2.5 py-1 text-[11px] font-semibold text-foreground-muted">
          {lifecycle.versionCount} version{lifecycle.versionCount === 1 ? "" : "s"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Employee deductions" value={contributions.employeeSide} hint="rates with an employee share" />
        <Stat label="Employer contributions" value={contributions.employerSide} hint="rates with an employer share" />
        <Stat label="Parameters & thresholds" value={contributions.parameters} hint="flat amounts, limits, values" />
        <Stat label="Tax slabs / bands" value={taxSlabs.total} hint={`${taxSlabs.byRuleType.length} rule type${taxSlabs.byRuleType.length === 1 ? "" : "s"}`} />
      </div>

      {taxSlabs.byRuleType.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead className="bg-surface-muted text-foreground-muted">
              <tr><th className="px-3 py-2 font-semibold">Tax rule</th><th className="px-3 py-2 font-semibold">Rows</th><th className="px-3 py-2 font-semibold">Regimes</th><th className="px-3 py-2 font-semibold">Regions</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {taxSlabs.byRuleType.map((g) => (
                <tr key={g.ruleType}>
                  <td className="px-3 py-2 font-medium text-foreground">{g.ruleType}</td>
                  <td className="px-3 py-2 text-foreground">{g.count}</td>
                  <td className="px-3 py-2 text-foreground-muted">{g.regimes.join(", ") || "—"}</td>
                  <td className="px-3 py-2 text-foreground-muted">{g.regions.join(", ") || "National"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
        <div>
          <p className="text-foreground-muted">Effective dates</p>
          <p className="font-medium text-foreground">
            {data.effectiveFrom || "—"} → {data.effectiveTo || "open-ended"}
            {data.taxYear ? ` · tax year ${data.taxYear}` : ""}
          </p>
        </div>
        <div>
          <p className="text-foreground-muted">Regions covered</p>
          <p className="font-medium text-foreground">{regions.length ? regions.join(", ") : "National only"}</p>
        </div>
      </div>

      {(pending > 0 || missingMetadata.length > 0 || registrationBlockedReason) && (
        <div className="space-y-1.5 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2.5 text-xs text-warning">
          <p className="flex items-center gap-1.5 font-semibold"><FileWarning size={13} aria-hidden="true" /> Needs attention</p>
          {pending > 0 && <p>{pending} value{pending === 1 ? "" : "s"} still awaiting sign-off from an authoritative source.</p>}
          {missingMetadata.length > 0 && <p>Not filled in: {missingMetadata.join(", ")}.</p>}
          {registrationBlockedReason && <p>Organisations cannot register for this country yet: {registrationBlockedReason}</p>}
        </div>
      )}
    </div>
  );
}
