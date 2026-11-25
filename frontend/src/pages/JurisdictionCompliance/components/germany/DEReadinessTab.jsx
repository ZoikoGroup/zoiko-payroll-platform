import Collapsible from "../../../../components/jurisdiction/Collapsible";
import { useLoad } from "../../../../components/jurisdiction/japan/jpFormat";
import { getPapReleaseGateStatus, listPapReleases } from "../../../../service/superAdminService";
import { SourceEvidenceTab } from "../../GermanyStatutoryRegistriesPage";
import { CompletenessPanel } from "./GermanyCompliancePackSection";
import { DEWageTaxWarning } from "./DETaxSlabsTab";

// Germany Readiness tab: the wage-tax warning, the pack's registry-linkage
// completeness (assess_germany_pack_completeness), the PAP release gate status
// (read-only; the releases are managed in Tax Slabs) and the source evidence.

const loadGates = () => listPapReleases().then((releases) => Promise.all((releases || []).map((r) =>
  getPapReleaseGateStatus(r.id).then((gate) => ({ release: r, gate })).catch((e) => ({ release: r, error: e?.message || "Could not load." })))));

function PapGateStatus() {
  const [rows, error] = useLoad(loadGates);
  if (error) return <p className="text-xs text-error">{error}</p>;
  if (!rows) return <p className="text-xs text-foreground-muted">Loading…</p>;
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border-light px-3 py-6 text-center text-xs text-foreground-disabled" data-testid="de-pap-gates-empty">
        No PAP release record exists, so there are no release gates to assess. Releases are managed in the Tax Slabs tab.
      </p>
    );
  }
  return (
    <div className="space-y-2" data-testid="de-pap-gates">
      {rows.map(({ release, gate, error: gateError }) => (
        <div key={release.id} className="rounded-lg border border-border p-3 text-xs">
          <p className="font-semibold text-foreground">Release #{release.id} · {release.status}</p>
          {gateError && <p className="text-error">{gateError}</p>}
          {gate && (
            <>
              <ul className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(gate.gates || {}).map(([name, ok]) => (
                  <li key={name} className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${ok
                    ? "border-success/30 bg-success/5 text-success" : "border-error/30 bg-error/5 text-error"}`}>{name}</li>
                ))}
              </ul>
              <p className="mt-1.5 text-foreground-muted">
                {gate.isActivationEligible ? "Every gate is satisfied." : `Failed gates: ${(gate.failedGates || []).join(", ") || "—"}.`}
              </p>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

export default function DEReadinessTab({ pack }) {
  return (
    <div className="space-y-3" data-testid="de-readiness">
      <DEWageTaxWarning testId="de-readiness-warning" />
      <Collapsible title="Pack completeness" testId="de-readiness-completeness" defaultOpen
        summary="Published registry rows linked to this pack, per component (COMPLETE / PARTIAL / INVALID).">
        <CompletenessPanel key={pack.id} packId={pack.id} />
      </Collapsible>
      <Collapsible title="PAP release gates" testId="de-readiness-pap" defaultOpen
        summary="The 8 production-release gate dimensions of each PAP release (read-only).">
        <PapGateStatus />
      </Collapsible>
      <Collapsible title="Source evidence" testId="de-readiness-sources"
        summary="Source artifacts backing the German registries and their review status.">
        <SourceEvidenceTab />
      </Collapsible>
    </div>
  );
}
