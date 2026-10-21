import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { getStoredUser } from "../../api/client";
import Modal from "../../components/Modal";
import { Badge, Banner, NotAvailable, actionError, card, input, primary, subtle } from "../../components/SecurityUi";
import { isUnavailable, privacyAssurance as svc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// Privacy Assurance (ZP-PRIV-VERIFY-001): the control register, the evidence
// behind each control and the independent reviews recorded against it.
// The platform never grades itself: a control only moves on when a named,
// independent reviewer records a decision with a proof reference. Statuses
// outside the known set are shown as "Unknown" rather than echoed.
const READERS = ["super_admin", "platform_security"];
const STATUS_META = {
  NT: { label: "Not tested", className: "bg-slate-200 text-slate-700" },
  ENGINEERING_COMPLETE_AWAITING_REVIEW: { label: "Engineering complete — awaiting review", className: "bg-amber-100 text-amber-800" },
  FAIL: { label: "Fail", className: "bg-red-100 text-red-800" },
};
const UNKNOWN_STATUS = { label: "Unknown", className: "bg-slate-200 text-slate-700" };
const statusMeta = (s) => STATUS_META[s] || UNKNOWN_STATUS;
const DECISION_BADGE = { accepted: "bg-emerald-100 text-emerald-800", rejected: "bg-red-100 text-red-800" };

function VerdictPanel({ attestation }) {
  if (!attestation) return null;
  const blocked = attestation.verdict === "BLOCKED";
  return (
    <section className={`${card} space-y-2 ${blocked ? "border-red-300" : "border-amber-300"}`}>
      <div className="flex items-center gap-2">
        <ShieldAlert size={20} className={blocked ? "text-red-600" : "text-amber-600"} aria-hidden="true" />
        <h2 className="text-lg font-semibold text-foreground">Attestation verdict:</h2>
        <span className={`text-lg font-bold ${blocked ? "text-red-600" : "text-amber-600"}`}>
          {blocked ? "BLOCKED" : "NOT VERIFIED"}
        </span>
      </div>
      {(attestation.reasons || []).length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-foreground">
          {attestation.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}
      <p className="text-xs text-foreground-secondary">
        The platform never marks itself as passed or verified. Verification needs a named, independent reviewer to record
        a decision with a proof reference against every control.
      </p>
    </section>
  );
}

function ReviewDialog({ control, onClose, onDone }) {
  const [decision, setDecision] = useState("accepted");
  const [proof, setProof] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const trimmed = proof.trim();
  const valid = trimmed.length >= 3 && trimmed.length <= 200;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await svc.recordReview(control.id, decision, trimmed);
      onDone(`Review recorded for ${control.id}.`);
      onClose();
    } catch (err) {
      setError(actionError(err, "The review could not be recorded."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Record review — ${control.id}`} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <p className="text-foreground">{control.title}</p>
        <fieldset className="space-y-1">
          <legend className="font-medium text-foreground">Decision</legend>
          {["accepted", "rejected"].map((d) => (
            <label key={d} className="flex items-center gap-2 text-foreground">
              <input type="radio" name="decision" value={d} checked={decision === d} onChange={() => setDecision(d)} /> {d}
            </label>
          ))}
        </fieldset>
        <label className="block space-y-1">
          <span className="font-medium text-foreground">Proof reference</span>
          <input className={input} maxLength={200} value={proof} onChange={(e) => setProof(e.target.value)}
            placeholder="Ticket, evidence file or report reference (3–200 characters)" />
        </label>
        <p className="text-xs text-foreground-secondary">
          Your name is recorded against this review. You will be asked for a fresh verification code.
        </p>
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className={subtle} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} onClick={submit} disabled={busy || !valid}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Record review
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function PrivacyAssurancePage() {
  const role = getStoredUser()?.role;
  const isSecurity = role === "platform_security";
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [section, setSection] = useState("");
  const [priority, setPriority] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(null);
  const [reviewing, setReviewing] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await svc.controls());
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load the control register.");
    }
  }, []);

  useEffect(() => {
    if (!READERS.includes(role)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, role]);

  const controls = useMemo(() => data?.controls || [], [data]);
  const sections = useMemo(() => [...new Set(controls.map((c) => c.section).filter(Boolean))].sort(), [controls]);
  const shown = controls.filter((c) => (!section || c.section === section) && (!priority || c.priority === priority) &&
    (!status || c.status === status));

  if (!READERS.includes(role) || unavailable) {
    return <div className="p-4 sm:p-6"><NotAvailable what="Privacy Assurance" /></div>;
  }

  const summary = data?.summary;
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Privacy Assurance</h1>
          <p className="text-sm text-foreground-secondary">
            The privacy control register, its evidence and independent reviews.
            {data?.generatedAt ? ` Generated ${formatDateTime(data.generatedAt)}.` : ""}
          </p>
        </div>
        <button type="button" className={subtle} onClick={load}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      {notice && <Banner tone="success">{notice}</Banner>}
      {!data ? <p className="text-sm text-foreground-secondary">Loading…</p> : (
        <>
          <VerdictPanel attestation={data.attestation} />
          {summary && (
            <div className="flex flex-wrap gap-3">
              <div className={`${card} min-w-[140px]`}>
                <p className="text-2xl font-bold leading-none text-foreground">{summary.total}</p>
                <p className="mt-1 text-xs text-foreground-secondary">Controls</p>
              </div>
              {Object.keys(STATUS_META).map((k) => (
                <div key={k} className={`${card} min-w-[140px]`}>
                  <p className="text-2xl font-bold leading-none text-foreground">{summary.byStatus?.[k] ?? 0}</p>
                  <p className="mt-1 text-xs text-foreground-secondary">{STATUS_META[k].label}</p>
                </div>
              ))}
              <div className={`${card} min-w-[140px]`}>
                <p className="text-2xl font-bold leading-none text-foreground">{summary.reviewed}</p>
                <p className="mt-1 text-xs text-foreground-secondary">With an independent review</p>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            <select className={`${input} max-w-[14rem]`} value={section} onChange={(e) => setSection(e.target.value)} aria-label="Section">
              <option value="">All sections</option>
              {sections.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className={`${input} max-w-[10rem]`} value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority">
              <option value="">Any priority</option>
              <option value="P0">P0</option>
              <option value="P1">P1</option>
            </select>
            <select className={`${input} max-w-[22rem]`} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="">Any status</option>
              {Object.entries(STATUS_META).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
            </select>
          </div>

          <div className="space-y-3">
            {shown.length === 0 && <p className="text-sm text-foreground-secondary">No controls match these filters.</p>}
            {shown.map((c) => {
              const meta = statusMeta(c.status);
              const expanded = open === c.id;
              return (
                <div key={c.id} className={`${card} space-y-3`}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <button type="button" className="text-left" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : c.id)}>
                      <p className="font-mono text-xs text-foreground-secondary">{c.id} · {c.section} · {c.priority} · owner {c.owner}</p>
                      <p className="font-medium text-foreground">{c.title}</p>
                    </button>
                    <span className="flex items-center gap-2">
                      <Badge className={meta.className}>{meta.label}</Badge>
                      <span className="text-xs text-foreground-secondary">{(c.reviews || []).length} review(s)</span>
                      {isSecurity && (
                        <button type="button" className={subtle} onClick={() => setReviewing(c)}>Record review</button>
                      )}
                    </span>
                  </div>
                  {c.deviation && <Banner tone="warning">Deviation: {c.deviation}</Banner>}
                  {expanded && (
                    <dl className="grid gap-3 text-sm sm:grid-cols-2">
                      <div>
                        <dt className="text-xs text-foreground-secondary">Automated tests</dt>
                        <dd className="font-mono text-xs text-foreground break-all">{(c.testIds || []).join(", ") || "None"}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-foreground-secondary">Evidence</dt>
                        <dd className="font-mono text-xs text-foreground break-all">{c.evidencePath || "—"}</dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-xs text-foreground-secondary">Human proofs required</dt>
                        <dd className="text-foreground">
                          {(c.humanProofs || []).length ? (
                            <ul className="list-disc pl-5">{c.humanProofs.map((p) => <li key={p}>{p}</li>)}</ul>
                          ) : "None"}
                        </dd>
                      </div>
                      <div className="sm:col-span-2">
                        <dt className="text-xs text-foreground-secondary">Independent reviews</dt>
                        <dd>
                          {(c.reviews || []).length === 0 ? (
                            <span className="text-foreground-secondary">No reviews recorded.</span>
                          ) : (
                            <ul className="divide-y divide-border-light">
                              {c.reviews.map((r) => (
                                <li key={`${r.reviewerUserId}-${r.recordedAt}`} className="flex flex-wrap items-center gap-2 py-1.5">
                                  <Badge className={DECISION_BADGE[r.decision] || "bg-slate-200 text-slate-700"}>{r.decision}</Badge>
                                  <span className="text-foreground">{r.reviewerEmail || `#${r.reviewerUserId}`}</span>
                                  <span className="text-foreground-secondary">{r.proofReference}</span>
                                  <span className="text-xs text-foreground-secondary">{formatDateTime(r.recordedAt)}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </dd>
                      </div>
                    </dl>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
      {reviewing && isSecurity && (
        <ReviewDialog control={reviewing} onClose={() => setReviewing(null)}
          onDone={(msg) => { setNotice(msg); load(); }} />
      )}
    </div>
  );
}
