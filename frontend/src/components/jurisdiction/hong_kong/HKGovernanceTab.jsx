import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import {
  compareHongKongReportTemplates, getHongKongStatutorySummary, transitionHongKongServiceRegistry,
} from "../../../service/superAdminService";
import { hkLabel } from "./hkLabels";

// Hong Kong activation & governance (final jurisdiction completion program).
// Everything shown is computed server-side (GET statutory-summary →
// activationReadiness / templateCoverage); the registry step is re-checked by
// the server, so the disabled button is a convenience, never the control.
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const STATE_LABEL = { ACTIVE: "Active", DRAFT: "Draft only", MISSING: "No template" };
const DECISION_LABEL = { OPEN: "Open", SUBMITTED: "Submitted (awaiting independent review)", RECORDED: "Recorded" };
// Display only: "HK_EMPF_REMITTANCE" → "EMPF REMITTANCE", "PER_EMPLOYEE" → "PER EMPLOYEE".
const human = (v) => String(v ?? "—").replace(/^HK_/, "").replace(/_/g, " ");

export default function HKGovernanceTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [reason, setReason] = useState("");
  const [cmp, setCmp] = useState({ from: "", to: "" });
  const [diff, setDiff] = useState(null);

  const load = useCallback(() => getHongKongStatutorySummary().then(setData).catch((e) => setError(e?.message || "Could not load.")), []);
  useEffect(() => { load(); }, [load]);

  async function registry(target) {
    setError(null); setNotice(null);
    try {
      const row = await transitionHongKongServiceRegistry(target, reason);
      setNotice(`Hong Kong registry is now ${row.availability}.`);
      setReason("");
      load();
    } catch (e) {
      setError(e?.message || "The registry change was refused.");
    }
  }

  async function compare() {
    setError(null); setDiff(null);
    try { setDiff(await compareHongKongReportTemplates(cmp.from, cmp.to)); } catch (e) { setError(e?.message || "Compare failed."); }
  }

  if (!data) return error ? <p role="alert" className="text-[13px] text-error">{error}</p>
    : <p className="text-[13px] text-foreground-muted">Loading Hong Kong governance…</p>;
  const ready = data.activationReadiness;
  const templates = data.templateCoverage.flatMap((c) => c.versions.map((v) => ({ ...v, reportType: c.reportType, yearKey: c.yearKey })));

  return (
    <div className="space-y-4">
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[13px] text-success">{notice}</p>}

      <section className={card} aria-labelledby="hk-activation">
        <h3 id="hk-activation" className="mb-1 text-[14px] font-semibold text-foreground">Activation readiness</h3>
        <p className="mb-2 text-[12px] text-foreground-secondary">
          Registry: <strong>{ready.registry || "missing"}</strong> · {ready.met} / {ready.total} requirements met (as of {ready.asOf}).
          Opening onboarding (AVAILABLE) is refused by the server unless every requirement is met; suspension (PLANNED) is always allowed.
        </p>
        <ul aria-label="Activation requirements" className="space-y-1">
          {ready.requirements.map((r) => (
            <li key={r.key} className="flex items-start gap-2 text-[12px]">
              {r.met ? <CheckCircle2 size={14} className="text-success" aria-label="met" />
                : <AlertTriangle size={14} className="text-warning" aria-label="not met" />}
              <span>{r.label} — <span className="text-foreground-muted">{hkLabel(r.detail)}</span></span>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-[12px] text-foreground-secondary">Reason (the change record)
            <input aria-label="Registry change reason" className={`${input} ml-2 w-80`} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className={btn} disabled={!ready.canOpen || !reason} onClick={() => registry("AVAILABLE")}>
            Open onboarding (AVAILABLE)
          </button>
          <button type="button" className={btn} disabled={ready.registry !== "AVAILABLE" || !reason} onClick={() => registry("PLANNED")}>
            Suspend (PLANNED)
          </button>
        </div>
      </section>

      <section className={card} aria-labelledby="hk-coverage">
        <h3 id="hk-coverage" className="mb-2 text-[14px] font-semibold text-foreground">Report template coverage (exact year — no fallback)</h3>
        <table className="w-full">
          <thead><tr><th className={th}>Report type</th><th className={th}>Year basis</th><th className={th}>Period</th><th className={th}>Year</th><th className={th}>State</th><th className={th}>Versions</th></tr></thead>
          <tbody>
            {data.templateCoverage.map((c) => (
              <tr key={`${c.reportType}-${c.period}`} className="border-t border-border">
                <td className={td}>{human(c.reportType)}</td>
                <td className={td}>{c.yearKind === "YA" ? "Year of assessment" : "Calendar year"}</td>
                <td className={td}>{c.period === "current" ? "Current" : "Next"}</td>
                <td className={td}>{c.yearKey}</td>
                <td className={td}>{STATE_LABEL[c.state]}</td>
                <td className={td}>{c.versions.map((v) => `v${v.version} ${v.status}${v.sourceDocumentId ? "" : " (no source)"} · ${v.contentHash.slice(0, 10)}`).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={card} aria-labelledby="hk-decisions">
        <h3 id="hk-decisions" className="mb-1 text-[14px] font-semibold text-foreground">Owner decisions</h3>
        <p className="mb-2 text-[12px] text-foreground-secondary">
          A decision is recorded only when its document (tag shown) is uploaded under Source Evidence and reviewed by a different Super Admin.
        </p>
        <table className="w-full" aria-label="Owner decisions">
          <thead><tr><th className={th}>Decision</th><th className={th}>Subject</th><th className={th}>Blocks launch</th><th className={th}>State</th><th className={th}>Evidence tag</th></tr></thead>
          <tbody>
            {data.ownerDecisions.map((d) => (
              <tr key={d.key} className="border-t border-border">
                <td className={td}>{d.key}</td><td className={td}>{d.label}</td><td className={td}>{d.blocksLaunch ? "Yes" : "No"}</td>
                <td className={td}>{DECISION_LABEL[d.state]}</td><td className={td}><code>{d.evidenceTag}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={card} aria-labelledby="hk-deps">
        <h3 id="hk-deps" className="mb-2 text-[14px] font-semibold text-foreground">External dependencies</h3>
        <ul aria-label="External dependencies" className="space-y-1 text-[12px] text-foreground-secondary">
          {data.externalDependencies.map((d) => (
            <li key={d.key}>{d.key} — {d.label} · gate {d.gate}: {hkLabel(d.gateState)}</li>
          ))}
        </ul>
      </section>

      <section className={card} aria-labelledby="hk-compare">
        <h3 id="hk-compare" className="mb-2 text-[14px] font-semibold text-foreground">Compare template versions</h3>
        <div className="flex flex-wrap items-end gap-2">
          {["from", "to"].map((side) => (
            <label key={side} className="text-[12px] text-foreground-secondary">{side === "from" ? "From" : "To"}
              <select aria-label={`Compare ${side}`} className={`${input} ml-2`} value={cmp[side]} onChange={(e) => setCmp({ ...cmp, [side]: e.target.value })}>
                <option value="">Select…</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{human(t.reportType)} {t.yearKey} v{t.version} ({t.status})</option>)}
              </select>
            </label>
          ))}
          <button type="button" className={btn} disabled={!cmp.from || !cmp.to} onClick={compare}>Compare</button>
        </div>
        {diff && (
          <div aria-label="Template comparison" className="mt-3 space-y-1 text-[12px] text-foreground-secondary">
            <p>{diff.identical ? "The two versions have identical fields." : `${diff.added.length} added · ${diff.removed.length} removed · ${diff.changed.length} changed field(s)`}</p>
            {diff.added.length > 0 && <p><strong>Added:</strong> {diff.added.map(human).join(", ")}</p>}
            {diff.removed.length > 0 && <p><strong>Removed:</strong> {diff.removed.map(human).join(", ")}</p>}
            {diff.changed.map((c) => (
              <p key={c.field}><strong>{human(c.field)}:</strong> {Object.entries(c.changes).map(([k, v]) => `${human(k)} ${human(v.from)} → ${human(v.to)}`).join("; ")}</p>
            ))}
            {Object.keys(diff.metadata).length > 0 && (
              <p><strong>Metadata:</strong> {Object.entries(diff.metadata).map(([k, v]) => `${human(k)}: ${human(v.from)} → ${human(v.to)}`).join("; ")}</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
