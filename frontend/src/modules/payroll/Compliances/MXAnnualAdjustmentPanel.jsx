import { useCallback, useEffect, useState } from "react";
import {
  applyMxAnnualAdjustment, approveMxAnnualAdjustment, approveMxAnnualExclusion, computeMxAnnualAdjustment,
  getMxAnnualExclusionReasons, listMxAnnualAdjustments, listMxEmployers, recordMxAnnualExclusion,
} from "../../../service/payrollService";
import { Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

const link = "text-[12px] text-primary underline disabled:opacity-40";

// Annual ISR adjustment (ZP-MX-ENG-001 §4 MX-010; Phase 9e). Per legal employer
// and ended fiscal year, from committed runs only: the transcribed rule decides
// eligibility and the annual ISR (S24); the difference is approved by a second
// person and applied in a later, open ordinary run as its own payslip section —
// the year's payslips and CFDIs are never edited.
export default function MXAnnualAdjustmentPanel() {
  const [years, setYears] = useState(null);
  const [employers, setEmployers] = useState([]);
  const [reasons, setReasons] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [runIds, setRunIds] = useState({});
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    Promise.all([listMxAnnualAdjustments(), listMxEmployers(), getMxAnnualExclusionReasons()])
      .then(([y, e, r]) => { if (active) { setYears(y); setEmployers(e || []); setReasons(r); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The annual adjustments could not be loaded."));
    return () => { active = false; };
  }, [tick]);

  const employerName = (id) => employers.find((e) => e.employerId === id)?.legalName || `#${id}`;
  const reasonCodes = (reasons?.reasons || []).map((r) => r.code);
  const yearKey = (y) => `${y.employerId}-${y.fiscalYear}`;

  return (
    <Panel title="Annual ISR adjustment" testId="mx-annual"
      hint="Computed from committed runs by the transcribed rule; applied in a later open ordinary run — the year's payslips are never edited.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      <Messages error={error} notice={notice} />
      {(years || []).map((y) => {
        const statuses = new Set(y.rows.map((r) => r.status));
        const body = { employerId: y.employerId, fiscalYear: y.fiscalYear };
        return (
          <div key={yearKey(y)} className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="mx-annual-year">
            <p className="text-[12px] text-foreground-muted">
              {y.fiscalYear} · {employerName(y.employerId)} · {[...statuses].join(", ")}
            </p>
            <Table rows={y.rows} rowKey={(r) => r.id} columns={[
              { key: "employeeId", label: "Employee" },
              { key: "annualTaxable", label: "Annual taxable" },
              { key: "withheldTotal", label: "Withheld" },
              { key: "annualIsr", label: "Annual ISR", render: (r) => r.annualIsr ?? "—" },
              { key: "difference", label: "Difference", render: (r) => r.difference ?? "—" },
              { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
              { key: "excl", label: "Excluded", render: (r) => (r.eligible ? "—" : `${r.exclusionReason || ""}${r.exclusionEvidenceRef ? ` (${r.exclusionEvidenceRef})` : ""}`) },
              { key: "applied", label: "Applied", render: (r) => (r.appliedItemId ? `payslip #${r.appliedItemId}` : r.appliedRunId ? `run #${r.appliedRunId}` : "—") },
              { key: "act", label: "", render: (r) => (
                <span className="flex flex-wrap gap-2">
                  {r.status === "COMPUTED" && !r.exclusionPending && r.eligible && reasonCodes.length > 0 && (
                    <button type="button" className={link} disabled={busy}
                      onClick={() => run(() => recordMxAnnualExclusion(r.id, { reasonCode: reasonCodes[0], evidenceRef: "Recorded from the Compliance Centre" }),
                        "Exclusion recorded — another person must approve it.")}>
                      Exclude ({reasonCodes[0]})
                    </button>
                  )}
                  {r.exclusionPending && (
                    <button type="button" className={link} disabled={busy}
                      onClick={() => run(() => approveMxAnnualExclusion(r.id), "Exclusion approved.")}>Approve exclusion (another person)</button>
                  )}
                </span>
              ) },
            ]} />
            <span className="flex flex-wrap items-center gap-3">
              {statuses.has("COMPUTED") && (
                <>
                  <button type="button" className={link} disabled={busy}
                    onClick={() => run(() => computeMxAnnualAdjustment(body), "Re-computed.")}>Re-compute</button>
                  <button type="button" className={link} disabled={busy}
                    onClick={() => run(() => approveMxAnnualAdjustment(body), "Approved.")}>Approve (another person)</button>
                </>
              )}
              {statuses.has("APPROVED") && (
                <>
                  <input aria-label="Run id" placeholder="Open ordinary run id" className="rounded border border-border px-1 text-[12px]"
                    value={runIds[yearKey(y)] || ""} onChange={(e) => setRunIds((s) => ({ ...s, [yearKey(y)]: e.target.value }))} />
                  <button type="button" className={link} disabled={busy || !runIds[yearKey(y)]}
                    onClick={() => run(() => applyMxAnnualAdjustment({ ...body, runId: Number(runIds[yearKey(y)]) }),
                      "Assigned — generate the run's payslips to apply it.")}>
                    Apply in run
                  </button>
                </>
              )}
            </span>
            {reasonCodes.length === 0 && statuses.has("COMPUTED") && (
              <p className="text-[12px] text-warning" role="status">{reasons?.block?.code}: {reasons?.block?.message}</p>
            )}
          </div>
        );
      })}
      <MiniForm
        testId="mx-new-annual" submitLabel="Compute" busy={busy}
        fields={[
          { key: "employerId", label: "Legal employer", type: "select", required: true,
            options: employers.map((e) => ({ value: String(e.employerId), label: e.legalName })) },
          { key: "fiscalYear", label: "Fiscal year (ended)", required: true },
        ]}
        onSubmit={(s) => run(() => computeMxAnnualAdjustment({ employerId: Number(s.employerId), fiscalYear: Number(s.fiscalYear) }),
          "Computed — another person approves it.")}
      />
    </Panel>
  );
}
