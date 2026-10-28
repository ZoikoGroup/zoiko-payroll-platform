import { useState } from "react";
import { ChevronDown, RefreshCw } from "lucide-react";
import { getZaSummary } from "../../../service/superAdminService";
import { Table } from "./zaShared";
import { card, useLoad } from "./zaFormat";

// South Africa release readiness (ZP-ZA-ENG-001 §13-§14; Phase 10). Read-only:
// every state here comes from the API. A gate is SIGNED only by evidence
// uploaded on the Sources tab (form number ZA-GATE-Gn) and marked reviewed by a
// DIFFERENT Super Admin; a decision likewise (ZA-DECISION-D-n). Nothing on this
// tab signs a gate, records a decision or opens South Africa.

const STATE_STYLE = {
  SIGNED: "border-success/40 bg-success/10 text-success",
  RECORDED: "border-success/40 bg-success/10 text-success",
  SUBMITTED: "border-info/40 bg-info/10 text-info",
  OPEN: "border-warning/40 bg-warning/10 text-warning",
};

function Badge({ state }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${STATE_STYLE[state] || STATE_STYLE.OPEN}`}>
      {state}
    </span>
  );
}

function Met({ met }) {
  return <span className={`text-[11px] font-semibold ${met ? "text-success" : "text-danger"}`}>{met ? "Met" : "Not met"}</span>;
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-surface-muted p-3">
      <p className="text-[11px] uppercase tracking-wide text-foreground-muted">{label}</p>
      <p className="mt-1 text-[20px] font-semibold text-foreground">{value}</p>
    </div>
  );
}

function GateCard({ gate, checklist }) {
  const [open, setOpen] = useState(false);
  const items = checklist?.items || [];
  return (
    <div className="rounded-lg border border-border p-3" data-testid={`za-gate-${gate.gate}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-semibold text-foreground">{gate.gate} · {gate.label}</p>
          <p className="text-[11px] text-foreground-muted">{gate.owner} · <span className="font-mono">{gate.evidenceTag}</span></p>
        </div>
        <Badge state={gate.state} />
      </div>
      <p className="mt-2 text-[12px] text-foreground-secondary">{gate.definition}</p>
      {checklist?.available && (
        <>
          <p className="mt-2 text-[11px] text-foreground-muted">
            Code checks {checklist.codeMet}/{checklist.codeTotal} met · {checklist.evidenceItems} evidence item(s)
          </p>
          <button type="button" onClick={() => setOpen((o) => !o)}
            className="mt-1 flex items-center gap-1 text-[12px] font-semibold text-primary">
            <ChevronDown size={13} className={open ? "rotate-180" : ""} /> {open ? "Hide" : "Show"} checklist
          </button>
          {open && (
            <ul className="mt-2 space-y-1">
              {items.map((item, i) => (
                <li key={`${gate.gate}-${i}`} className="text-[12px]">
                  <Met met={item.met} />
                  <span className="text-foreground"> · {item.text}</span>
                  <span className="text-foreground-muted"> — {item.kind === "code" ? item.detail : "evidence: " + item.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

export default function ZAReadinessTab() {
  const [data, error, loading, reload] = useLoad(getZaSummary, []);
  const checklists = Object.fromEntries((data?.gateChecklists?.gates || []).map((g) => [g.gate, g]));
  const unmet = (data?.gaPreconditions || []).filter((p) => !p.met);

  return (
    <div className="space-y-4" data-testid="za-readiness">
      <div className={card}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[14px] font-semibold text-foreground">Release readiness — gates G0–G7</h3>
            <p className="mt-1 text-[12px] text-foreground-muted">
              South Africa stays PLANNED until every gate is signed, every launch decision is recorded and every
              code check is met. Evidence is uploaded on the Sources tab and reviewed by a second Super Admin
              (see {data?.documents?.releaseGates || "docs/south-africa/release-gates/README.md"}).
            </p>
          </div>
          <button type="button" onClick={reload} disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12px] text-foreground-secondary hover:bg-surface-muted disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
        {error && <p className="mt-3 rounded-lg border border-danger/40 bg-danger/10 p-2 text-[12px] text-danger">{error}</p>}
        {data && (
          <>
            <div className="mt-4 grid gap-3 sm:grid-cols-4">
              <Stat label="Gates signed" value={`${data.signedGates ?? 0}/8`} />
              <Stat label="Go-live preconditions unmet" value={unmet.length} />
              <Stat label="Active employer registrations" value={data.activeEmployerRegistrations ?? 0} />
              <Stat label="Available" value={data.available ? "Yes" : "No"} />
            </div>
            {data.note && <p className="mt-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{data.note}</p>}
          </>
        )}
      </div>

      {data && (
        <div className={card}>
          <h3 className="mb-3 text-[14px] font-semibold text-foreground">Gates</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {(data.gates || []).map((g) => <GateCard key={g.gate} gate={g} checklist={checklists[g.gate]} />)}
          </div>
        </div>
      )}

      {data && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Go-live preconditions</h3>
          <Table rows={data.gaPreconditions || []} rowKey={(r) => r.key} empty="No preconditions."
            columns={[
              { label: "Precondition", render: (r) => r.label },
              { label: "State", render: (r) => <Met met={r.met} /> },
              { label: "Detail", render: (r) => r.detail },
            ]} />
        </div>
      )}

      {data && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Code checks (evaluated now)</h3>
          <Table rows={data.codeChecks || []} rowKey={(r) => r.key} empty="No code checks."
            columns={[
              { label: "Check", render: (r) => r.key.replaceAll("_", " ") },
              { label: "Gate", render: (r) => r.gates },
              { label: "State", render: (r) => (r.informational ? <span className="text-[11px] text-foreground-muted">Information</span> : <Met met={r.met} />) },
              { label: "Detail", render: (r) => r.detail },
            ]} />
        </div>
      )}

      {data && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Owner decisions</h3>
          <Table rows={data.decisions || []} rowKey={(row) => row.key} empty="No owner decisions."
            columns={[
              { label: "Decision", render: (row) => `${row.key} · ${row.label}` },
              { label: "Evidence tag", render: (row) => <span className="font-mono text-[11px]">{row.evidenceTag}</span> },
              { label: "Blocks launch", render: (row) => (row.blocksLaunch ? "Yes" : "No") },
              { label: "State", render: (row) => <Badge state={row.state} /> },
            ]} />
        </div>
      )}

      {data && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className={card} data-testid="za-no-go">
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">NO-GO conditions</h3>
            <p className="mb-2 text-[12px] text-foreground-muted">Do not activate South Africa while any of these is unresolved.</p>
            <ul className="list-disc space-y-1 pl-5 text-[12px] text-foreground">
              {(data.noGo || []).map((n) => <li key={n}>{n}</li>)}
            </ul>
          </div>
          <div className={card} data-testid="za-open-points">
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Open points for the reviewers</h3>
            <ul className="space-y-1 text-[12px]">
              {(data.openPoints || []).map((p) => (
                <li key={p.key}><span className="font-semibold text-foreground">{p.gate}</span>
                  <span className="text-foreground"> · {p.item}</span></li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Tax packs</h3>
        <Table rows={data?.packs || []} empty="No South Africa tax packs are seeded."
          columns={[
            { label: "Pack", render: (row) => row.packId },
            { label: "Version", render: (row) => row.version },
            { label: "Status", render: (row) => row.status },
            { label: "Effective from", render: (row) => row.effectiveFrom || "—" },
            { label: "Effective to", render: (row) => row.effectiveTo || "—" },
          ]} />
      </div>
    </div>
  );
}
