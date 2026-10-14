import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, CircleAlert, Loader2, Plus, Trash2 } from "lucide-react";
import { getSwissEntityProfile, saveSwissEntityProfile, listSwissSchemes } from "../../../service/payrollService";
import { CH_CANTONS } from "../../../components/jurisdiction/switzerland/chComponentConfig";
import CHElmSubmissionsPanel from "../Reports/CHElmSubmissionsPanel";

// Switzerland employer profile (ZP-CH-PAYROLL-001). The operator records the
// employer's FACTS (UID, seat canton, canton QST registrations, compensation-
// office + FAK scheme assignments); readiness is recomputed by the server on
// every save and is NEVER sent from here. Saving always opens a new profile
// version starting `effectiveFrom` — no version is ever rewritten. QST daily
// rate cards, tariff files and taxability are platform data (Super Admin),
// not editable here; the advisory qst/resolve check is exposed instead.

const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const label = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY = { uid: "", seatCanton: "", registrations: [], compensationOfficeSchemeId: "", fakSchemeId: "", effectiveFrom: "", reason: "" };

const fromCurrent = (c) => (c ? {
  uid: c.uid || "",
  seatCanton: c.seatCanton || "",
  registrations: (c.cantonRegistrations || []).map((r) => ({ canton: r.canton || "", qstDebtorNumber: r.qstDebtorNumber || "", reference: r.reference || "" })),
  compensationOfficeSchemeId: c.compensationOfficeSchemeId ?? "",
  fakSchemeId: c.fakSchemeId ?? "",
  effectiveFrom: c.effectiveFrom || todayISO(),
  reason: "",
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

export default function CHEmployerProfileTab() {
  const [profile, setProfile] = useState(null);
  const [schemes, setSchemes] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([getSwissEntityProfile(), listSwissSchemes()])
      .then(([prof, schemes]) => {
        if (!live) return;
        setProfile(prof || null);
        setSchemes(Array.isArray(schemes) ? schemes : []);
        setForm(fromCurrent(prof?.current));
      })
      .catch((e) => { if (live) setError(e?.message || "Failed to load the Swiss employer profile."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  const set = (field) => (e) => { setForm((f) => ({ ...f, [field]: e.target.value })); setSaved(false); };
  const blank = (v) => (v === "" ? null : v);

  const assignable = useMemo(() => {
    const usable = (schemes || []).filter((s) => s.status !== "RETIRED");
    return {
      compensationOffice: usable.filter((s) => s.schemeType === "COMPENSATION_OFFICE"),
      fak: usable.filter((s) => s.schemeType === "FAK"),
    };
  }, [schemes]);

  const schemeLabel = (s) => `${s.schemeCode} — ${s.name} v${s.version} (${s.status})${s.catalog ? " · platform catalog" : ""}`;

  const setRegistration = (idx, patch) => {
    setForm((f) => {
      const registrations = f.registrations.map((r, i) => (i === idx ? { ...r, ...patch } : r));
      return { ...f, registrations };
    });
    setSaved(false);
  };
  const addRegistration = () => {
    const used = new Set(form.registrations.map((r) => r.canton).filter(Boolean));
    const next = CH_CANTONS.find(([code]) => !used.has(code));
    setForm((f) => ({ ...f, registrations: [...f.registrations, { canton: next ? next[0] : "", qstDebtorNumber: "", reference: "" }] }));
    setSaved(false);
  };
  const removeRegistration = (idx) => {
    setForm((f) => ({ ...f, registrations: f.registrations.filter((_, i) => i !== idx) }));
    setSaved(false);
  };
  const remainingCantons = CH_CANTONS.filter(([code]) => !form.registrations.some((r) => r.canton === code));

  async function save() {
    setSaving(true); setError(null); setSaved(false);
    try {
      const p = await saveSwissEntityProfile({
        uid: blank(form.uid.trim()),
        seatCanton: blank(form.seatCanton),
        cantonRegistrations: form.registrations
          .filter((r) => r.canton)
          .map((r) => ({ canton: r.canton, qstDebtorNumber: blank(r.qstDebtorNumber.trim()), reference: blank(r.reference.trim()) })),
        compensationOfficeSchemeId: form.compensationOfficeSchemeId === "" ? null : Number(form.compensationOfficeSchemeId),
        fakSchemeId: form.fakSchemeId === "" ? null : Number(form.fakSchemeId),
        effectiveFrom: form.effectiveFrom || todayISO(),
        reason: blank(form.reason.trim()),
      });
      setProfile(p);
      setForm(fromCurrent(p?.current));
      setSaved(true);
    } catch (e) {
      setError(e?.message || "Failed to save the Swiss employer profile.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex items-center gap-2 p-6 text-[13px] text-foreground-muted"><Loader2 size={14} className="animate-spin" /> Loading…</div>;
  }

  const readiness = profile?.readinessNow || null;
  const ready = readiness?.status === "READY";
  const checks = readiness?.checks || [];
  const versions = profile?.versions || [];

  return (
    <div className="space-y-5">
      <div className="bg-surface border border-border rounded-[18px] p-5 space-y-4">
        <div>
          <h3 className="text-[15px] font-bold text-foreground">Swiss employer profile</h3>
          <p className="mt-1 text-[12px] text-foreground-muted">
            UID, seat canton, canton QST registrations and the assigned compensation-office (AHV) and FAK fund
            schemes. Swiss statutory rates are looked up from LIVE platform schemes/tariffs — there is no national
            rate to enter here. Saving opens a new profile version; readiness is recomputed server-side.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field id="ch-er-uid" text="UID (Business Identification No.)" hint="Format CHE-123.456.789.">
            <input id="ch-er-uid" className={input} value={form.uid} onChange={set("uid")} placeholder="CHE-123.456.789" maxLength={15} />
          </Field>
          <Field id="ch-er-seat" text="Seat canton">
            <select id="ch-er-seat" className={input} value={form.seatCanton} onChange={set("seatCanton")}>
              <option value="">Select…</option>
              {CH_CANTONS.map(([code, name]) => <option key={code} value={code}>{code} — {name}</option>)}
            </select>
          </Field>
          <Field id="ch-er-effective" text="Effective from">
            <input id="ch-er-effective" type="date" className={input} value={form.effectiveFrom} onChange={set("effectiveFrom")} />
          </Field>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className={label}>Canton QST registrations</p>
            <button type="button" onClick={addRegistration}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[11px] font-bold text-foreground-muted hover:text-foreground">
              <Plus size={12} /> Add canton
            </button>
          </div>
          {form.registrations.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-light bg-surface px-3 py-4 text-[12px] text-foreground-disabled">
              No canton QST registrations recorded yet — the seat canton must be registered before the employer is READY.
            </p>
          ) : (
            <div className="divide-y divide-border-light rounded-xl border border-border">
              {form.registrations.map((r, idx) => (
                <div key={idx} className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-5 sm:items-end">
                  <Field id={`ch-er-reg-canton-${idx}`} text="Canton">
                    <select id={`ch-er-reg-canton-${idx}`} className={input} value={r.canton} onChange={(e) => setRegistration(idx, { canton: e.target.value })}>
                      <option value="">Select…</option>
                      {(r.canton ? CH_CANTONS : remainingCantons).map(([code, name]) => <option key={code} value={code}>{code} — {name}</option>)}
                    </select>
                  </Field>
                  <div className="sm:col-span-2">
                    <Field id={`ch-er-reg-qst-${idx}`} text="QST debtor number">
                      <input id={`ch-er-reg-qst-${idx}`} className={input} value={r.qstDebtorNumber} onChange={(e) => setRegistration(idx, { qstDebtorNumber: e.target.value })} />
                    </Field>
                  </div>
                  <div className="sm:col-span-2">
                    <div className="flex items-end gap-2">
                    <Field id={`ch-er-reg-ref-${idx}`} text="Reference">
                      <input id={`ch-er-reg-ref-${idx}`} className={input} value={r.reference} onChange={(e) => setRegistration(idx, { reference: e.target.value })} />
                    </Field>
                    <button type="button" onClick={() => removeRegistration(idx)} aria-label="Remove canton"
                      className="mb-0.5 rounded-lg border border-border p-2 text-foreground-muted hover:text-error">
                      <Trash2 size={14} />
                    </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="ch-er-comp-office" text="Compensation office scheme (AHV)" hint="LIVE COMPENSATION_OFFICE scheme that runs the AHV/IV/EO/ALV collections.">
            <select id="ch-er-comp-office" className={input} value={form.compensationOfficeSchemeId} onChange={set("compensationOfficeSchemeId")}>
              <option value="">Select…</option>
              {assignable.compensationOffice.map((s) => <option key={s.id} value={s.id}>{schemeLabel(s)}</option>)}
            </select>
          </Field>
          <Field id="ch-er-fak" text="FAK fund scheme" hint="LIVE FAK scheme that runs the canton's family allowances.">
            <select id="ch-er-fak" className={input} value={form.fakSchemeId} onChange={set("fakSchemeId")}>
              <option value="">Select…</option>
              {assignable.fak.map((s) => <option key={s.id} value={s.id}>{schemeLabel(s)}</option>)}
            </select>
          </Field>
        </div>

        <Field id="ch-er-reason" text="Reason for change" hint="Optional audit note kept with this profile version.">
          <input id="ch-er-reason" className={input} value={form.reason} onChange={set("reason")} maxLength={500} />
        </Field>

        {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
        {saved && <p role="status" className="text-[12px] font-medium text-primary">Saved — a new profile version is in force and readiness was recomputed.</p>}
        <button type="button" onClick={save} disabled={saving}
          className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
          {saving ? "Saving…" : "Save employer profile"}
        </button>
      </div>

      {readiness && (
        <div className="bg-surface border border-border rounded-[18px] p-5 space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-[15px] font-bold text-foreground">Employer readiness</h3>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ready ? "bg-primary/10 text-primary" : "bg-warning/10 text-warning"}`}>
              {ready ? "Employer facts complete" : "Incomplete"}
            </span>
            {readiness.asOf && <span className="text-[11px] text-foreground-muted">as of {readiness.asOf}</span>}
          </div>
          <ul className="divide-y divide-border-light rounded-xl border border-border">
            {checks.map((c) => (
              <li key={c.key} className="flex items-start gap-2 px-3 py-2 text-[12px]">
                {c.passed
                  ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-primary" aria-label="Passed" />
                  : <CircleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-label="Not passed" />}
                <div>
                  <p className="font-medium text-foreground">{c.key}</p>
                  {c.detail && <p className="text-foreground-muted">{c.detail}</p>}
                </div>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-foreground-muted">
            Complete employer facts do not switch on Swiss payroll by themselves: the platform&apos;s statutory content
            for the employee&apos;s canton must also pass its release gates.
          </p>
        </div>
      )}

      {versions.length > 0 && (
        <div className="bg-surface border border-border rounded-[18px] p-5 space-y-3">
          <h3 className="text-[15px] font-bold text-foreground">Profile versions</h3>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-surface-muted border-b border-border text-left text-foreground-muted">
                  <th className="px-3 py-2 font-bold">UID</th>
                  <th className="px-3 py-2 font-bold">Seat canton</th>
                  <th className="px-3 py-2 font-bold">Registrations</th>
                  <th className="px-3 py-2 font-bold">Effective</th>
                  <th className="px-3 py-2 font-bold">Readiness</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {versions.map((v) => (
                  <tr key={v.id}>
                    <td className="px-3 py-2 font-mono text-foreground">{v.uid || "—"}</td>
                    <td className="px-3 py-2 text-foreground">{v.seatCanton || "—"}</td>
                    <td className="px-3 py-2 text-foreground-muted">{(v.cantonRegistrations || []).length}</td>
                    <td className="px-3 py-2 text-foreground-muted">{v.effectiveFrom}{v.effectiveTo ? ` → ${v.effectiveTo}` : ""}</td>
                    <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${v.readinessStatus === "READY" ? "bg-primary/10 text-primary" : "bg-warning/10 text-warning"}`}>{v.readinessStatus}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <CHElmSubmissionsPanel />
    </div>
  );
}