import { useEffect, useState } from "react";
import { ShieldCheck, Zap } from "lucide-react";
import { listSwissWageFloors, createSwissWageFloor, approveSwissWageFloor, activateSwissWageFloor } from "../../../service/superAdminService";
import StatusPill from "../../StatusPill";
import { inputClass, labelClass } from "../constants";
import { CH_CANTON_CODES, CH_WAGE_FLOOR_TYPES } from "./chComponentConfig";

const FLOOR_STATUS_PILL = { DRAFT: "pending", APPROVED: "approved", ACTIVE: "active", SUPERSEDED: "inactive" };

const EMPTY_FORM = {
  agreementType: "CH_CANTON_MINIMUM", agreementCode: "", name: "", version: "1.0",
  jurisdictionState: "", employerScope: "", employeeGroup: "", wageFloorText: "{}",
  effectiveFrom: "", effectiveTo: "", sourceDocumentId: "", reason: "",
};

// Canton wage floors (collective agreements — CH_CANTON_MINIMUM, GAV, NAV).
// A wage floor is a flat base amount and/or scale rows, validated server-side
// (ChWageFloor: at least one of amount / scales must be set; a canton minimum
// needs the canton). Lifecycle: DRAFT -> APPROVED -> ACTIVE by distinct
// Super Admins; activating the next version supersedes the previous Active one.
export default function CHWageFloorTab({ addToast }) {
  const [rows, setRows] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [reason, setReason] = useState("");

  const load = () => {
    listSwissWageFloors()
      .then(setRows)
      .catch((e) => setError(e?.message || "Failed to load wage floors."));
  };
  useEffect(() => { load(); }, []);

  async function create() {
    setError(null);
    try {
      let wageFloor;
      try { wageFloor = JSON.parse(form.wageFloorText || "{}"); }
      catch { setError("Wage floor must be valid JSON."); return; }
      await createSwissWageFloor({
        agreementType: form.agreementType, agreementCode: form.agreementCode, name: form.name,
        version: form.version || undefined, jurisdictionState: form.jurisdictionState || undefined,
        employerScope: form.employerScope || undefined, employeeGroup: form.employeeGroup || undefined,
        wageFloor, effectiveFrom: form.effectiveFrom, effectiveTo: form.effectiveTo || undefined,
        sourceDocumentId: form.sourceDocumentId || undefined, reason: form.reason || undefined,
      });
      addToast?.("Wage floor created (DRAFT).", "success");
      setShowCreate(false); setForm(EMPTY_FORM); load();
    } catch (e) { setError(e?.message || "Create failed."); }
  }

  async function runConfirmed(row) {
    const { action } = confirming;
    setError(null);
    try {
      if (action === "approve") { await approveSwissWageFloor(row.id, reason || null); addToast?.("Approved.", "success"); }
      if (action === "activate") { await activateSwissWageFloor(row.id, reason || null); addToast?.("Activated.", "success"); }
      setConfirming(null); setReason(""); load();
    } catch (e) { setError(e?.message || "Action failed."); }
  }

  const next = (r) => r.status === "DRAFT" ? "approve" : r.status === "APPROVED" ? "activate" : null;
  const fmtAmount = (f) => {
    const wf = f || {};
    const bits = [];
    if (wf.amount != null) bits.push(`${wf.basis || ""} CHF ${wf.amount}`.trim());
    if (Array.isArray(wf.scales) && wf.scales.length) bits.push(`${wf.scales.length} scale row(s)`);
    return bits.length ? bits.join(" · ") : "—";
  };

  return (
    <section aria-labelledby="ch-floors-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id="ch-floors-heading" className="text-sm font-semibold text-foreground">Canton wage floors</h3>
          <p className="text-xs text-foreground-muted">
            Collective-agreement minimums (canton minimums, GAV, NAV) with base amounts and/or scale rows. The engine
            checks earnings against the Active floor for the worker&apos;s canton.
          </p>
        </div>
        <button type="button" onClick={() => setShowCreate(true)}
          className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover">
          New agreement
        </button>
      </div>

      {error && <p role="alert" className="text-xs text-error">{error}</p>}

      <div className="space-y-2">
        {rows.length === 0 ? (
          <p className="py-6 text-center text-xs text-foreground-disabled">No wage floors yet.</p>
        ) : rows.map((r) => (
          <div key={r.id} className="rounded-xl border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs font-semibold text-foreground">{r.agreementCode}</span>
              <span className="text-xs text-foreground-secondary">{r.agreementType}</span>
              <span className="text-xs text-foreground-muted">v{r.version}</span>
              {r.jurisdictionState && <span className="font-mono text-xs text-foreground-muted">{r.jurisdictionState}</span>}
              <StatusPill status={FLOOR_STATUS_PILL[r.status] || "pending"} label={r.status} />
              <div className="ml-auto flex items-center gap-1.5">
                {next(r) && (
                  <button type="button" onClick={() => setConfirming({ row: r, action: next(r) })}
                    className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                    {next(r) === "approve" ? <><ShieldCheck size={12} /> Approve</> : <><Zap size={12} /> Activate</>}
                  </button>
                )}
              </div>
            </div>
            <p className="mt-1 text-xs text-foreground-secondary">{r.name}</p>
            <p className="text-[11px] text-foreground-muted">
              {fmtAmount(r.wageFloor)}
              {r.employeeGroup ? ` · ${r.employeeGroup}` : ""}
              <span className="mx-1">·</span>{r.effectiveFrom}{r.effectiveTo ? ` → ${r.effectiveTo}` : " → open"}
            </p>
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="rounded-xl border border-border p-4">
          <p className="mb-3 text-xs font-semibold text-foreground">New wage-floor agreement (DRAFT)</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass} htmlFor="wf-type">Agreement type</label>
              <select id="wf-type" className={inputClass} value={form.agreementType} onChange={(e) => setForm({ ...form, agreementType: e.target.value })}>
                {CH_WAGE_FLOOR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div><label className={labelClass} htmlFor="wf-code">Agreement code</label>
              <input id="wf-code" className={inputClass} value={form.agreementCode} onChange={(e) => setForm({ ...form, agreementCode: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-name">Name</label>
              <input id="wf-name" className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-ver">Version</label>
              <input id="wf-ver" className={inputClass} value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} /></div>
            <div>
              <label className={labelClass} htmlFor="wf-state">Canton (required for CH_CANTON_MINIMUM)</label>
              <select id="wf-state" className={inputClass} value={form.jurisdictionState} onChange={(e) => setForm({ ...form, jurisdictionState: e.target.value })}>
                <option value="">All cantons</option>
                {CH_CANTON_CODES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div><label className={labelClass} htmlFor="wf-scope">Employer scope</label>
              <input id="wf-scope" className={inputClass} value={form.employerScope} onChange={(e) => setForm({ ...form, employerScope: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-group">Employee group</label>
              <input id="wf-group" className={inputClass} value={form.employeeGroup} onChange={(e) => setForm({ ...form, employeeGroup: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-from">Effective from</label>
              <input id="wf-from" type="date" className={inputClass} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-to">Effective to</label>
              <input id="wf-to" type="date" className={inputClass} value={form.effectiveTo} onChange={(e) => setForm({ ...form, effectiveTo: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-src">Source artifact id</label>
              <input id="wf-src" type="number" className={inputClass} value={form.sourceDocumentId} onChange={(e) => setForm({ ...form, sourceDocumentId: e.target.value })} /></div>
            <div><label className={labelClass} htmlFor="wf-reason">Reason</label>
              <input id="wf-reason" className={inputClass} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></div>
          </div>
          <div className="mt-3">
            <label className={labelClass} htmlFor="wf-json">Wage floor (JSON — {"{ amount, basis: HOURLY|MONTHLY|ANNUAL, scales: [{occupation, grade, experienceYearsFrom, amount}] }"})</label>
            <textarea id="wf-json" rows={4} className={inputClass + " font-mono text-xs"} value={form.wageFloorText}
              onChange={(e) => setForm({ ...form, wageFloorText: e.target.value })} />
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
            {confirming.action === "approve"
              ? `Approve ${confirming.row.agreementCode} — a Super Admin other than its author (source document required).`
              : `Activate ${confirming.row.agreementCode} — a Super Admin other than its approver; the previous Active version is superseded.`}
          </p>
          <input className={inputClass + " mt-2"} placeholder="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
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