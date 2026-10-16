import { Table } from "../mxShared";
import { Badge, Panel } from "./employerShared";

// Panel H — one employer's readiness on an explicit date. Each item names the
// gate(s) it feeds with the spec §22 definition it is mapped by, or says
// "unmapped". Employer readiness never signs a gate; LIVE needs every item
// PASS *and* every platform gate G1–G8 SIGNED.
export default function MXEmployerReadiness({ readiness, gates }) {
  if (!readiness) return null;
  const scope = (s) => [s.registroPatronal && `reg ${s.registroPatronal}`, s.state, s.establishmentId && `est #${s.establishmentId}`]
    .filter(Boolean).join(" · ");
  return (
    <Panel letter="H" title={`Readiness on ${readiness.on}`} testId="mx-panel-h"
      hint="A single evidence gate: SAT stamp, IMSS/SUA, INFONAVIT, state ISN, bank, labour policy and parallel payroll. Items without a clear §22 gate are marked unmapped.">
      <div className="flex flex-wrap items-center gap-2 text-[12px]" data-testid="mx-live-eligibility">
        <span className="font-semibold text-foreground">LIVE:</span>
        <Badge value={readiness.liveEligible ? "PASS" : "BLOCKED"} />
        <span className="text-foreground-muted">{readiness.liveBlockedBy.join("; ")}</span>
      </div>
      <Table rows={readiness.items} rowKey={(r) => `${r.key}-${JSON.stringify(r.scope)}`} columns={[
        { key: "panel", label: "Panel" }, { key: "label", label: "Item" },
        { key: "scope", label: "Scope", render: (r) => scope(r.scope) || "employer" },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        { key: "detail", label: "Detail" },
        {
          key: "gates", label: "Feeds gate", render: (r) => (r.gates.length === 0 ? (
            <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-semibold text-foreground-muted">unmapped</span>
          ) : (
            <span className="flex flex-wrap gap-1">
              {r.gates.map((g) => (
                <abbr key={g} title={`§22 ${r.gateBasis[g]}`} className="cursor-help rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary no-underline">{g}</abbr>
              ))}
            </span>
          )),
        },
      ]} />
      {gates && (
        <div className="flex flex-wrap gap-2 text-[11px] text-foreground-muted" data-testid="mx-gate-states">
          Platform gates: {gates.map((g) => <span key={g.gate}>{g.gate} {g.state}</span>)}
        </div>
      )}
    </Panel>
  );
}
