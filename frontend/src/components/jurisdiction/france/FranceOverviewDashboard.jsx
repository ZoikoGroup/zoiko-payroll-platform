import { useState } from "react";
import { ShieldCheck, CheckCircle2, XCircle, Rocket, AlertTriangle, RefreshCw } from "lucide-react";
import StatusPill from "../../StatusPill";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import {
  getFranceReadiness, listFranceDsnSubmissions, setFranceLive,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass, labelClass } from "../constants";
import { DSN_STATUS_TONE, readinessMeta } from "./franceStatutoryConfig";
import { useFranceOrgData } from "./useFranceOrgData";

// Each source loads independently (allSettled), so one failing endpoint
// shows its own error instead of blanking the whole overview.
const loadAll = (params) => Promise.allSettled([getFranceReadiness(params), listFranceDsnSubmissions(params)])
  .then(([readiness, dsn]) => ({
    readiness: readiness.status === "fulfilled" ? readiness.value : null,
    readinessError: readiness.status === "rejected" ? describeLoadError(readiness.reason) : null,
    dsn: dsn.status === "fulfilled" ? dsn.value || [] : [],
    dsnError: dsn.status === "rejected" ? describeLoadError(dsn.reason) : null,
  }));

const SECTION_LINKS = { A: "employer-profile", B: "establishments", C: "employer-profile", D: "pas-rates", E: "rate-packs" };
const SECTION_LABELS = {
  A: "A · Legal entity", B: "B · Establishments", C: "C · Urssaf / DSN", D: "D · DGFiP PAS",
  E: "E · Employer rates & effectif", H: "H · Statutory pack (G1)",
};

// France readiness (FR §11 gate H + FR-031 dry-run). The status is COMPUTED
// from the real records on every load — there is no hand-set readiness
// flag. "Mark LIVE" is available only when every check passes.
export default function FranceOverviewDashboard({ organizationId, onNavigate }) {
  const { addToast } = useToast() || {};
  const { data, error, loading, reload } = useFranceOrgData(organizationId, loadAll);
  const [goLive, setGoLive] = useState(null); // { note, saving, error }

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to view its readiness.</p>;
  }
  if (loading) return <p className="py-10 text-xs text-foreground-disabled">Loading France readiness…</p>;
  if (error) return <p className="py-10 text-xs text-foreground-muted"><AlertTriangle size={14} className="inline mr-1" />{loadErrorText(error)}</p>;

  const { readiness, readinessError, dsn, dsnError } = data;
  const checks = readiness?.checks || [];
  const sections = [...new Set(checks.map((c) => c.section))];
  const status = readiness?.readinessStatus || "NOT_READY";

  async function confirmGoLive() {
    setGoLive((g) => ({ ...g, saving: true, error: "" }));
    try {
      await setFranceLive({ evidence: goLive.note ? { note: goLive.note } : null }, { organizationId });
      addToast?.("France payroll marked LIVE.", "success");
      setGoLive(null);
      reload();
    } catch (err) {
      setGoLive((g) => ({ ...g, saving: false, error: loadErrorText(describeLoadError(err)) }));
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ShieldCheck size={16} className="text-primary" />
          <h2 className="text-sm font-bold text-foreground">France readiness (§11 gate H)</h2>
          <StatusPill
            status={status === "LIVE" ? "active" : status === "READY" ? "approved" : status === "LIVE_CHECKS_FAILING" ? "suspended" : "pending"}
            label={readinessMeta(status).label}
          />
        </div>
        <div className="flex items-center gap-2">
          <button onClick={reload} className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
            <RefreshCw size={12} /> Re-check
          </button>
          {status !== "LIVE" && (
            <button
              onClick={() => setGoLive({ note: "", saving: false, error: "" })}
              disabled={!readiness?.ready}
              title={readiness?.ready ? undefined : "Every check must pass first"}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-40"
            >
              <Rocket size={12} /> Mark LIVE
            </button>
          )}
        </div>
      </div>

      {readinessError ? (
        <p className="text-xs text-foreground-muted"><AlertTriangle size={13} className="inline mr-1" />{loadErrorText(readinessError)}</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {sections.map((section) => (
            <div key={section} className="rounded-xl border border-border bg-surface p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-bold text-foreground">{SECTION_LABELS[section] || section}</p>
                {SECTION_LINKS[section] && onNavigate && (
                  <button onClick={() => onNavigate(SECTION_LINKS[section])} className="text-[11px] font-semibold text-primary hover:underline">Open</button>
                )}
              </div>
              <ul className="space-y-1.5">
                {checks.filter((c) => c.section === section).map((c) => (
                  <li key={c.key} className="flex items-start gap-2 text-xs">
                    {c.ok ? <CheckCircle2 size={14} className="mt-px shrink-0 text-success" /> : <XCircle size={14} className="mt-px shrink-0 text-error" />}
                    <span>
                      <span className="font-medium text-foreground">{c.label}</span>
                      {!c.ok && c.detail && <span className="block text-[11px] text-foreground-muted">{c.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-2 text-xs font-bold text-foreground">Latest DSN submissions</p>
        {dsnError ? (
          <p className="text-xs text-foreground-muted">{loadErrorText(dsnError)}</p>
        ) : dsn.length === 0 ? (
          <p className="text-xs text-foreground-disabled">No DSN submission yet.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">Period</th>
                <th className="py-1 pr-3 font-semibold">Due</th>
                <th className="py-1 pr-3 font-semibold">Release</th>
                <th className="py-1 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {dsn.slice(0, 5).map((d) => (
                <tr key={d.id} className="border-t border-border">
                  <td className="py-1.5 pr-3 font-mono tabular-nums">{d.periodStart} → {d.periodEnd}</td>
                  <td className="py-1.5 pr-3 font-mono tabular-nums">{d.dueDate}</td>
                  <td className="py-1.5 pr-3">{d.releaseRef}{d.correctionOfId ? ` · corrects #${d.correctionOfId}` : ""}</td>
                  <td className="py-1.5"><StatusPill status={DSN_STATUS_TONE[d.status] || "inactive"} label={d.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {goLive && (
        <Modal title="Mark France payroll LIVE" onClose={() => setGoLive(null)}>
          <p className="text-xs text-foreground-muted">
            Every readiness check passes. Going live records the current check results as evidence (audited). Remember the
            spec&apos;s production gates G1–G8 — statutory sign-off and a two-cycle parallel run — are your evidence to attach.
          </p>
          <label className={`${labelClass} mt-3`}>Evidence note (optional)</label>
          <input className={inputClass} value={goLive.note} placeholder="e.g. G8 parallel run May/June 2026 signed off"
            onChange={(e) => setGoLive((g) => ({ ...g, note: e.target.value }))} />
          {goLive.error && <p className="mt-2 text-xs text-error">{goLive.error}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setGoLive(null)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={confirmGoLive} disabled={goLive.saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {goLive.saving ? "Saving…" : "Mark LIVE"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
