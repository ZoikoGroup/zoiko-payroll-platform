import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, Loader2 } from "lucide-react";
import { getItalyEmployerProfile, saveItalyEmployerProfile } from "../../../service/payrollService";

// Italy employer profile (ZP-IT-ENG-001 §17 B-G). The operator records FACTS;
// the readiness status is recomputed by the server on every save and is never
// sent from here (IT-049). Italian payroll for this organization stays
// blocked until the platform's own release gates pass as well.

const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const label = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";

const EMPTY = {
  matricolaInps: "", cscCode: "", caCode: "", atecoCode: "", inpsOffice: "", cnelCode: "",
  fund: "", fisBand: "", priorYearAvgHeadcount: "", tesoreriaStatus: "", f24OperatingModel: "", lulMethod: "",
};

const fromProfile = (p) => (p ? {
  matricolaInps: p.matricolaInps || "", cscCode: p.cscCode || "", caCode: p.caCode || "",
  atecoCode: p.atecoCode || "", inpsOffice: p.inpsOffice || "", cnelCode: p.cnelCode || "",
  fund: p.fundStatus?.fund || "", fisBand: p.fundStatus?.fisBand || "",
  priorYearAvgHeadcount: p.priorYearAvgHeadcount ?? "", tesoreriaStatus: p.tesoreriaStatus || "",
  f24OperatingModel: p.f24OperatingModel || "", lulMethod: p.lulMethod || "",
} : EMPTY);

function Field({ id, text, hint, children }) {
  return (
    <div>
      <label htmlFor={id} className={label}>{text}</label>
      <div className="mt-1.5">{children}</div>
      {hint && <p className="mt-1 text-[11px] text-foreground-muted">{hint}</p>}
    </div>
  );
}

export default function ITEmployerProfileTab() {
  const [profile, setProfile] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let live = true;
    getItalyEmployerProfile()
      .then((p) => { if (live) { setProfile(p || null); setForm(fromProfile(p)); } })
      .catch((e) => { if (live) setError(e?.message || "Failed to load the Italy employer profile."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  const set = (field) => (e) => { setForm((f) => ({ ...f, [field]: e.target.value })); setSaved(false); };
  const blank = (v) => (v === "" ? null : v);

  async function save() {
    setSaving(true); setError(null); setSaved(false);
    try {
      const p = await saveItalyEmployerProfile({
        matricolaInps: blank(form.matricolaInps), cscCode: blank(form.cscCode), caCode: blank(form.caCode),
        atecoCode: blank(form.atecoCode), inpsOffice: blank(form.inpsOffice), cnelCode: blank(form.cnelCode),
        fundStatus: form.fund ? { fund: form.fund, fisBand: form.fund === "FIS" ? blank(form.fisBand) : null } : null,
        priorYearAvgHeadcount: form.priorYearAvgHeadcount === "" ? null : Number(form.priorYearAvgHeadcount),
        tesoreriaStatus: blank(form.tesoreriaStatus), f24OperatingModel: blank(form.f24OperatingModel),
        lulMethod: blank(form.lulMethod),
      });
      setProfile(p);
      setForm(fromProfile(p));
      setSaved(true);
    } catch (e) {
      setError(e?.message || "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex items-center gap-2 p-6 text-[13px] text-foreground-muted"><Loader2 size={14} className="animate-spin" /> Loading…</div>;
  }
  const items = profile?.readinessEvidence?.items || [];
  const ready = profile?.readinessStatus === "READY";

  return (
    <div className="space-y-5">
      <div className="bg-surface border border-border rounded-[18px] p-5 space-y-4">
        <div>
          <h3 className="text-[15px] font-bold text-foreground">Italy employer profile</h3>
          <p className="mt-1 text-[12px] text-foreground-muted">
            INPS registration, income-support fund, CCNL and Fondo Tesoreria facts. Italian contribution rates are
            looked up from your CSC/CA classification — there is no single national rate to enter here.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field id="it-er-matricola" text="Matricola INPS"><input id="it-er-matricola" className={input} value={form.matricolaInps} onChange={set("matricolaInps")} /></Field>
          <Field id="it-er-csc" text="CSC (codice statistico contributivo)"><input id="it-er-csc" className={input} value={form.cscCode} onChange={set("cscCode")} /></Field>
          <Field id="it-er-ca" text="CA (codice autorizzazione)" hint="Leave blank if INPS assigned none."><input id="it-er-ca" className={input} value={form.caCode} onChange={set("caCode")} /></Field>
          <Field id="it-er-ateco" text="ATECO"><input id="it-er-ateco" className={input} value={form.atecoCode} onChange={set("atecoCode")} /></Field>
          <Field id="it-er-office" text="INPS office"><input id="it-er-office" className={input} value={form.inpsOffice} onChange={set("inpsOffice")} /></Field>
          <Field id="it-er-cnel" text="Reference CCNL (CNEL code)"><input id="it-er-cnel" className={input} value={form.cnelCode} onChange={set("cnelCode")} placeholder="H011" /></Field>
          <Field id="it-er-fund" text="Income-support fund">
            <select id="it-er-fund" className={input} value={form.fund} onChange={set("fund")}>
              <option value="">Not recorded</option>
              <option value="CIG">CIG (cassa integrazione)</option>
              <option value="FIS">FIS (fondo di integrazione salariale)</option>
              <option value="SECTOR_FUND">Sector bilateral fund</option>
            </select>
          </Field>
          {form.fund === "FIS" && (
            <Field id="it-er-fisband" text="FIS size band">
              <select id="it-er-fisband" className={input} value={form.fisBand} onChange={set("fisBand")}>
                <option value="">Select…</option>
                <option value="UP_TO_5">Up to 5 employees (0.50%)</option>
                <option value="OVER_5">More than 5 employees (0.80%)</option>
              </select>
            </Field>
          )}
          <Field id="it-er-headcount" text="Prior-year average headcount" hint="Decides whether unallocated TFR must go to the Fondo Tesoreria (IT-040).">
            <input id="it-er-headcount" className={input} inputMode="numeric" value={form.priorYearAvgHeadcount} onChange={set("priorYearAvgHeadcount")} />
          </Field>
          <Field id="it-er-tesoreria" text="Fondo Tesoreria status">
            <select id="it-er-tesoreria" className={input} value={form.tesoreriaStatus} onChange={set("tesoreriaStatus")}>
              <option value="">Not recorded</option>
              <option value="OBLIGED">Obliged</option>
              <option value="NOT_OBLIGED">Not obliged</option>
              <option value="TRANSFER_PRESERVED">Preserved after a transfer (IT-041)</option>
            </select>
          </Field>
          <Field id="it-er-f24" text="F24 operating model"><input id="it-er-f24" className={input} value={form.f24OperatingModel} onChange={set("f24OperatingModel")} placeholder="EMPLOYER" /></Field>
          <Field id="it-er-lul" text="LUL method"><input id="it-er-lul" className={input} value={form.lulMethod} onChange={set("lulMethod")} placeholder="ELECTRONIC" /></Field>
        </div>
        {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
        {saved && <p role="status" className="text-[12px] font-medium text-primary">Saved — readiness recalculated.</p>}
        <button type="button" onClick={save} disabled={saving}
          className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
          {saving ? "Saving…" : "Save employer profile"}
        </button>
      </div>

      {profile && (
        <div className="bg-surface border border-border rounded-[18px] p-5 space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-[15px] font-bold text-foreground">Employer readiness</h3>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ready ? "bg-primary/10 text-primary" : "bg-warning/10 text-warning"}`}>
              {ready ? "Employer facts complete" : "Incomplete"}
            </span>
          </div>
          <ul className="divide-y divide-border-light rounded-xl border border-border">
            {items.map((i) => (
              <li key={i.key} className="flex items-start gap-2 px-3 py-2 text-[12px]">
                {i.complete
                  ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-primary" aria-label="Complete" />
                  : <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-label="Incomplete" />}
                <div>
                  <p className="font-medium text-foreground">{i.label}</p>
                  {i.detail && <p className="text-foreground-muted">{i.detail}</p>}
                </div>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-foreground-muted">
            Complete employer facts do not switch on Italian payroll by themselves: the platform&apos;s statutory content
            must also pass its release gates.
          </p>
        </div>
      )}
    </div>
  );
}
