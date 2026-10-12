import { useCallback, useEffect, useMemo, useState } from "react";
import { Lock } from "lucide-react";
import {
  compareHkConfig, createHkConfigVersion, getHkConfigPack, getHkConfigResolution, getHkConfigVersions, getSourceArtifacts,
  updateHkConfigRow,
} from "../../../service/superAdminService";

// Hong Kong statutory configuration administration (Super Admin control
// plane). Everything is read from the governed pack rows server-side —
// nothing statutory is hard-coded here. Edits go through the governed HK
// editor (source document + reason required; Draft-family packs only; the
// approval is invalidated; audited). An Active version is never edited in
// place: "Create new version" makes a Draft copy (also the rollback path).
const card = "rounded-xl border border-border bg-surface p-4";
const th = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted";
const td = "px-2 py-1.5 text-[12px] text-foreground align-top";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const STATE = {
  CURRENT_ACTIVE: "Current active", NEXT_PUBLISHED: "Next published (not yet in force)", FUTURE_DRAFT: "Future draft",
  DRAFT: "Draft", PAST_ACTIVE: "Past (pinned by its period's payroll)", SUPERSEDED: "Superseded", RETIRED: "Retired",
};
const STATUS = { SOURCED: "Sourced", "UNVERIFIED — G1": "Unverified — G1 specialist", SOURCE_HASH_REQUIRED: "Source hash required" };
const RATE_FIELDS = [["employeeRatePct", "Employee rate (fraction, 0.05 = 5%)"], ["employerRatePct", "Employer rate (fraction)"],
  ["flatAmount", "Amount"], ["textValue", "Text / date value"]];
const SLAB_FIELDS = [["minAmount", "From"], ["maxAmount", "To"], ["ratePct", "Rate %"], ["flatAmount", "Amount / days"],
  ["taxFormula", "Value / date / treatment"]];

function EditRow({ row, sources, onSaved, onCancel }) {
  const fields = row.kind === "rate" ? RATE_FIELDS : SLAB_FIELDS;
  const [form, setForm] = useState(() => {
    const f = { reason: "", sourceDocumentId: row.source?.id ? String(row.source.id) : "", effectiveFrom: row.effectiveFrom || "", effectiveTo: row.effectiveTo || "" };
    fields.forEach(([k]) => { f[k] = row.raw[k] ?? ""; });
    return f;
  });
  const [error, setError] = useState(null);
  async function save() {
    setError(null);
    const payload = { reason: form.reason, sourceDocumentId: Number(form.sourceDocumentId) };
    if (form.specialistVerified) payload.specialistVerified = true;
    fields.forEach(([k]) => { if (String(form[k] ?? "") !== String(row.raw[k] ?? "")) payload[k] = form[k]; });
    if (form.effectiveFrom !== (row.effectiveFrom || "")) payload.effectiveFrom = form.effectiveFrom;
    if (form.effectiveTo !== (row.effectiveTo || "")) payload.effectiveTo = form.effectiveTo;
    try { onSaved(await updateHkConfigRow(row.kind, row.id, payload)); } catch (e) { setError(e?.message || "Save refused."); }
  }
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-border bg-surface-muted p-3" aria-label={`Edit ${row.key}`}>
      <div className="flex flex-wrap gap-2">
        {fields.filter(([k]) => row.raw[k] !== null && row.raw[k] !== undefined).map(([k, label]) => (
          <label key={k} className="text-[11px] text-foreground-secondary">{label}
            <input aria-label={label} className={`${input} ml-1 w-40`} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          </label>
        ))}
        <label className="text-[11px] text-foreground-secondary">Effective from
          <input type="date" className={`${input} ml-1`} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} />
        </label>
        <label className="text-[11px] text-foreground-secondary">Effective to
          <input type="date" className={`${input} ml-1`} value={form.effectiveTo} onChange={(e) => setForm({ ...form, effectiveTo: e.target.value })} />
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[11px] text-foreground-secondary">Official source document
          <select aria-label="Source document" className={`${input} ml-1 max-w-md`} value={form.sourceDocumentId} onChange={(e) => setForm({ ...form, sourceDocumentId: e.target.value })}>
            <option value="">Select…</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
          </select>
        </label>
        <label className="text-[11px] text-foreground-secondary">Change reason
          <input aria-label="Change reason" className={`${input} ml-1 w-72`} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        </label>
        {row.status !== "SOURCED" && (
          <label className="flex items-center gap-1 text-[11px] text-foreground-secondary">
            <input type="checkbox" aria-label="Confirmed by the HK specialist" checked={Boolean(form.specialistVerified)}
              onChange={(e) => setForm({ ...form, specialistVerified: e.target.checked })} />
            Confirmed by the HK specialist (G1) — the source must be a stored, hashed, independently reviewed document
          </label>
        )}
        <button type="button" className={btn} disabled={!form.reason || !form.sourceDocumentId} onClick={save}>Save change</button>
        <button type="button" className={btn} onClick={onCancel}>Cancel</button>
      </div>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
    </div>
  );
}

export default function HKStatutoryConfigurationTab() {
  const [versions, setVersions] = useState([]);
  const [packId, setPackId] = useState(null);
  const [data, setData] = useState(null);
  const [domain, setDomain] = useState("mpf");
  const [editing, setEditing] = useState(null);
  const [sources, setSources] = useState([]);
  const [why, setWhy] = useState(null);
  const [whyDate, setWhyDate] = useState(new Date().toISOString().slice(0, 10));
  const [cmpTo, setCmpTo] = useState("");
  const [diff, setDiff] = useState(null);
  const [nv, setNv] = useState({ version: "", reason: "" });
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  // Selecting a version resets the per-version views and loads its rows
  // (an event handler, not an effect, so nothing cascades).
  const selectPack = useCallback((id) => {
    setPackId(id); setData(null); setDiff(null); setEditing(null);
    if (id) getHkConfigPack(id).then(setData).catch((e) => setError(e?.message || "Could not load the pack."));
  }, []);
  const loadVersions = useCallback(() => getHkConfigVersions().then((vs) => { setVersions(vs); return vs; }), []);
  useEffect(() => {
    let live = true;
    loadVersions().then((vs) => {
      if (live) selectPack((vs.find((v) => v.versionState === "CURRENT_ACTIVE") || vs[vs.length - 1] || {}).id ?? null);
    }).catch((e) => { if (live) setError(e?.message || "Could not load versions."); });
    getSourceArtifacts().then((s) => { if (live) setSources(s); }).catch(() => {});
    return () => { live = false; };
  }, [loadVersions, selectPack]);

  const current = useMemo(() => data?.domains.find((d) => d.key === domain), [data, domain]);

  async function explain() {
    setError(null);
    try { setWhy(await getHkConfigResolution(whyDate)); } catch (e) { setError(e?.message || "Could not resolve."); }
  }
  async function compare() {
    setError(null);
    try { setDiff(await compareHkConfig(packId, cmpTo)); } catch (e) { setError(e?.message || "Compare failed."); }
  }
  async function newVersion() {
    setError(null); setNotice(null);
    try {
      const created = await createHkConfigVersion(packId, nv.version, nv.reason);
      setNotice(`Draft ${created.packId} v${created.version} created — edit it, have it approved, then activate it.`);
      setNv({ version: "", reason: "" });
      await loadVersions();
      selectPack(created.id);
    } catch (e) { setError(e?.message || "Could not create the version."); }
  }

  return (
    <div className="space-y-4">
      {error && <p role="alert" className="text-[13px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[13px] text-success">{notice}</p>}

      <section className={card} aria-labelledby="hk-cfg-versions">
        <h3 id="hk-cfg-versions" className="mb-2 text-[14px] font-semibold text-foreground">Statutory versions</h3>
        <table className="w-full" aria-label="Statutory versions">
          <thead><tr><th className={th}>Version</th><th className={th}>Year of assessment</th><th className={th}>Effective</th><th className={th}>Status</th><th className={th}>State</th><th className={th} /></tr></thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id} className={`border-t border-border ${v.id === packId ? "bg-surface-muted" : ""}`}>
                <td className={td}>{v.packId} v{v.version}</td><td className={td}>{v.yearOfAssessment}</td>
                <td className={td}>{v.effectiveFrom} → {v.effectiveTo || "open"}</td><td className={td}>{v.status}</td>
                <td className={td}>{STATE[v.versionState] || v.versionState}</td>
                <td className={td}><button type="button" className={btn} onClick={() => selectPack(v.id)} disabled={v.id === packId}>{v.id === packId ? "Viewing" : "View"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-[12px] text-foreground-secondary">Why is this version selected? Payroll date
            <input type="date" aria-label="Payroll date" className={`${input} ml-2`} value={whyDate} onChange={(e) => setWhyDate(e.target.value)} />
          </label>
          <button type="button" className={btn} onClick={explain}>Explain</button>
        </div>
        {why && (
          <div aria-label="Version resolution" className="mt-2 rounded-lg border border-border p-3 text-[12px] text-foreground-secondary">
            <p><strong>{why.payrollDate}</strong> (year of assessment {why.yearOfAssessment}): {why.pack ? `${why.pack.packId} v${why.pack.version} (${why.pack.effectiveFrom} → ${why.pack.effectiveTo})` : why.outcome}</p>
            <p className="mt-1">Rule: {why.rule}.</p>
            {why.templates[0] && <p className="mt-1">Report templates: {why.templates[0].rule}.</p>}
            <ul className="mt-1 list-disc pl-5">
              {why.templates.map((t) => (
                <li key={t.reportType}>{t.reportType.replace(/^HK_/, "").replace(/_/g, " ")} — {t.yearBasis} {t.yearKey}: {t.template ? `template v${t.template.version}` : "no Active template (generation refused)"}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {data && (
        <section className={card} aria-labelledby="hk-cfg-pack">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 id="hk-cfg-pack" className="text-[14px] font-semibold text-foreground">
              {data.pack.packId} v{data.pack.version} — {data.pack.status} · {STATE[data.pack.versionState]} · {data.total} governed values
            </h3>
            {!data.pack.editable && (
              <span className="inline-flex items-center gap-1 text-[12px] text-foreground-muted"><Lock size={13} aria-hidden="true" /> Locked — {data.pack.status} versions are never edited in place; create a new version.</span>
            )}
          </div>
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <label className="text-[12px] text-foreground-secondary">New version number
              <input aria-label="New version number" className={`${input} ml-2 w-24`} value={nv.version} onChange={(e) => setNv({ ...nv, version: e.target.value })} />
            </label>
            <label className="text-[12px] text-foreground-secondary">Reason (change or rollback)
              <input aria-label="New version reason" className={`${input} ml-2 w-72`} value={nv.reason} onChange={(e) => setNv({ ...nv, reason: e.target.value })} />
            </label>
            <button type="button" className={btn} disabled={!nv.version || !nv.reason} onClick={newVersion}>Create new version (Draft)</button>
            <label className="ml-4 text-[12px] text-foreground-secondary">Compare with
              <select aria-label="Compare with version" className={`${input} ml-2`} value={cmpTo} onChange={(e) => setCmpTo(e.target.value)}>
                <option value="">Select…</option>
                {versions.filter((v) => v.id !== packId).map((v) => <option key={v.id} value={v.id}>{v.packId} v{v.version}</option>)}
              </select>
            </label>
            <button type="button" className={btn} disabled={!cmpTo} onClick={compare}>Compare</button>
          </div>
          {diff && (
            <div aria-label="Version comparison" className="mb-3 rounded-lg border border-border p-3 text-[12px] text-foreground-secondary">
              <p className="font-semibold text-foreground">{diff.from.packId} v{diff.from.version} → {diff.to.packId} v{diff.to.version}: {diff.changed.length} changed · {diff.added.length} added · {diff.removed.length} removed · {diff.unchanged} unchanged</p>
              <table className="mt-2 w-full">
                <thead><tr><th className={th}>Domain</th><th className={th}>Item</th><th className={th}>Previous</th><th className={th}>New</th></tr></thead>
                <tbody>
                  {diff.changed.map((c) => Object.entries(c.changes).map(([field, v]) => (
                    <tr key={`${c.key}-${c.label}-${field}`} className="border-t border-border">
                      <td className={td}>{c.domain}</td><td className={td}>{c.label}{field !== "value" ? ` (${field})` : ""}</td>
                      <td className={td}>{String(v.from ?? "—")}</td><td className={td}>{String(v.to ?? "—")}</td>
                    </tr>
                  )))}
                  {diff.added.map((r) => <tr key={`a-${r.key}-${r.label}`} className="border-t border-border"><td className={td}>{r.domain}</td><td className={td}>{r.label}</td><td className={td}>—</td><td className={td}>{r.value} (added)</td></tr>)}
                  {diff.removed.map((r) => <tr key={`r-${r.key}-${r.label}`} className="border-t border-border"><td className={td}>{r.domain}</td><td className={td}>{r.label}</td><td className={td}>{r.value}</td><td className={td}>— (removed)</td></tr>)}
                </tbody>
              </table>
            </div>
          )}
          <div role="tablist" aria-label="Statutory domains" className="mb-3 flex flex-wrap gap-1">
            {data.domains.map((d) => (
              <button key={d.key} role="tab" aria-selected={d.key === domain} type="button" onClick={() => { setDomain(d.key); setEditing(null); }}
                className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold ${d.key === domain ? "bg-primary text-white" : "border border-border text-foreground"}`}>
                {d.label} ({d.count})
              </button>
            ))}
          </div>
          {current && (
            <div>
              {current.notice && <p className="mb-2 rounded-lg bg-surface-muted p-2 text-[12px] font-semibold text-foreground">{current.notice}</p>}
              <p className="mb-2 text-[11px] text-foreground-muted">Consumer: <code>{current.consumer}</code> · {current.unverified} value(s) not yet statutorily verified.</p>
              <table className="w-full" aria-label={`${current.label} configuration`}>
                <thead><tr><th className={th}>Item</th><th className={th}>Value</th><th className={th}>Unit</th><th className={th}>Effective</th><th className={th}>Source</th><th className={th}>Status</th><th className={th} /></tr></thead>
                <tbody>
                  {current.rows.map((r) => (
                    <tr key={`${r.kind}-${r.id}`} className="border-t border-border">
                      <td className={td}>{r.label}<div className="text-[10px] text-foreground-muted">{r.key}</div></td>
                      <td className={td}>{r.value}</td><td className={td}>{r.unit}</td>
                      <td className={td}>{r.effectiveFrom} → {r.effectiveTo}</td>
                      <td className={td}>{r.source ? <>{r.source.agency}<div className="text-[10px] text-foreground-muted">{r.source.sha256 ? `sha256 ${r.source.sha256.slice(0, 12)}…` : "no hash"}{r.source.reviewed ? " · reviewed" : ""}</div></> : "—"}</td>
                      <td className={td}>{STATUS[r.status] || r.status}</td>
                      <td className={td}>
                        {r.editable ? <button type="button" className={btn} onClick={() => setEditing(r)}>Edit</button> : <Lock size={13} aria-label="locked" />}
                        {editing && editing.kind === r.kind && editing.id === r.id && (
                          <EditRow row={r} sources={sources} onCancel={() => setEditing(null)}
                            onSaved={async () => { setEditing(null); setNotice(`${r.label} updated — the version's approval was reset; it needs re-approval.`); setData(await getHkConfigPack(packId)); }} />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
