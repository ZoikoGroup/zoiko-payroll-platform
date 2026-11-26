import { getBeSummary } from "../../../service/superAdminService";
import Collapsible from "../Collapsible";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import BESigningStatusTab from "./BESigningStatusTab";

// Belgium pack status. Since the gate removal (owner decision 2026-11-25)
// there are no release gates, gate evidence, activation readiness or owner
// decisions: Belgium opens for onboarding like Spain once a pack is Active.
// What remains is whether onboarding is open and the pack's row status.

export default function BEReleaseReadinessTab({ pack }) {
  const [summary, error] = useLoad(getBeSummary);
  if (error) return <ErrorNote message={error} />;
  if (!summary) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return (
    <div className="space-y-3" data-testid="be-release-readiness">
      <div className={card} data-testid="be-engine-status">
        <h3 className="text-[14px] font-semibold text-foreground">Belgium — {summary.spec}</h3>
        <p className="mt-1 text-[12px] text-foreground-secondary">
          Available for onboarding: <strong>{summary.available ? "yes" : "no"}</strong>
          {summary.available ? "" : " (opens once a Belgian pack is Active)"}
        </p>
      </div>
      {pack && (
        <Collapsible title="Signing status" testId="be-section-signing"
          summary="Unsigned, empty and unsourced rows; content workbook export / import.">
          <BESigningStatusTab pack={pack} />
        </Collapsible>
      )}
    </div>
  );
}
