import { RefreshCw } from "lucide-react";
import { getZaSummary } from "../../../service/superAdminService";
import { Table } from "./zaShared";
import { card, useLoad } from "./zaFormat";

const DECISION_STYLE = {
  RECORDED: "border-success/40 bg-success/10 text-success",
  SUBMITTED: "border-info/40 bg-info/10 text-info",
  OPEN: "border-warning/40 bg-warning/10 text-warning",
};

function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-surface-muted p-3">
      <p className="text-[11px] uppercase tracking-wide text-foreground-muted">{label}</p>
      <p className="mt-1 text-[20px] font-semibold text-foreground">{value}</p>
    </div>
  );
}

export default function ZAReadinessTab() {
  const [data, error, loading, reload] = useLoad(getZaSummary, []);

  return (
    <div className="space-y-4">
      <div className={card}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[14px] font-semibold text-foreground">Release readiness</h3>
            <p className="mt-1 text-[12px] text-foreground-muted">
              PLANNED. Activation gates G1-G8 are not evidenced, so live South Africa payroll remains disabled.
            </p>
          </div>
          <button
            type="button"
            onClick={reload}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12px] text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
        {error && <p className="mt-3 rounded-lg border border-danger/40 bg-danger/10 p-2 text-[12px] text-danger">{error}</p>}
        {data && (
          <>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <Stat label="Active employer registrations" value={data.activeEmployerRegistrations ?? 0} />
              <Stat label="Approved directives" value={data.approvedDirectives ?? 0} />
              <Stat label="Live ETI entries" value={data.liveEtiEntries ?? 0} />
            </div>
            <dl className="mt-4 grid gap-2 text-[12px] sm:grid-cols-2">
              <div>
                <dt className="text-foreground-muted">Specification</dt>
                <dd className="font-mono text-foreground">{data.spec || "—"}</dd>
              </div>
              <div>
                <dt className="text-foreground-muted">Available</dt>
                <dd className="font-semibold text-danger">{data.available ? "Yes" : "No"}</dd>
              </div>
            </dl>
            {data.note && <p className="mt-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{data.note}</p>}
            <p className="mt-3 text-[11px] text-foreground-muted">
              This endpoint reports counts and owner decisions only. It does not expose gate evidence, so no gate is
              shown as signed here.
            </p>
          </>
        )}
      </div>

      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Tax packs</h3>
        <Table
          rows={data?.packs || []}
          empty="No South Africa tax packs are configured."
          columns={[
            { label: "Pack", render: (row) => row.packId },
            { label: "Version", render: (row) => row.version },
            { label: "Status", render: (row) => row.status },
            { label: "Effective from", render: (row) => row.effectiveFrom || "—" },
            { label: "Effective to", render: (row) => row.effectiveTo || "—" },
          ]}
        />
      </div>

      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
        <Table
          rows={data?.decisions || []}
          empty="No owner decisions are recorded."
          rowKey={(row) => row.key}
          columns={[
            { label: "Decision", render: (row) => row.label },
            { label: "Evidence tag", render: (row) => <span className="font-mono text-[11px]">{row.evidenceTag}</span> },
            { label: "Blocks launch", render: (row) => (row.blocksLaunch ? "Yes" : "No") },
            {
              label: "State",
              render: (row) => (
                <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${DECISION_STYLE[row.state] || DECISION_STYLE.OPEN}`}>
                  {row.state}
                </span>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
