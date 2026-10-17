import { useEffect, useState } from "react";
import { getMxRunStatus } from "../../../../service/payrollService";

// Mexico run lifecycles (ZP-MX-ENG-001 MX-041): payroll, CFDI, authorities and
// bank are four separate objects — none advances another. Each badge reads
// its own field of GET /mexico/runs/{id}/status; an approval whose bound
// inputs changed since (MX-040) is shown as invalidated.
const TONE = {
  Approved: "border-success/40 text-success",
  NOT_STARTED: "border-border text-foreground-muted",
  HELD: "border-warning/50 text-warning",
};

function Badge({ label, status, detail, testId }) {
  return (
    <span data-testid={testId} title={detail || ""}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-semibold ${TONE[status] || "border-border text-foreground"}`}>
      <span className="uppercase tracking-widest text-foreground-muted">{label}</span>
      <span>{String(status || "—").replace("_", " ")}</span>
    </span>
  );
}

export default function MXRunStatusBadges({ runId, refreshKey }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    getMxRunStatus(runId)
      .then((d) => active && setData(d))
      .catch((err) => active && setError(err?.message || "Mexico run status could not be loaded."));
    return () => { active = false; };
  }, [runId, refreshKey]);

  if (error) return <p className="mb-3 text-[12px] text-error" role="alert">{error}</p>;
  if (!data) return null;
  const p = data.payroll || {};
  return (
    <div className="mb-4" data-testid="mx-run-status">
      <div className="flex flex-wrap items-center gap-2">
        <Badge testId="mx-badge-payroll" label="Payroll" status={p.status} detail={p.committedAt ? `committed ${p.committedAt}` : ""} />
        <Badge testId="mx-badge-cfdi" label="CFDI" status={data.cfdi?.status} detail={data.cfdi?.detail} />
        <Badge testId="mx-badge-authorities" label="Authorities" status={data.authorities?.status} detail={data.authorities?.detail} />
        <Badge testId="mx-badge-bank" label="Bank" status={data.bank?.status} detail={data.bank?.detail} />
      </div>
      {p.approvalInvalidated && (
        <p className="mt-2 text-[12px] text-error" role="alert" data-testid="mx-approval-invalidated">
          Approval invalidated — bound inputs changed since approval:{" "}
          {(p.drift || []).map((d) => `employee #${d.employeeId}: ${(d.changed || []).join(", ")}`).join("; ")}.
          Reset the run to Review and recalculate.
        </p>
      )}
      <p className="mt-2 text-[11px] text-foreground-muted">
        CFDI stamping arrives in Phase 7, authority filings in Phase 8 and bank settlement in Phase 10 — until then a
        Mexican run stops at Approved and every payment is held.
      </p>
    </div>
  );
}
