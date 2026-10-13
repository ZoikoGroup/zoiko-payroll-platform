import { useEffect, useState } from "react";
import { Landmark, ShieldCheck, Trash2, Zap, Eye } from "lucide-react";
import {
  listSwissCatalogSchemes, createSwissCatalogScheme, deleteSwissCatalogScheme,
  approveSwissCatalogScheme, activateSwissCatalogScheme,
} from "../../../service/superAdminService";
import StatusPill from "../../StatusPill";
import { inputClass, labelClass } from "../constants";
import { CH_CANTON_CODES, CH_SCHEME_TYPES } from "./chComponentConfig";

const SCHEME_STATUS_PILL = { DRAFT: "pending", APPROVED: "approved", ACTIVE: "active", SUPERSEDED: "inactive" };

const EMPTY_FORM = {
  schemeType: "COMPENSATION_OFFICE", schemeCode: "", name: "", version: "1.0",
  authorityIdentifier: "", canton: "", rulesText: "{}", effectiveFrom: "", effectiveTo: "",
  sourceDocumentId: "", reason: "",
};

// CH Step 5 — platform scheme catalog (organization_id NULL "definitions").
// Compensation-office admin-cost, FAK, BVG plans, UVG/KTG policies live here
// so an organisation's own profiles can reference them, with the same
// maker-checker lifecycle as everything else: DRAFT -> APPROVED -> ACTIVE,
// each transition by a distinct Super Admin. Rules are validated server-side
// against the scheme type (validate_scheme_rules).
export default function CHSchemeCatalogTab({ addToast }) {
  const [rows, setRows] = useState([]);
  const [schemeType, setSchemeType] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [detailId, setDetailId] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [reason, setReason] = useState("");

  const load = () => {
    listSwissCatalogSchemes({
      ...(schemeType ? { schemeType } : {}),
      ...(statusFilter ? { status: statusFilter } : {}),
    })
      .then(setRows)
      .catch((e) => setError(e?.message || "Failed to load the scheme catalog."));
  };
  useEffect(() => { load(); }, [schemeType, statusFilter]);

  async function create() {
    setError(null);
    try {
      let rules = {};
      try { rules = JSON.parse(form.rulesText || "{}"); }
      catch { setError("Rules must be valid JSON."); return; }
      await createSwissCatalogScheme({
        schemeType: form.schemeType, schemeCode: form.schemeCode, name: form.name,
        version: form.version || undefined,
        authorityIdentifier: form.authorityIdentifier || undefined,
        canton: form.canton || undefined, rules,
        effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || undefined,
        sourceDocumentId: form.sourceDocumentId || undefined, reason: form.reason || undefined,
      });
      addToast?.("Catalog scheme created (DRAFT).", "success");
      setShowCreate(false); setForm(EMPTY_FORM); load();
    } catch (e) { setError(e?.message || "Create failed."); }
  }

  async function runConfirmed(row) {
    const { action } = confirming;
    setError(null);
    try {
      if (action === "delete") { await deleteSwissCatalogScheme(row.id); addToast?.("Deleted.", "success"); }
      if (action === "approve") { await approveSwissCatalogScheme(row.id, reason || null); addToast?.("Approved.", "success"); }
      if (action === "activate") { await activateSwissCatalogScheme(row.id, reason || null); addToast?.("Activated.", "success"); }
      setConfirming(null); setReason(""); setDetailId(null); load();
    } catch (e) { setError(e?.message || "Action failed."); }
  }

  const editable = (r) => r.status === "DRAFT";
  const next = (r) => r.status === "DRAFT" ? "approve" : r.status === "APPROVED" ? "activate" : null;

  return (
    <section aria-labelledby="ch-schemes-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="ch-schemes-heading" className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <Landmark size={13} /> Platform scheme catalog
          </h3>
          <p className="text-xs text-foreground-muted">
            Compensation-office, FAK, BVG, UVG and KTG scheme definitions an organisation can reference in its Swiss
            entity profile and QST resolution. Rules are validated against the scheme type server-side.
          </p>
        </div>
        <button type="button" onClick={() => setShowCreate(true)}
          className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover">
          New scheme
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select className={inputClass + " w-auto"} value={schemeType} onChange={(e) => setSchemeType(e.target.value)}>
          <option value="">All scheme types</option>
          {CH_SCHEME_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className={inputClass + " w-auto"} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {["DRAFT", "APPROVED", "ACTIVE", "SUPERSEDED"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && <p role="alert" className="text-xs text-error">{error}</p>}

      <div className="space-y-2">
        {rows.length === 0 ? (
          <p className="py-6 text-center text-xs text-foreground-disabled">No catalog schemes match.</p>
        ) : rows.map((r) => (
          <div key={r.id} className="rounded-xl border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs font-semibold text-foreground">{r.schemeCode}</span>
              <span className="text-xs text-foreground-secondary">{r.schemeType}</span>
              <span className="text-xs text-foreground-muted">v{r.version}</span>
              {r.canton && <span className="text-xs text-foreground-muted">{r.canton}</span>}
              <StatusPill status={SCHEME_STATUS_PILL[r.status] || "pending"} label={r.status} />
              <div className="ml-auto flex items-center gap-1.5">
                <button type="button" onClick={() => setDetailId(detailId === r.id ? null : r.id)} title="Rules"
                  className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs text-foreground-muted hover:bg-surface-muted">
                  <Eye size={12} /> rules
                </button>
                {next(r) && (
                  <button type="button" onClick={() => setConfirming({ row: r, action: next(r) })}
                    className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                    {next(r) === "approve" ? <><ShieldCheck size={12} /> Approve</> : <><Zap size={12} /> Activate</>}
                  </button>
                )}
                {editable(r) && (
                  <button type="button" onClick={() => setConfirming({ row: r, action: "delete" })}
                    className="inline-flex items-center gap-1 rounded-lg border border-error/40 px-2 py-1 text-xs font-semibold text-error hover:bg-error/5">
                    <Trash2 size={12} /> Delete
                  </button>
                )}
              </div>
            </div>
            <p className="mt-1 text-xs text-foreground-secondary">{r.name}</p>
            <p className="flex flex-wrap gap-x-4 text-[11px] text-foreground-muted">
              <span>{r.effectiveFrom}{r.effectiveTo ? ` → ${r.effectiveTo}` : " → open"}</span>
              <span className="font-mono">sha {r.rulesSha256?.slice(0, 12)}…</span>
              {r.createdById ? <span>created by #({r.createdById})</span> : null}
            </p>
            {detailId === r.id && (
              <pre className="mt-2 overflow-x-auto rounded-lg bg-surface-muted p-2 font-mono text-[11px] text-foreground-secondary">
                {JSON.stringify(r.rules, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="rounded-xl border border-border p-4">
          <p className="mb-3 text-xs font-semibold text-foreground">New catalog scheme (DRAFT)</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass} htmlFor="sch-type">Scheme type</label>
              <select id="sch-type" className={inputClass} value={form.schemeType} onChange={(e) => setForm({ ...form, schemeType: e.target.value })}>
                {CH_SCHEME_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div><label className={labelClass} htmlFor="sch-code">Scheme code</label>
              <input id="sch-code" className={inputClass} value={form.schemeCode} onChange={(e) => setForm({ ...form, schemeCode: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="sch-name">Name</label>
              <input id="sch-name" className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="sch-ver">Version</label>
              <input id="sch-ver" className={inputClass} value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="sch-auth">Authority identifier</label>
              <input id="sch-auth" className={inputClass} value={form.authorityIdentifier} onChange={(e) => setForm({ ...form, authorityIdentifier: e.target.value })} /></div>
            <div>
              <label className={labelClass} htmlFor="sch-canton">Canton</label>
              <select id="sch-canton" className={inputClass} value={form.canton} onChange={(e) => setForm({ ...form, canton: e.target.value })}>
                <option value="">Country-level</option>
                {CH_CANTON_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div><label className={labelClass} htmlFor="sch-from">Effective from</label>
              <input id="sch-from" type="date" className={inputClass} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="sch-to">Effective to</label>
              <input id="sch-to" type="date" className={inputClass} value={form.effectiveTo} onChange={(e) => setForm({ ...form, effectiveTo: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="sch-src">Source artifact id</label>
              <input id="sch-src" type="number" className={inputClass} value={form.sourceDocumentId} onChange={(e) => setForm({ ...form, sourceDocumentId: e.target.value })} /></div>
          </div>
          <div className="mt-3">
            <label className={labelClass} htmlFor="sch-rules">Rules (JSON — validated against the scheme type)</label>
            <textarea id="sch-rules" rows={4} className={inputClass + " font-mono text-xs"} value={form.rulesText} onChange={(e) => setForm({ ...form, rulesText: e.target.value })} />
          </div>
          <div className="mt-3">
            <label className={labelClass} htmlFor="sch-reason">Reason</label>
            <input id="sch-reason" className={inputClass} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button type="button" onClick={create} className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover">Create</button>
            <button type="button" onClick={() => { setShowCreate(false); setError(null); setForm(EMPTY_FORM); }}
              className="rounded-lg border border-border px-3 py-2 text-xs text-foreground-muted hover:bg-surface-muted">Cancel</button>
          </div>
        </div>
      )}

      {confirming && (
        <div className="rounded-xl border border-warning/40 bg-warning-light p-4">
          <p className="text-xs font-semibold text-foreground">
            {confirming.action === "delete" && `Delete "${confirming.row.schemeCode}"? Only an unreferenced DRAFT can be deleted.`}
            {confirming.action === "approve" && `Approve ${confirming.row.schemeCode} — a Super Admin other than its author/editors.`}
            {confirming.action === "activate" && `Activate ${confirming.row.schemeCode} — a Super Admin other than its approver.`}
          </p>
          {confirming.action !== "delete" && (
            <input className={inputClass + " mt-2"} placeholder="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
          )}
          <div className="mt-3 flex items-center gap-2">
            <button type="button" onClick={() => runConfirmed(confirming.row)}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">Confirm {confirming.action}</button>
            <button type="button" onClick={() => { setConfirming(null); setReason(""); }}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-foreground-muted hover:bg-surface-muted">Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}