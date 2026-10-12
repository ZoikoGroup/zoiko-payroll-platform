import { useCallback, useEffect, useState } from "react";
import {
  activateHkEmpfConfiguration, approveHkRetentionPolicy, createHkEmpfConfiguration, getHkEmpfConfiguration,
  getHkMonitoring, getHkReadinessCenter, getHkRetentionPolicies, getHkSoftwareApproval, getSourceArtifacts, proposeHkRetentionPolicy,
  transitionHkSoftwareApproval,
} from "../../../service/superAdminService";

// Hong Kong platform control records (Super Admin). Every value is read from
// the server; nothing here can claim an external approval — the server
// refuses IRD approval without the IRD's reviewed letter, eMPF certification
// without reviewed evidence, and any retention period before D-2 / D-3.
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = (s) => (s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

function useLoad(fn) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const reload = useCallback(() => fn().then((d) => { setData(d); setError(null); }).catch((e) => setError(e?.message || "Could not load.")), [fn]);
  useEffect(() => {
    let live = true;
    fn().then((d) => { if (live) setData(d); }).catch((e) => { if (live) setError(e?.message || "Could not load."); });
    return () => { live = false; };
  }, [fn]);
  return [data, error, reload];
}

function Messages({ error, notice }) {
  return (
    <>
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[13px] text-success">{notice}</p>}
    </>
  );
}

// ── IRD & eMPF control center ────────────────────────────────────────────
const SW_FIELDS = {
  APPLICATION_PREPARED: [["formsCovered", "Forms covered (comma separated)"], ["specificationVersion", "IRD specification version"]],
  APPLICATION_SUBMITTED: [["applicationReference", "IRD application reference"], ["applicationSubmittedOn", "Submitted on (YYYY-MM-DD)"]],
  TEST_DATA_SUBMITTED: [["testDataSubmittedOn", "Test data submitted on (YYYY-MM-DD)"]],
  APPROVAL_RECEIVED: [["approvalReference", "IRD approval reference"], ["approvalReceivedOn", "Received on (YYYY-MM-DD)"], ["expiresOn", "Expires on (YYYY-MM-DD, optional)"]],
};

export function HKIrdEmpfControlTab() {
  const [sw, swError, reloadSw] = useLoad(getHkSoftwareApproval);
  const [empf, empfError, reloadEmpf] = useLoad(getHkEmpfConfiguration);
  const [sources, setSources] = useState([]);
  const [target, setTarget] = useState("");
  const [form, setForm] = useState({});
  const [cfg, setCfg] = useState({ submissionMethod: "EMPF_PORTAL_MANUAL", environment: "NOT_CONFIGURED", credentialStatus: "NOT_CONFIGURED", certificateStatus: "NOT_CONFIGURED" });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  useEffect(() => { getSourceArtifacts().then(setSources).catch(() => setSources([])); }, []);

  async function act(fn, ok, after) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); after(); } catch (e) { setError(e?.message || "Refused."); }
  }
  function swPayload() {
    const p = { target, reason: form.reason, notes: form.notes || undefined };
    (SW_FIELDS[target] || []).forEach(([k]) => { if (form[k]) p[k] = k === "formsCovered" ? form[k].split(",").map((x) => x.trim()).filter(Boolean) : form[k]; });
    if (target === "APPROVAL_RECEIVED") p.approvalDocumentId = form.approvalDocumentId ? Number(form.approvalDocumentId) : undefined;
    return p;
  }

  return (
    <div className="space-y-4">
      <Messages error={error || swError || empfError} notice={notice} />
      <section className={card} aria-labelledby="hk-sw">
        <h3 id="hk-sw" className="mb-1 text-[14px] font-semibold text-foreground">IRD software approval register</h3>
        {sw && (
          <>
            <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{sw.notice}</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] md:grid-cols-4">
              {[["Status", label(sw.status)], ["Forms covered", (sw.formsCovered || []).join(", ") || "—"],
                ["Specification", sw.specificationVersion || "—"], ["Application ref", sw.applicationReference || "—"],
                ["Submitted", sw.applicationSubmittedOn || "—"], ["Test data", sw.testDataSubmittedOn || "—"],
                ["Approval ref", sw.approvalReference || "—"], ["Expires", sw.expiresOn || "—"],
                ["Approval document SHA-256", sw.documentSha256 ? `${sw.documentSha256.slice(0, 16)}…` : "—"],
                ["Reviewer", sw.reviewerId ?? "—"], ["Data-file submission", sw.dataFileSubmissionPermitted ? "Permitted" : "Refused"]].map(([k, v]) => (
                <div key={k}><dt className="text-foreground-muted">{k}</dt><dd className="font-medium text-foreground">{v}</dd></div>
              ))}
            </dl>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="text-[12px] text-foreground-secondary">Record step
                <select aria-label="Software approval step" className={`${input} ml-2`} value={target} onChange={(e) => { setTarget(e.target.value); setForm({}); }}>
                  <option value="">Select…</option>
                  {sw.allowedNext.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </label>
              {(SW_FIELDS[target] || []).map(([k, l]) => (
                <input key={k} aria-label={l} placeholder={l} className={`${input} w-56`} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              ))}
              {target === "APPROVAL_RECEIVED" && (
                <select aria-label="IRD approval letter" className={`${input} max-w-xs`} value={form.approvalDocumentId || ""} onChange={(e) => setForm({ ...form, approvalDocumentId: e.target.value })}>
                  <option value="">IRD approval letter (Source Evidence, tag HK-IRD-SOFTWARE-APPROVAL)…</option>
                  {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
                </select>
              )}
              {target && <input aria-label="Software approval reason" placeholder="Reason" className={`${input} w-56`} value={form.reason || ""} onChange={(e) => setForm({ ...form, reason: e.target.value })} />}
              {target && <button type="button" className={btn} disabled={!form.reason}
                onClick={() => act(() => transitionHkSoftwareApproval(swPayload()), `Recorded: ${label(target)}.`, () => { setTarget(""); reloadSw(); })}>Record</button>}
            </div>
          </>
        )}
      </section>

      <section className={card} aria-labelledby="hk-empf">
        <h3 id="hk-empf" className="mb-1 text-[14px] font-semibold text-foreground">eMPF integration configuration</h3>
        {empf && (
          <>
            <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{empf.notice}</p>
            <table className="w-full" aria-label="eMPF configuration versions">
              <thead><tr>{["Version", "Status", "Method", "Environment", "Format", "Credentials", "Certificate", "Certification", "Maker / approver", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>
                {empf.versions.length === 0 && <tr><td className={td} colSpan={10}>Not configured — no eMPF configuration has been created.</td></tr>}
                {empf.versions.map((v) => (
                  <tr key={v.id} className="border-t border-border">
                    <td className={td}>v{v.version}</td><td className={td}>{label(v.status)}</td><td className={td}>{label(v.submissionMethod)}</td>
                    <td className={td}>{label(v.environment)}</td><td className={td}>{[v.fileFormat, v.formatVersion].filter(Boolean).join(" ") || "—"}</td>
                    <td className={td}>{label(v.credentialStatus)}</td><td className={td}>{label(v.certificateStatus)}</td>
                    <td className={td}>{label(v.certificationStatus)}</td><td className={td}>{v.createdById} / {v.approvedById ?? "—"}</td>
                    <td className={td}>{v.status === "DRAFT" && <button type="button" className={btn}
                      onClick={() => { const r = window.prompt("Activation reason"); if (r) act(() => activateHkEmpfConfiguration(v.id, r), `v${v.version} activated.`, reloadEmpf); }}>Activate</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              {[["submissionMethod", empf.methods], ["environment", empf.environments], ["credentialStatus", empf.secretStatuses], ["certificateStatus", empf.secretStatuses]].map(([k, opts]) => (
                <label key={k} className="text-[11px] text-foreground-secondary">{label(k)}
                  <select aria-label={label(k)} className={`${input} ml-1`} value={cfg[k]} onChange={(e) => setCfg({ ...cfg, [k]: e.target.value })}>
                    {opts.map((o) => <option key={o} value={o}>{label(o)}</option>)}
                  </select>
                </label>
              ))}
              {[["fileFormat", "File format"], ["formatVersion", "Format version"], ["endpointReference", "Endpoint (no credentials)"], ["reason", "Reason"]].map(([k, l]) => (
                <input key={k} aria-label={l} placeholder={l} className={`${input} w-44`} value={cfg[k] || ""} onChange={(e) => setCfg({ ...cfg, [k]: e.target.value })} />
              ))}
              <select aria-label="eMPF certification evidence" className={`${input} max-w-xs`} value={cfg.certificationEvidenceId || ""} onChange={(e) => setCfg({ ...cfg, certificationEvidenceId: e.target.value ? Number(e.target.value) : undefined })}>
                <option value="">No certification evidence (tag HK-EMPF-CERTIFICATION)</option>
                {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
              </select>
              <button type="button" className={btn} disabled={!cfg.reason}
                onClick={() => act(() => createHkEmpfConfiguration(Object.fromEntries(Object.entries(cfg).filter(([, v]) => v !== "" && v !== undefined))),
                  "Draft configuration created — a second Super Admin activates it.", reloadEmpf)}>Create draft version</button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

// ── Retention & privacy (PDPO) ───────────────────────────────────────────
export function HKRetentionTab() {
  const [data, loadError, reload] = useLoad(getHkRetentionPolicies);
  const [form, setForm] = useState({ endOfRetention: "DELETE" });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  async function act(fn, ok) {
    setError(null); setNotice(null);
    try { await fn(); setNotice(ok); reload(); } catch (e) { setError(e?.message || "Refused."); }
  }
  return (
    <div className="space-y-4">
      <Messages error={error || loadError} notice={notice} />
      {data && (
        <section className={card} aria-labelledby="hk-ret">
          <h3 id="hk-ret" className="mb-1 text-[14px] font-semibold text-foreground">Retention policy by record category</h3>
          <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
            {data.notice} Owner decisions: D-2 {label(data.decisions["D-2"])}, D-3 {label(data.decisions["D-3"])}.
          </p>
          <table className="w-full" aria-label="Retention policies">
            <thead><tr>{["Category", "State", "Period", "End of retention", "Basis", "Pending draft", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>
              {data.categories.map((c) => (
                <tr key={c.category} className="border-t border-border">
                  <td className={td}>{c.label}</td>
                  <td className={td}>{label(c.state)}{c.blocker && <div className="text-[10px] text-foreground-muted">{c.blocker}</div>}</td>
                  <td className={td}>{c.retentionYears ? `${c.retentionYears} years` : "—"}</td><td className={td}>{label(c.endOfRetention) || "—"}</td>
                  <td className={td}>{c.legalBasis || "—"}</td>
                  <td className={td}>{c.draft ? `${c.draft.retentionYears} years (maker ${c.draft.createdById})` : "—"}</td>
                  <td className={td}>{c.draft && <button type="button" className={btn} onClick={() => act(() => approveHkRetentionPolicy(c.draft.id), "Retention period approved.")}>Approve</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <select aria-label="Record category" className={input} value={form.recordCategory || ""} onChange={(e) => setForm({ ...form, recordCategory: e.target.value })}>
              <option value="">Category…</option>
              {data.categories.map((c) => <option key={c.category} value={c.category}>{c.label}</option>)}
            </select>
            <input aria-label="Retention years" placeholder="Years (from D-2)" className={`${input} w-28`} value={form.retentionYears || ""} onChange={(e) => setForm({ ...form, retentionYears: e.target.value })} />
            <select aria-label="End of retention" className={input} value={form.endOfRetention} onChange={(e) => setForm({ ...form, endOfRetention: e.target.value })}>
              <option value="DELETE">Delete</option><option value="ANONYMISE">Anonymise</option>
            </select>
            <input aria-label="Legal basis" placeholder="Legal basis" className={`${input} w-56`} value={form.legalBasis || ""} onChange={(e) => setForm({ ...form, legalBasis: e.target.value })} />
            <input aria-label="Retention reason" placeholder="Reason" className={`${input} w-44`} value={form.reason || ""} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            <button type="button" className={btn} disabled={!form.recordCategory || !form.reason}
              onClick={() => act(() => proposeHkRetentionPolicy({ ...form, retentionYears: Number(form.retentionYears) }), "Retention period proposed — a second Super Admin approves it.")}>Propose</button>
          </div>
        </section>
      )}
    </div>
  );
}

// ── Production readiness center ──────────────────────────────────────────
const TONE = { PASS: "text-success", FAIL: "text-error", BLOCKED: "text-error", PENDING: "text-warning", NOT_APPLICABLE: "text-foreground-muted" };

export function HKReadinessCenterTab() {
  const [data, error] = useLoad(getHkReadinessCenter);
  const [monitoring] = useLoad(getHkMonitoring);
  const [filter, setFilter] = useState("");
  if (error) return <p role="alert" className="text-[13px] text-error">{error}</p>;
  if (!data) return <p className="text-[13px] text-foreground-muted">Loading…</p>;
  const rows = data.items.filter((i) => !filter || i.status === filter);
  return (
    <div className="space-y-4">
      <section className={card} aria-labelledby="hk-ready">
        <h3 id="hk-ready" className="text-[14px] font-semibold text-foreground">{data.classification}</h3>
        <p className="mb-3 text-[12px] text-foreground-secondary">As of {data.asOf} · registry {data.registry || "not registered"} · re-derived from the database on every load.</p>
        <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Filter by status">
          <button type="button" className={btn} aria-pressed={!filter} onClick={() => setFilter("")}>All ({data.total})</button>
          {Object.entries(data.counts).map(([s, n]) => (
            <button key={s} type="button" className={btn} aria-pressed={filter === s} onClick={() => setFilter(s)}>{label(s)} ({n})</button>
          ))}
        </div>
        <table className="w-full" aria-label="Readiness items">
          <thead><tr>{["Category", "Item", "Status", "Owner", "Evidence", "Next action", "Due", "Blocker"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.key} className="border-t border-border">
                <td className={td}>{i.category}</td><td className={td}>{i.item}</td>
                <td className={`${td} font-semibold ${TONE[i.status] || ""}`}>{label(i.status)}</td>
                <td className={td}>{i.owner}</td><td className={td}>{i.evidence}</td><td className={td}>{i.nextAction}</td>
                <td className={td}>{i.dueDate || "not scheduled"}</td><td className={td}>{i.blockerReason || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {monitoring && (
        <section className={card} aria-labelledby="hk-mon">
          <h3 id="hk-mon" className="mb-1 text-[14px] font-semibold text-foreground">Monitoring signals — {monitoring.alerts} alert(s)</h3>
          <p className="mb-2 text-[12px] text-foreground-secondary">{monitoring.notice}</p>
          <table className="w-full" aria-label="Monitoring signals">
            <thead><tr>{["Signal", "Value", "Alert threshold", "Alert"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>
              {monitoring.signals.map((m) => (
                <tr key={m.key} className="border-t border-border">
                  <td className={td}>{m.label}</td><td className={td}>{m.value}</td>
                  <td className={td}>{m.threshold === null ? "informational" : `> ${m.threshold}`}</td>
                  <td className={`${td} font-semibold ${m.alert ? "text-error" : "text-foreground-muted"}`}>{m.alert ? "ALERT" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
