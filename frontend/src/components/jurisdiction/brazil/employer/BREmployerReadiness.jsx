import { Table } from "../brShared";
import { Badge, Panel } from "./brEmployerShared";

// One legal employer's readiness on an explicit date. Each item names the
// gate(s) it feeds, with the spec §24 definition on hover. Readiness never
// signs a gate; LIVE needs every item PASS *and* every gate G1–G8 SIGNED.
export default function BREmployerReadiness({ readiness, gates }) {
  if (!readiness) return null;
  const scope = (s) => [s.cnpj && `CNPJ ${s.cnpj}`, s.establishmentId && `est #${s.establishmentId}`]
    .filter(Boolean).join(" · ");
  return (
    <Panel title={`Readiness on ${readiness.on} — ${readiness.legalName}`} testId="br-readiness"
      hint="Employer facts, establishments, RAT/FAP for the year, CPRB option, eSocial certificate, and the platform items later phases build.">
      <div className="flex flex-wrap items-center gap-2 text-[12px]" data-testid="br-live-eligibility">
        <span className="font-semibold text-foreground">LIVE:</span>
        <Badge value={readiness.liveEligible ? "PASS" : "BLOCKED"} />
        <span className="text-foreground-muted">
          {readiness.liveEligible ? "every item passes and every gate is signed" : "not eligible — Brazilian payroll stays blocked until G1–G8 are signed"}
        </span>
      </div>
      <Table rows={readiness.items} rowKey={(r) => `${r.key}-${JSON.stringify(r.scope)}`} columns={[
        { key: "section", label: "Section" }, { key: "label", label: "Item" },
        { key: "scope", label: "Scope", render: (r) => scope(r.scope) || "employer" },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        { key: "detail", label: "Detail" },
        {
          key: "gates", label: "Feeds gate", render: (r) => (
            <span className="flex flex-wrap gap-1">
              {r.gates.map((g) => (
                <abbr key={g} title={`§24 ${r.gateBasis[g]}`} className="cursor-help rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary no-underline">{g}</abbr>
              ))}
            </span>
          ),
        },
      ]} />
      {gates && (
        <div className="flex flex-wrap gap-2 text-[11px] text-foreground-muted" data-testid="br-gate-states">
          Platform gates: {gates.map((g) => <span key={g.gate}>{g.gate} {g.state}</span>)}
        </div>
      )}
    </Panel>
  );
}
