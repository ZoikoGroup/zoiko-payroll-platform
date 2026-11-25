import { getBeSigningStatus, getBeSummary, listBeGateEvidence } from "../../../service/superAdminService";
import Collapsible from "../Collapsible";
import Notice from "../Notice";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";
import BEActivationReadinessTab from "./BEActivationReadinessTab";
import BECatalogueNotice from "./BECatalogueNotice";
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

// Who acts on a check, as the backend classifies it (belgium_readiness.check_actor):
// "code" = engineering work, "data" = content / configuration someone supplies,
// "sign-off" = a human approval or accepted evidence.
const ACTOR_LABEL = { code: "Code", data: "Data", "sign-off": "Sign-off" };
const ACTOR_TONE = {
  code: "border-info/40 bg-info/10 text-info",
  data: "border-warning/40 bg-warning/10 text-warning",
  "sign-off": "border-primary/40 bg-primary/10 text-primary",
};

function ActorBadge({ actor }) {
  if (!actor) return null;
  return (
    <span className={`mr-1.5 inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${ACTOR_TONE[actor] || "border-border"}`}
      data-testid="be-check-actor">{ACTOR_LABEL[actor] || actor}</span>
  );
}

function checkSummary(checks) {
  if (!checks.length) return "No checks reported.";
  const missing = checks.filter((c) => !c.ok);
  if (!missing.length) return `Done — all ${checks.length} checks pass.`;
  const by = {};
  for (const c of missing) by[c.actor || "other"] = (by[c.actor || "other"] || 0) + 1;
  const parts = Object.entries(by).map(([a, n]) => `${n} ${(ACTOR_LABEL[a] || a).toLowerCase()}`);
  return `${checks.length - missing.length} of ${checks.length} done · missing: ${parts.join(", ")}.`;
}

function GateCard({ gate, met, detail, evidence, onChange }) {
  const checks = detail?.checks || [];
  const failing = checks.filter((c) => !c.ok);
  const passing = checks.filter((c) => c.ok);
  // Which pack this gate is judging and why (the backend's selection: Active,
  // else in force today, else the next upcoming pack).
  const judging = checks.find((c) => typeof c.detail === "string" && c.detail.startsWith("Judging "))?.detail || null;
  return (
    <Collapsible
      testId={`be-gate-${gate}`}
      title={detail?.label ? `${gate} — ${detail.label}` : gate}
      badge={<GateBadge met={met} />}
      summary={checkSummary(checks)}
    >
      <div className="space-y-3 text-[12px]">
        {judging && (
          <p className="rounded border border-border bg-surface-muted px-2 py-1 text-foreground" data-testid="be-gate-judging">
            {judging}
          </p>
        )}
        {detail?.owner && (
          <p className="text-foreground-secondary" data-testid="be-gate-owner">
            <span className="font-semibold text-foreground">Who acts:</span> {detail.owner}
          </p>
        )}
        {failing.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-foreground">Missing</p>
            <ul className="space-y-1 text-foreground-secondary" data-testid="be-gate-details">
              {failing.map((c, i) => (
                <li key={`f${i}`} className="break-words"><ActorBadge actor={c.actor} />{c.detail}</li>
              ))}
            </ul>
          </div>
        )}
        {passing.length > 0 && (
          <div>
            <p className="mb-1 font-semibold text-foreground">Done</p>
            <ul className="space-y-1 text-success" data-testid="be-gate-done">
              {passing.map((c, i) => <li key={`p${i}`} className="break-words">✓ {c.detail}</li>)}
            </ul>
          </div>
        )}
        {evidence && <GateEvidence gate={gate} block={evidence} onChange={onChange} />}
      </div>
    </Collapsible>
  );
}

// The pack's own sections, or — for a pack holding no catalogue rows — the calm
// catalogue notice instead of per-row reports that would only say "missing".
function PackSections({ pack }) {
  const [status, error] = useLoad(() => getBeSigningStatus(pack.id));
  if (error) return <ErrorNote message={error} />;
  if (!status) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  if (status.catalogue && status.catalogue.rows === 0) return <BECatalogueNotice pack={pack} />;
  return (
    <>
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
      {(summary.readinessWarnings || []).map((w) => (
        <Notice key={w} tone="warning" title="Overlapping packs" testId="be-readiness-warning">{w}</Notice>
      ))}
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
          <PackSections key={pack.id} pack={pack} />
        </>
      )}
    </div>
  );
}
