import { useState } from "react";
import { CheckCircle2, CircleAlert, XCircle } from "lucide-react";
import {
  getMxActivationReadiness, getMxReadiness, getMxSaEmployerReadinessSummary, listMxPacks,
} from "../../../service/superAdminService";
import { Messages, Table, card, useLoad } from "./mxShared";
import { ReadinessDateBar } from "./employer/employerShared";
import { localToday } from "./employer/employerUtils";
import MXPilotGrantsPanel from "./MXPilotGrantsPanel";

// Go-live gates G1–G8 (spec §22) and, per pack, every activation condition
// with its reason — the answer to "why can't I activate this pack?".
// A [PENDING G2] parameter is a warning, never a block (the engine blocks
// only the affected ZLFN employees, decision 4).
function PackReadiness({ pack }) {
  const [view, error] = useLoad(() => getMxActivationReadiness(pack.id), [pack.id]);
  return (
    <div className={card} data-testid={`mx-activation-${pack.packId}`}>
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">
        {pack.packId} v{pack.version} · {pack.status}
      </h3>
      <Messages error={error} />
      {view && (
        <>
          <p className={`mb-2 text-[12px] font-semibold ${view.activatable ? "text-success" : "text-error"}`}>
            {view.activatable ? "Every Mexico activation condition is met." : "Cannot be activated yet."}
          </p>
          <ul className="flex flex-col gap-1">
            {view.checks.map((c) => (
              <li key={c.key} className="flex items-start gap-2 text-[12px] text-foreground">
                {c.met ? <CheckCircle2 size={14} className="mt-0.5 text-success" /> : <XCircle size={14} className="mt-0.5 text-error" />}
                <span><span className="font-semibold">{c.label}:</span> {c.detail}</span>
              </li>
            ))}
            {view.warnings.map((w) => (
              <li key={w.key} className="flex items-start gap-2 text-[12px] text-warning">
                <CircleAlert size={14} className="mt-0.5" /><span><span className="font-semibold">Warning:</span> {w.detail}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-foreground-muted">{view.note}</p>
        </>
      )}
    </div>
  );
}

// Phase 3: per gate, how many employers have every item feeding it passing,
// and each employer's first blocking item — on an explicit date.
function EmployerSummary() {
  const [on, setOn] = useState(localToday);
  const [summary, error] = useLoad(() => getMxSaEmployerReadinessSummary(on), [on]);
  return (
    <div className={card} data-testid="mx-employer-summary">
      <h3 className="mb-2 text-[14px] font-semibold text-foreground">Employer readiness</h3>
      <ReadinessDateBar on={on} onChange={setOn} />
      <Messages error={error} />
      {summary && (
        <>
          <Table rows={Object.entries(summary.perGate).map(([gate, s]) => ({ gate, ...s }))} rowKey={(r) => r.gate} columns={[
            { key: "gate", label: "Gate" }, { key: "employers", label: "Employers with items" },
            { key: "allPassing", label: "All items passing" },
            { key: "definition", label: "§22 definition", render: (r) => summary.definitions[r.gate] },
          ]} />
          <Table rows={summary.employers} rowKey={(r) => r.employerId} empty="No Mexico employer is recorded yet." columns={[
            { key: "organizationId", label: "Org" }, { key: "employerId", label: "Employer" },
            { key: "liveEligible", label: "LIVE", render: (r) => (r.liveEligible ? "eligible" : "blocked") },
            { key: "first", label: "First blocking item", render: (r) => (r.firstBlockingItem ? `${r.firstBlockingItem.label} — ${r.firstBlockingItem.detail}` : "—") },
          ]} />
        </>
      )}
    </div>
  );
}

export default function MXReadinessGatesTab() {
  const [data, error] = useLoad(() => getMxReadiness(), []);
  const [packs, packsError] = useLoad(() => listMxPacks(), []);
  return (
    <div className="flex flex-col gap-4">
      <Messages error={error || packsError} />
      <EmployerSummary />
      {data && (
        <>
          <div className={card}>
            <p className="text-[12px] text-foreground-muted">{data.note}</p>
            <p className="mt-1 text-[12px] text-foreground">
              Engine {data.engineVersion} · Level: {data.level} · Gates signed: {data.signedGates}/8 · Service registry: {data.registry || "not seeded"} ·
              Onboarding flag (kill switch): {data.onboardingEnabled ? "on" : "off"} · Available: {data.available ? "Yes" : "No"}
            </p>
          </div>
          <div className={card} data-testid="mx-release-gates">
            <h3 className="mb-1 text-[14px] font-semibold text-foreground">Release gates</h3>
            <p className="mb-2 text-[12px] text-foreground-muted">
              A gate is signed only by its evidence: on the Sources tab, add a source with Form/Publication # = its evidence tag,
              upload the signed evidence pack, and a different Super Admin marks it reviewed. Checklists: {data.documents?.releaseGates}.
            </p>
            <Table rows={data.gates} rowKey={(g) => g.gate} columns={[
              { key: "gate", label: "Gate" }, { key: "label", label: "Area" },
              { key: "definition", label: "§22 definition", render: (g) => g.definition || "—" },
              { key: "evidenceTag", label: "Evidence tag", render: (g) => <span className="font-mono">{g.evidenceTag}</span> },
              { key: "state", label: "State", render: (g) => (g.artifactId ? `${g.state} (source #${g.artifactId})` : g.state) },
            ]} />
          </div>
          <MXPilotGrantsPanel level={data.level} />
          <div className={card} data-testid="mx-owner-decisions">
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Legal decisions</h3>
            <Table rows={data.decisions || []} rowKey={(d) => d.key} columns={[
              { key: "label", label: "Decision" },
              { key: "evidenceTag", label: "Evidence tag", render: (d) => <span className="font-mono">{d.evidenceTag}</span> },
              { key: "state", label: "State" },
            ]} />
          </div>
          <div className={card} data-testid="mx-retention">
            <h3 className="mb-1 text-[14px] font-semibold text-foreground">Record retention</h3>
            <p className="mb-2 text-[12px] text-foreground-muted">
              No retention period is chosen by the platform. Until one is approved for a category, nothing in it can be purged; legal holds always prevail.
            </p>
            <Table rows={data.retention || []} rowKey={(r) => r.category} columns={[
              { key: "label", label: "Records" }, { key: "state", label: "State" },
              { key: "blocker", label: "Why", render: (r) => r.blocker || "—" },
            ]} />
          </div>
          <div className={card} data-testid="mx-release-documents">
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Release documents</h3>
            <ul className="flex flex-col gap-1 text-[12px] text-foreground">
              <li>Evidence register and gate checklists: <span className="font-mono">{data.documents?.releaseGates}</span></li>
              <li>Production activation runbook: <span className="font-mono">{data.documents?.activationRunbook}</span></li>
              <li>Release checklist: <span className="font-mono">{data.documents?.releaseChecklist}</span></li>
              <li>UNKNOWN-state recovery runbook: <span className="font-mono">{data.documents?.unknownRunbook}</span></li>
            </ul>
          </div>
        </>
      )}
      {(packs || []).map((p) => <PackReadiness key={p.id} pack={p} />)}
    </div>
  );
}
