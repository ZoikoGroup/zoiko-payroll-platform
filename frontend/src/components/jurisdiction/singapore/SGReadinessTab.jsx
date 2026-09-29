import { useState } from "react";
import { recordSgDecision, reviewSgEvidence, supersedeSourceArtifact } from "../../../service/superAdminService";
import { ActivationReadiness, OperationsReadiness, SgStatus } from "./SGStatutorySummaryTab";
import useSgStatutorySummary from "./useSgStatutorySummary";

// Singapore activation readiness & operations (closure programme) — one view
// of everything that stands between the configured jurisdiction and
// activation: service availability, pack gates and governance evidence, the
// hotfix policy (owner decision D2), the per-organisation AIS setting and
// its states, statutory operations and the ZP-SG-ENG-001 §18 gates. No
// organisation data is shown on this platform screen.
// Rendered exactly as GET /super-admin/compliance/singapore/statutory-summary
// returns it; nothing is evaluated or defaulted here, and nothing is ever
// shown as passed without backend evidence.
const HOTFIX_POLICY_TEXT = {
  RESTRICTED: "Hotfix allowed; every gate except the approver checks applies; a distinct Super Admin's review is required and final.",
  PROHIBITED: "No Singapore hotfix activation.",
  FOLLOW_UP_REQUIRED: "Restricted, and no further Singapore activation while a hotfix awaits its review.",
};

const BASIS_TEXT = {
  runtime: "Observed now",
  internal: "Internal engineering evidence",
  owner: "Owner action",
};

// Review outcome for one UNDER_REVIEW artifact. The backend enforces every
// rule (a different Super Admin, uploaded document, notes on rejection, a
// future validity date); this only collects the inputs.
function EvidenceReview({ id, onReview }) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState("");
  const [validUntil, setValidUntil] = useState("");
  if (!open) {
    return <button type="button" onClick={() => setOpen(true)} className="ml-2 text-[11px] text-primary hover:underline">Review…</button>;
  }
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5">
      <label className="sr-only" htmlFor={`sg-ev-notes-${id}`}>Review notes</label>
      <input id={`sg-ev-notes-${id}`} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (required to reject)"
        className="rounded border border-border bg-surface px-1.5 py-0.5 text-[11px]" />
      <label className="text-[11px] text-foreground-muted" htmlFor={`sg-ev-valid-${id}`}>Valid until</label>
      <input id={`sg-ev-valid-${id}`} type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)}
        className="rounded border border-border bg-surface px-1.5 py-0.5 text-[11px]" />
      <button type="button" onClick={() => onReview(id, { outcome: "ACCEPTED", notes, validUntil })}
        className="text-[11px] font-semibold text-success hover:underline">Accept</button>
      <button type="button" onClick={() => onReview(id, { outcome: "REJECTED", notes })}
        className="text-[11px] font-semibold text-error hover:underline">Reject</button>
      <button type="button" onClick={() => setOpen(false)} className="text-[11px] text-foreground-muted hover:underline">Cancel</button>
    </span>
  );
}

function EvidenceList({ items, tag, onSupersede, onReview }) {
  if (!items || !items.length) {
    return <span className="text-foreground-muted">None recorded — add a Source Evidence artifact with form number <span className="font-mono">{tag}</span>, upload the signed document; a different Super Admin reviews it</span>;
  }
  // The newest current artifact is the natural replacement for older current ones.
  const current = items.filter((e) => !e.superseded);
  const newest = current.length ? current[current.length - 1] : null;
  return (
    <ul className="space-y-0.5">
      {items.map((e) => (
        <li key={e.id} title={e.sha256 ? `sha256 ${e.sha256}` : undefined}>
          #{e.id} {e.agency} — {e.title}
          <span className="ml-1"><SgStatus status={e.status} /></span>
          {e.selectedValue && <span className="ml-1 font-mono text-[11px]">{e.selectedValue}</span>}
          {e.validUntil && <span className="ml-1 text-[11px] text-foreground-muted">valid until {e.validUntil}</span>}
          {e.notes && <span className="block text-[11px] text-foreground-muted">Review notes: {e.notes}</span>}
          {onReview && e.status === "UNDER_REVIEW" && <EvidenceReview id={e.id} onReview={onReview} />}
          {onSupersede && !e.superseded && newest && newest.id !== e.id && (
            <button type="button" onClick={() => onSupersede(e.id, newest.id)}
              className="ml-2 text-[11px] text-primary hover:underline">Supersede with #{newest.id}</button>
          )}
        </li>
      ))}
    </ul>
  );
}

// Records the owner's choice for D1 / D2 / D3. Nothing is pre-selected: the
// value in force is shown beside it, never submitted on the owner's behalf.
function DecisionForm({ decision, onRecord }) {
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("");
  const id = `sg-dec-${decision.key}`;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5">
      <label className="sr-only" htmlFor={`${id}-opt`}>{decision.key} option</label>
      <select id={`${id}-opt`} value={selected} onChange={(e) => setSelected(e.target.value)}
        className="rounded border border-border bg-surface px-1.5 py-0.5 text-[11px]">
        <option value="">Select option…</option>
        {decision.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      <label className="sr-only" htmlFor={`${id}-reason`}>Reason</label>
      <input id={`${id}-reason`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Owner's reason"
        className="min-w-[12rem] flex-1 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px]" />
      <button type="button" disabled={!selected || !reason.trim()}
        onClick={() => onRecord({ key: decision.key, selectedValue: selected, reason })}
        className="text-[11px] font-semibold text-primary hover:underline disabled:opacity-50">Record decision</button>
    </span>
  );
}

function Section({ id, title, status, children }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby={id}>
      <div className="mb-2 flex items-center gap-2">
        <h3 id={id} className="text-sm font-bold text-foreground">{title}</h3>
        {status && <SgStatus status={status} />}
      </div>
      {children}
    </section>
  );
}

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-foreground-muted">{label}</dt>
      <dd className="text-right font-medium text-foreground">{children}</dd>
    </div>
  );
}

export default function SGReadinessTab() {
  const [reloadKey, setReloadKey] = useState(0);
  const [actionError, setActionError] = useState(null);
  const { loading, error, data } = useSgStatutorySummary(undefined, reloadKey);
  const act = async (fn, failure) => {
    setActionError(null);
    try {
      await fn();
      setReloadKey((k) => k + 1);
    } catch (e) {
      setActionError(e?.message || failure);
    }
  };
  const supersede = (id, replacementId) => act(() => supersedeSourceArtifact(id, replacementId), "The evidence could not be superseded.");
  const review = (id, outcome) => act(() => reviewSgEvidence(id, outcome), "The review could not be recorded.");
  const recordDecision = (payload) => act(() => recordSgDecision(payload), "The decision could not be recorded.");
  const sections = data?.sections || [];
  const readiness = data?.activationReadiness;
  const operations = sections.find((s) => s.key === "operations");
  const overall = sections.find((s) => s.key === "readiness");
  const availability = readiness?.serviceAvailability;
  const hotfix = readiness?.statutoryPack?.hotfixPolicy;
  const ais = readiness?.aisSubmissionModeSetting;

  if (loading) return <p className="text-sm text-foreground-muted">Loading…</p>;
  if (error) return <p className="text-sm text-error" role="alert">{error}</p>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-border bg-surface-muted/50 p-2 text-xs text-foreground-muted">{data.certification}</p>
      {actionError && <p className="text-sm text-error" role="alert">{actionError}</p>}

      <Section id="sg-rd-dashboard" title="Activation readiness dashboard">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Singapore production activation categories</caption>
            <thead className="bg-surface-muted text-foreground-muted">
              <tr>{["Category", "Status", "Basis", "Evidence"].map((h) => <th key={h} scope="col" className="px-3 py-2 font-semibold">{h}</th>)}</tr>
            </thead>
            <tbody>
              {(readiness?.readinessDashboard || []).map((r) => (
                <tr key={r.key} className={`border-t border-border ${r.key === "production_activation" ? "font-semibold" : ""}`}>
                  <td className="px-3 py-2 text-foreground">{r.label}</td>
                  <td className="px-3 py-2"><SgStatus status={r.status} /></td>
                  <td className="px-3 py-2 text-foreground-muted">{BASIS_TEXT[r.basis] || r.basis}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{r.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Section id="sg-rd-service" title="Service availability" status={availability ? undefined : "NOT_CONFIGURED"}>
          {availability ? (
            <dl className="space-y-1 text-xs">
              <Row label="Singapore availability">{availability.availability}</Row>
              <Row label="Filing">{availability.filingResponsibility || "—"}</Row>
              <Row label="Payment execution">{availability.paymentExecutionResponsibility || "—"}</Row>
              <Row label="Remittance">{availability.remittanceResponsibility || "—"}</Row>
            </dl>
          ) : <p className="text-xs text-foreground-muted">No jurisdiction service registry row for Singapore.</p>}
          <p className="mt-2 text-[11px] text-foreground-muted">Organisations cannot onboard Singapore payroll until it is AVAILABLE.</p>
        </Section>

        <Section id="sg-rd-hotfix" title="Hotfix policy (owner decision D2)">
          {hotfix ? (
            <dl className="space-y-1 text-xs">
              <Row label="Current">{hotfix.current}</Row>
              <Row label="Awaiting review">{hotfix.unreviewedHotfixes}</Row>
              <Row label="Options">{hotfix.options.join(" · ")}</Row>
            </dl>
          ) : <p className="text-xs text-foreground-muted">Not reported.</p>}
          {hotfix && <p className="mt-2 text-[11px] text-foreground-muted">{HOTFIX_POLICY_TEXT[hotfix.current] || hotfix.current}</p>}
        </Section>

        <Section id="sg-rd-ais" title="IRAS AIS submission mode">
          {ais ? (
            <dl className="space-y-1 text-xs">
              {ais.options.map((mode) => (
                <Row key={mode} label={mode}><SgStatus status={ais.optionStates[mode] || "NOT_CONFIGURED"} /></Row>
              ))}
            </dl>
          ) : <p className="text-xs text-foreground-muted">Setting not defined.</p>}
          {ais && <p className="mt-2 text-[11px] text-foreground-muted">Chosen per organisation: {ais.setting}. Which modes the product offers is owner decision D1.</p>}
        </Section>
      </div>

      {readiness && <ActivationReadiness readiness={readiness} />}
      {operations && <OperationsReadiness section={operations} />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Section id="sg-rd-decisions" title="Owner decisions D1–D3">
          <ul className="space-y-3 text-xs">
            {(readiness?.pendingDecisions || []).map((d) => (
              <li key={d.key}>
                <span className="font-semibold text-foreground">{d.key} · {d.label}</span>
                <span className="ml-1.5"><SgStatus status={d.status} /></span>
                <span className="block text-foreground-muted">
                  In force (product default): {typeof d.inForce === "string" ? d.inForce : JSON.stringify(d.inForce)} · Options: {d.options.join(" · ")}
                </span>
                {d.recordedValue && (
                  <span className="block text-foreground-secondary">
                    Recorded: <span className="font-mono">{d.recordedValue}</span> by user #{d.decisionMakerId}
                    {d.decidedAt ? ` on ${d.decidedAt.slice(0, 10)}` : ""} — {d.reason}
                    {d.reviewerId ? ` · reviewed by user #${d.reviewerId}` : ""}
                  </span>
                )}
                {d.inForceDiffers && <span className="block text-[11px] text-warning">Recorded value differs from the value in force: {d.effectIfDifferent}</span>}
                {d.blockingReason && <span className="block text-[11px] text-foreground-muted">Blocking: {d.blockingReason} · Next: {d.nextAction}</span>}
                <span className="block text-[11px] text-foreground-muted">Decision record: <EvidenceList items={d.evidenceRecorded} tag={d.evidenceTag} onSupersede={supersede} onReview={review} /></span>
                {d.status !== "DECISION_RECORDED" && <DecisionForm decision={d} onRecord={recordDecision} />}
              </li>
            ))}
          </ul>
        </Section>
        <Section id="sg-rd-external" title="External dependencies">
          <ul className="space-y-2 text-xs">
            {(readiness?.externalDependencies || []).map((d) => (
              <li key={d.key} className="flex flex-wrap items-baseline gap-2">
                <SgStatus status={d.status} />
                <span className="text-foreground">{d.label}</span>
                <span className="text-foreground-muted">({d.authority})</span>
              </li>
            ))}
          </ul>
        </Section>
      </div>

      <Section id="sg-rd-gates" title="Production gates (ZP-SG-ENG-001 §18)">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <caption className="sr-only">Singapore production gates and the evidence each requires</caption>
            <thead className="bg-surface-muted text-foreground-muted">
              <tr>{["Gate", "Requirement", "Authority", "Evidence required", "Evidence recorded", "Owner", "Status", "Next action"].map((h) => (
                <th key={h} scope="col" className="px-3 py-2 font-semibold">{h}</th>))}</tr>
            </thead>
            <tbody>
              {(readiness?.productionGates || []).map((g) => (
                <tr key={g.key} className="border-t border-border">
                  <td className="px-3 py-2 font-mono">{g.key}</td>
                  <td className="px-3 py-2 text-foreground">{g.label}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{g.authority}</td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {g.evidenceRequired}
                    {g.validationCriteria && <span className="block text-[11px] text-foreground-muted">Accepted when: {g.validationCriteria}</span>}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary"><EvidenceList items={g.evidenceRecorded} tag={g.evidenceTag} onSupersede={supersede} onReview={review} /></td>
                  <td className="px-3 py-2 text-foreground-secondary">{g.owner}</td>
                  <td className="px-3 py-2">
                    <SgStatus status={g.status} />
                    {g.expiryDate && <span className="block text-[11px] text-foreground-muted">valid until {g.expiryDate}</span>}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">
                    {g.blockingReason && <span className="block text-foreground-muted">{g.blockingReason}</span>}
                    {g.nextAction}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {overall && (
        <Section id="sg-rd-overall" title="Overall readiness" status={overall.status}>
          <ul className="space-y-1.5 text-xs">
            {overall.values.items.map((i) => (
              <li key={i.key} className="flex flex-wrap items-baseline gap-2">
                <SgStatus status={i.status} />
                <span className="font-semibold text-foreground">{i.label}</span>
                <span className="text-foreground-muted">{i.evidence}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
