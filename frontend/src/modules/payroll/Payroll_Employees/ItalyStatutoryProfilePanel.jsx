import { useEffect, useState } from "react";
import { History, X } from "lucide-react";
import {
  createEmployeeStatutoryProfile,
  getEmployeeStatutoryProfile,
  getEmployeeStatutoryProfileHistory,
} from "../../../service/payrollService";
import {
  IT_CAP_COHORTS, IT_CONTRACT_TYPES, IT_LAUNCH_COMMUNI, IT_REGIONS, IT_TFR_DESTINATIONS,
} from "../../../components/jurisdiction/italy/itComponentConfig";

// Italy statutory profile (ZP-IT-ENG-001 §18): the worker facts the engine
// reads, as an append-only, effective-dated version history — a TFR election
// or a move of tax domicile mid-year must never rewrite an earlier payslip
// (IT-013, IT-038). Values are validated server-side against the engine's own
// vocabularies; nothing here computes a statutory figure.

const inputCls =
  "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground outline-none transition-colors focus:border-primary";

const FIELDS = [
  "itWorkerClass", "itContractType", "itCigsApplies", "itContributoryCapCohort", "itCnelCode", "itCnelLevel",
  "itContractualWeeklyHours", "itTaxDomicileRegion", "itTaxDomicileComune", "itTaxDomicileFrom",
  "itTfrDestination", "itPensionFund", "itTfrDestinationFrom", "itFringeChildDeclared", "itTerminationReason",
];
const BOOLEANS = new Set(["itCigsApplies", "itFringeChildDeclared"]);

function formFromProfile(p) {
  const today = new Date().toISOString().slice(0, 10);
  const form = { effectiveFrom: today, reason: "" };
  FIELDS.forEach((f) => { form[f] = BOOLEANS.has(f) ? Boolean(p?.[f]) : (p?.[f] ?? ""); });
  return form;
}

function buildPayload(form) {
  const payload = { countryCode: "IT", effectiveFrom: form.effectiveFrom, reason: form.reason || null };
  FIELDS.forEach((f) => { payload[f] = BOOLEANS.has(f) ? form[f] : (form[f] === "" ? null : form[f]); });
  return payload;
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

export default function ItalyStatutoryProfilePanel({ employee, onClose }) {
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [form, setForm] = useState(formFromProfile(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState("");

  async function reload() {
    const [current, hist] = await Promise.all([
      getEmployeeStatutoryProfile(employee.id).catch(() => null),
      getEmployeeStatutoryProfileHistory(employee.id).catch(() => []),
    ]);
    setProfile(current);
    setHistory(hist || []);
    setForm(formFromProfile(current));
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try { if (!cancelled) await reload(); } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee.id]);

  const set = (key) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true); setSaveError(""); setSaveSuccess("");
    try {
      await createEmployeeStatutoryProfile(employee.id, buildPayload(form));
      setSaveSuccess("New statutory profile version saved.");
      await reload();
    } catch (err) {
      setSaveError(err.message || "Could not save this statutory profile version.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Italy statutory profile</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee.name} · {employee.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>

        {loading ? (
          <p className="p-6 text-[13px] text-foreground-muted">Loading…</p>
        ) : (
          <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <p className="text-[12px] text-foreground-muted">
              {profile ? `Current version in force from ${profile.effectiveFrom}. ` : "No statutory profile yet — Italian payroll is blocked for this employee until one is saved. "}
              Saving always creates a new version; earlier versions stay as they were.
            </p>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Effective from"><input type="date" required className={inputCls} value={form.effectiveFrom} onChange={set("effectiveFrom")} /></Field>
              <Field label="Reason for change"><input className={inputCls} value={form.reason} onChange={set("reason")} /></Field>
            </div>

            <h3 className="text-[12px] font-bold text-foreground">INPS and contract</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="INPS worker class" hint="Must match a class in the INPS matrix for your CSC, e.g. IMPIEGATO.">
                <input className={inputCls} value={form.itWorkerClass} onChange={set("itWorkerClass")} />
              </Field>
              <Field label="Contract type">
                <select className={inputCls} value={form.itContractType} onChange={set("itContractType")}>
                  <option value="">Not recorded</option>
                  {IT_CONTRACT_TYPES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
              <Field label="CCNL (CNEL code)"><input className={inputCls} value={form.itCnelCode} onChange={set("itCnelCode")} /></Field>
              <Field label="CCNL level"><input className={inputCls} value={form.itCnelLevel} onChange={set("itCnelLevel")} /></Field>
              <Field label="Contractual weekly hours" hint="Below the CCNL full-time week = part-time (IT-018).">
                <input className={inputCls} inputMode="decimal" value={form.itContractualWeeklyHours} onChange={set("itContractualWeeklyHours")} />
              </Field>
              <Field label="Contribution-ceiling cohort" hint="Only with first-insurance or option evidence (IT-017).">
                <select className={inputCls} value={form.itContributoryCapCohort} onChange={set("itContributoryCapCohort")}>
                  <option value="">None</option>
                  {IT_CAP_COHORTS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
            </div>
            <label className="flex items-center gap-2 text-[13px] text-foreground-secondary">
              <input type="checkbox" checked={form.itCigsApplies} onChange={set("itCigsApplies")} /> CIGS applies to this worker
            </label>

            <h3 className="text-[12px] font-bold text-foreground">Tax domicile (not the workplace — IT-013)</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field label="Region">
                <select className={inputCls} value={form.itTaxDomicileRegion} onChange={set("itTaxDomicileRegion")}>
                  <option value="">Not recorded</option>
                  {IT_REGIONS.map(([c, n]) => <option key={c} value={c}>{c} — {n}</option>)}
                </select>
              </Field>
              <Field label="Comune (cadastral code)" hint="e.g. F205 = Milano">
                <input className={inputCls} list="it-sp-communi" value={form.itTaxDomicileComune} onChange={set("itTaxDomicileComune")} />
                <datalist id="it-sp-communi">{IT_LAUNCH_COMMUNI.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</datalist>
              </Field>
              <Field label="Domiciled since"><input type="date" className={inputCls} value={form.itTaxDomicileFrom} onChange={set("itTaxDomicileFrom")} /></Field>
            </div>

            <h3 className="text-[12px] font-bold text-foreground">TFR and benefits</h3>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field label="TFR destination">
                <select className={inputCls} value={form.itTfrDestination} onChange={set("itTfrDestination")}>
                  <option value="">Not elected</option>
                  {IT_TFR_DESTINATIONS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </Field>
              {form.itTfrDestination === "FONDO_PENSIONE" && (
                <Field label="Pension fund"><input className={inputCls} value={form.itPensionFund} onChange={set("itPensionFund")} /></Field>
              )}
              <Field label="Election date"><input type="date" className={inputCls} value={form.itTfrDestinationFrom} onChange={set("itTfrDestinationFrom")} /></Field>
            </div>
            <label className="flex items-center gap-2 text-[13px] text-foreground-secondary">
              <input type="checkbox" checked={form.itFringeChildDeclared} onChange={set("itFringeChildDeclared")} />
              Employee has declared dependent children for the higher fringe-benefit limit (IT-032)
            </label>

            {saveError && <p role="alert" className="text-[12px] font-medium text-error">{saveError}</p>}
            {saveSuccess && <p role="status" className="text-[12px] font-medium text-primary">{saveSuccess}</p>}
            <div className="flex items-center gap-2">
              <button type="submit" disabled={saving}
                className="rounded-[10px] bg-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
                {saving ? "Saving…" : "Save new version"}
              </button>
              <button type="button" onClick={() => setShowHistory((v) => !v)}
                className="flex items-center gap-1.5 rounded-[10px] border border-border px-3 py-2 text-[12px] font-semibold text-foreground-secondary hover:border-primary">
                <History size={13} /> {showHistory ? "Hide" : "Show"} history ({history.length})
              </button>
            </div>
            {showHistory && (
              <ul className="divide-y divide-border-light rounded-xl border border-border text-[12px]">
                {history.map((h) => (
                  <li key={h.id} className="px-3 py-2 text-foreground-secondary">
                    <span className="font-medium text-foreground">{h.effectiveFrom} → {h.effectiveTo || "open"}</span>
                    {" · "}{h.itWorkerClass || "—"} · {h.itContractType || "—"} · domicile {h.itTaxDomicileComune || "—"} · TFR {h.itTfrDestination || "—"}
                    {h.reason && <span className="block text-foreground-muted">{h.reason}</span>}
                  </li>
                ))}
              </ul>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
