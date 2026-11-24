import { getBeSummary, listBeGateEvidence } from "../../../service/superAdminService";
import Collapsible from "../Collapsible";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import BEActivationReadinessTab from "./BEActivationReadinessTab";
import { GateEvidence } from "./BEGateEvidencePanel";
import { GoldenCertification } from "./BEOverviewDashboard";
import BEOwnerDecisionsTab from "./BEOwnerDecisionsTab";
import BESigningStatusTab from "./BESigningStatusTab";
import { engineStatusLabel, gateCounts } from "./beShared";

// Belgium release readiness (ZP-BE-ENG-001 §14): everything that decides
// whether Belgium may go live, in one tab. The engine status and release gates
// G1–G7 come from the backend exactly as it derives them from evidence
// (belgium_readiness); each gate is a card whose failing checks are listed when
// opened, with that gate's evidence underneath. Golden certification,
// activation readiness, signing status and owner decisions follow as their own
// sections. No "ready" is ever shown while a gate is NOT MET.

function GateBadge({ met }) {
  return met ? (
    <span className="rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-[11px] font-semibold text-success">Met</span>
  ) : (
    <span className="rounded-full border border-error/30 bg-error/10 px-2 py-0.5 text-[11px] font-semibold text-error">Not met</span>
  );
}

function checkSummary(checks) {
  if (!checks.length) return "No checks reported.";
  const passing = checks.filter((c) => c.ok).length;
  if (passing === checks.length) return `All ${checks.length} checks pass.`;
  const open = checks.length - passing;
  return `${passing} of ${checks.length} checks pass · ${open} item${open === 1 ? "" : "s"} outstanding.`;
}

function GateCard({ gate, met, detail, evidence, onChange }) {
  const checks = detail?.checks || [];
  const failing = checks.filter((c) => !c.ok);
  const passing = checks.filter((c) => c.ok);
  return (
    <Collapsible
      testId={`be-gate-${gate}`}
      title={detail?.label ? `${gate} — ${detail.label}` : gate}
      badge={<GateBadge met={met} />}
      summary={checkSummary(checks)}
    >
      <div className="space-y-3 text-[12px]">
        {failing.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-foreground">Outstanding</p>
            <ul className="list-disc space-y-1 pl-5 text-foreground-secondary" data-testid="be-gate-details">
              {failing.map((c, i) => <li key={`f${i}`} className="break-words">{c.detail}</li>)}
            </ul>
          </div>
        )}
        {passing.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-foreground">Passing</p>
            <ul className="list-disc space-y-1 pl-5 text-success">
              {passing.map((c, i) => <li key={`p${i}`} className="break-words">{c.detail}</li>)}
            </ul>
          </div>
        )}
        {evidence && <GateEvidence gate={gate} block={evidence} onChange={onChange} />}
      </div>
    </Collapsible>
  );
}

export default function BEReleaseReadinessTab({ pack }) {
  const [summary, error, , reload] = useLoad(getBeSummary);
  const [evidence, evidenceError, , reloadEvidence] = useLoad(listBeGateEvidence);
  if (error) return <ErrorNote message={error} />;
  if (!summary) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  const { met, total } = gateCounts(summary);
  const certified = total > 0 && met === total;
  const onEvidenceChange = () => { reloadEvidence(); reload(); };
  return (
    <div className="space-y-3" data-testid="be-release-readiness">
      <div className={card} data-testid="be-engine-status">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-[14px] font-semibold text-foreground">Belgium engine — {summary.spec}</h3>
          <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${certified ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
            {engineStatusLabel(summary.status)}
          </span>
        </div>
        <p className="mt-1 text-[12px] text-foreground-secondary">
          {met} of {total} release gates met · available for onboarding: <strong>{summary.available ? "yes" : "no"}</strong>
        </p>
        <ul className="mt-3 flex flex-wrap gap-1.5" data-testid="be-gates">
          {Object.entries(summary.gates || {}).map(([gate, state]) => (
            <li key={gate} className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${state === "MET"
              ? "border-success/30 bg-success/5 text-success" : "border-error/30 bg-error/5 text-error"}`}>
              {gate}
            </li>
          ))}
        </ul>
      </div>

      <h3 className="pt-1 text-[13px] font-semibold text-foreground">Release gates</h3>
      <ErrorNote message={evidenceError} />
      {Object.entries(summary.gates || {}).map(([gate, state]) => (
        <GateCard key={gate} gate={gate} met={state === "MET"}
          detail={(summary.gateDetails || []).find((g) => g.gate === gate)}
          evidence={evidence?.[gate]} onChange={onEvidenceChange} />
      ))}

      {pack && (
        <>
          <h3 className="pt-1 text-[13px] font-semibold text-foreground">This pack ({pack.packId} v{pack.version})</h3>
          <Collapsible title="Golden certification (gate G1)" testId="be-section-golden"
            summary="Authority examples replayed against this pack's rows; the certification run activation requires.">
            <GoldenCertification key={`g${pack.id}`} pack={pack} />
          </Collapsible>
          <Collapsible title="Activation readiness" testId="be-section-activation"
            summary="What blocks activating this pack, row by row, and who clears each item. Read-only.">
            <BEActivationReadinessTab pack={pack} />
          </Collapsible>
          <Collapsible title="Signing status" testId="be-section-signing"
            summary="Unsigned, empty and unsourced rows; content workbook export / import; bulk signing.">
            <BESigningStatusTab pack={pack} />
          </Collapsible>
          <Collapsible title="Owner decisions" testId="be-section-decisions"
            summary="Owner and specialist decisions that block launch, and their decision records.">
            <BEOwnerDecisionsTab />
          </Collapsible>
        </>
      )}
    </div>
  );
}
