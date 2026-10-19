import { useCallback, useEffect, useState } from "react";
import { approveMxVacation, getMxVacationLedger, recordMxVacation, withdrawMxVacation } from "../../../service/payrollService";
import { Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";
import { blankToNull } from "../../../components/jurisdiction/mexico/employer/employerUtils";

// Vacation (ZP-MX-ENG-001 §17, MX-051 / MX-053; Phase 9b). Per service year
// (anniversary-exact from the seniority date): the employer policy days and the
// statutory days, opening balance, days taken and the balance. A TAKEN record
// is recorded by one person and approved by another; its vacation premium is
// paid in the ordinary run whose period reaches the start date (withheld only
// once the special-pay rule is transcribed — until then that payslip blocks).
export default function MXVacationPanel({ employeeId }) {
  const [ledger, setLedger] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    getMxVacationLedger(employeeId)
      .then((d) => { if (active) { setLedger(d); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The vacation ledger could not be loaded."));
    return () => { active = false; };
  }, [employeeId, tick]);

  return (
    <Panel title="Vacation" testId="mx-vacation"
      hint="Days come from the employer's labour policy (never below the statutory table). Paid-out days are written by the termination workflow.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      {ledger && (
        <>
          <p className="text-[12px] text-foreground-muted">
            Current service year: <strong>{ledger.currentServiceYear ?? "—"}</strong>
          </p>
          <Table rows={ledger.years} rowKey={(r) => r.serviceYear} empty="No service year yet." columns={[
            { key: "serviceYear", label: "Service year" },
            { key: "policyDays", label: "Policy days" },
            { key: "statutoryDays", label: "Statutory days", render: (r) => r.statutoryDays ?? "not transcribed" },
            { key: "opening", label: "Opening" }, { key: "taken", label: "Taken" },
            { key: "paidOut", label: "Paid out" }, { key: "balance", label: "Balance" },
          ]} />
          <Table rows={ledger.records} empty="No vacation recorded." columns={[
            { key: "kind", label: "Kind" }, { key: "serviceYear", label: "Year" }, { key: "days", label: "Days" },
            { key: "dates", label: "Dates", render: (r) => (r.startDate ? `${r.startDate} – ${r.endDate}` : "—") },
            { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
            { key: "premium", label: "Premium", render: (r) => (r.premiumRunId ? `paid in run #${r.premiumRunId}` : "—") },
            { key: "act", label: "", render: (r) => (
              <span className="flex gap-2">
                {r.status === "DRAFT" && (
                  <button type="button" className="text-[12px] text-primary underline" disabled={busy}
                    onClick={() => run(() => approveMxVacation(r.id), "Approved.")}>Approve (another person)</button>
                )}
                {(r.status === "DRAFT" || r.status === "APPROVED") && (
                  <button type="button" className="text-[12px] text-foreground-muted underline" disabled={busy}
                    onClick={() => run(() => withdrawMxVacation(r.id, "Withdrawn from the employee screen"), "Withdrawn.")}>
                    Withdraw
                  </button>
                )}
              </span>
            ) },
          ]} />
        </>
      )}
      <MiniForm
        testId="mx-new-vacation" submitLabel="Record" busy={busy} error={error} notice={notice}
        initial={{ kind: "TAKEN" }}
        fields={[
          { key: "kind", label: "Kind", type: "select", options: ["TAKEN", "OPENING"], required: true },
          { key: "days", label: "Days", required: true },
          { key: "startDate", label: "From (taken)", type: "date" },
          { key: "endDate", label: "To (taken)", type: "date" },
          { key: "serviceYear", label: "Service year (blank = current)" },
          { key: "note", label: "Note (required for an opening balance)" },
        ]}
        onSubmit={(s) => run(() => recordMxVacation(employeeId, blankToNull({
          ...s, serviceYear: s.serviceYear ? Number(s.serviceYear) : null,
        })), "Recorded — another person must approve it.")}
      />
    </Panel>
  );
}
