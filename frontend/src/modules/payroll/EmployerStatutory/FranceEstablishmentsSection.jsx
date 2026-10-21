import { useState } from "react";
import { CalendarX, Pencil, Plus } from "lucide-react";
import {
  appendFranceRatePack, closeFranceRatePack, createFranceEstablishment, listFranceEstablishments,
  listFranceRatePacks, updateFranceEstablishment, updateFranceRatePack,
} from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { display, opt, period, today } from "./format";

const BLANK_EST = { siret: "", name: "", address: "", communeInsee: "", workforceLocation: "", payrollIdentifier: "", isActive: true };

const FNAL = { UNDER_50: "FNAL — fewer than 50 (0.10%)", OVER_50: "FNAL — 50 or more (0.50%)" };
const CFP = { UNDER_11: "CFP — fewer than 11 (0.55%)", OVER_11: "CFP — 11 or more (1.00%)" };
const AGS = [
  { value: "", label: "Standard" },
  { value: "TEMPORARY_WORK", label: "Temporary-work agency (special AGS rate)" },
  { value: "EXEMPT", label: "Exempt / not affiliated" },
];

const loadAll = () => Promise.all([listFranceEstablishments(), listFranceRatePacks()])
  .then(([establishments, packs]) => ({
    establishments: Array.isArray(establishments) ? establishments : [],
    packs: Array.isArray(packs) ? packs : [],
  }));

function EstablishmentForm({ establishment, onCancel, onSaved }) {
  const [form, setForm] = useState(() => ({ ...BLANK_EST, ...(establishment || {}) }));
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function submit(e) {
    e.preventDefault();
    const siret = String(form.siret || "").replace(/\s/g, "");
    if (!/^\d{14}$/.test(siret)) return setError("SIRET must be exactly 14 digits (SIREN + 5-digit NIC).");
    const commune = String(form.communeInsee || "").trim().toUpperCase();
    if (commune && !/^(\d{5}|2[AB]\d{3})$/.test(commune)) {
      return setError("The commune INSEE code is 5 characters (e.g. 75056, or 2A004 / 2B033 for Corsica).");
    }
    const payload = {
      siret, name: opt(form.name), address: opt(form.address), communeInsee: commune || null,
      workforceLocation: opt(form.workforceLocation), payrollIdentifier: opt(form.payrollIdentifier), isActive: !!form.isActive,
    };
    const res = await run(() => (establishment?.id ? updateFranceEstablishment(establishment.id, payload) : createFranceEstablishment(payload)));
    if (res.ok) onSaved(establishment?.id ? "Establishment updated." : "Establishment registered.");
  }

  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 md:grid-cols-3" aria-label="Establishment">
      <Field id="est-siret" label="SIRET (14 digits)" required>
        <input id="est-siret" className={inputCls} inputMode="numeric" value={form.siret} required
          disabled={!!establishment?.id} onChange={set("siret")} placeholder="55210055400013" />
      </Field>
      <Field id="est-name" label="Name"><input id="est-name" className={inputCls} value={form.name || ""} onChange={set("name")} /></Field>
      <Field id="est-commune" label="Commune INSEE code"><input id="est-commune" className={inputCls} value={form.communeInsee || ""} onChange={set("communeInsee")} placeholder="75056" /></Field>
      <Field id="est-address" label="Address" className="md:col-span-2"><input id="est-address" className={inputCls} value={form.address || ""} onChange={set("address")} /></Field>
      <Field id="est-location" label="Workforce location"><input id="est-location" className={inputCls} value={form.workforceLocation || ""} onChange={set("workforceLocation")} /></Field>
      <Field id="est-payroll-id" label="Payroll identifier"><input id="est-payroll-id" className={inputCls} value={form.payrollIdentifier || ""} onChange={set("payrollIdentifier")} /></Field>
      <label className="flex items-center gap-2 self-end text-[12px] font-medium text-foreground-secondary">
        <input type="checkbox" checked={!!form.isActive} onChange={set("isActive")} /> Active
      </label>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel={establishment?.id ? "Save establishment" : "Register establishment"} onCancel={onCancel} />
    </form>
  );
}

function initialRate(p) {
  return {
    establishmentId: p?.establishmentId ?? "", effectiveFrom: p?.effectiveFrom || "",
    atMpRatePct: p?.atMpRatePct ?? "", atMpRiskCode: p?.atMpRiskCode || "", atMpEvidence: p?.atMpEvidence || "", atMpSource: p?.atMpSource || "",
    vmRatePct: p?.vmRatePct ?? "", vmNotDue: p ? p.vmThresholdApplies === false : false, vmEvidence: p?.vmEvidence || "", vmSource: p?.vmSource || "",
    agsSpecialStatus: p?.agsSpecialStatus || "", fnalClass: p?.fnalClass || "UNDER_50", cfpClass: p?.cfpClass || "UNDER_11",
    effectif: p?.effectif ?? "",
  };
}

function pctOrThrow(value, label) {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number(value);
  if (Number.isNaN(n) || n < 0 || n > 100) throw new Error(`${label} rate must be between 0 and 100%.`);
  return n;
}

function RatePackForm({ period: existing, establishments, onCancel, onSaved }) {
  const edit = !!existing;
  const [form, setForm] = useState(() => {
    const f = initialRate(existing);
    if (!edit && establishments.length === 1) f.establishmentId = establishments[0].id;
    return f;
  });
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function submit(e) {
    e.preventDefault();
    let atMp; let vm;
    try {
      if (!edit && !form.establishmentId) throw new Error("Choose the establishment.");
      if (!edit && !form.effectiveFrom) throw new Error("Effective from is required.");
      atMp = pctOrThrow(form.atMpRatePct, "AT/MP");
      vm = form.vmNotDue ? null : pctOrThrow(form.vmRatePct, "Versement mobilité");
      if (atMp == null) throw new Error("An AT/MP rate is required — enter the rate from the Urssaf decision.");
      if (!form.atMpEvidence.trim() && !form.atMpSource.trim()) throw new Error("Give the AT/MP evidence reference or source.");
      if (!form.vmNotDue && vm == null) throw new Error("Enter the versement mobilité rate, or tick “not due” for an establishment under 11 employees.");
      if (vm != null && !form.vmEvidence.trim() && !form.vmSource.trim()) throw new Error("Give the versement mobilité evidence reference or source.");
      if (form.effectif !== "" && (!Number.isInteger(Number(form.effectif)) || Number(form.effectif) < 0)) throw new Error("Effectif must be a whole number.");
    } catch (err) {
      setError(err.message);
      return;
    }
    const payload = {
      atMpRatePct: atMp, atMpRiskCode: opt(form.atMpRiskCode), atMpEvidence: opt(form.atMpEvidence), atMpSource: opt(form.atMpSource),
      vmRatePct: vm, vmThresholdApplies: !form.vmNotDue,
      vmEvidence: form.vmNotDue ? null : opt(form.vmEvidence), vmSource: form.vmNotDue ? null : opt(form.vmSource),
      agsSpecialStatus: form.agsSpecialStatus || null, fnalClass: form.fnalClass, cfpClass: form.cfpClass,
      effectif: form.effectif === "" ? null : Number(form.effectif),
    };
    const res = await run(() => (edit
      ? updateFranceRatePack(existing.id, payload)
      : appendFranceRatePack({ ...payload, establishmentId: Number(form.establishmentId), effectiveFrom: form.effectiveFrom })));
    if (res.ok) onSaved(edit ? "Future period updated." : "Rate period added — the previous open period closes the day before.");
  }

  const backdated = !edit && form.effectiveFrom && form.effectiveFrom < today();
  return (
    <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 rounded-[14px] border border-border p-4 md:grid-cols-2" aria-label="Employer rate period">
      <Field id="rp-est" label="Establishment" required={!edit}>
        <select id="rp-est" className={inputCls} value={form.establishmentId} disabled={edit} onChange={set("establishmentId")}>
          <option value="">Select…</option>
          {establishments.map((e) => <option key={e.id} value={e.id}>{e.siret}{e.name ? ` — ${e.name}` : ""}</option>)}
        </select>
      </Field>
      <Field id="rp-from" label="Effective from" required={!edit}
        hint={backdated ? "Backdated — payrolls already run for this period are not recalculated automatically." : undefined}>
        <input id="rp-from" type="date" className={inputCls} value={form.effectiveFrom} disabled={edit} onChange={set("effectiveFrom")} />
      </Field>
      <p className="col-span-full border-t border-border pt-3 text-[12px] font-bold text-foreground-secondary">AT/MP — workplace accident &amp; disease (Urssaf decision)</p>
      <Field id="rp-atmp" label="AT/MP rate %" required><input id="rp-atmp" type="number" min="0" max="100" step="0.01" className={inputCls} value={form.atMpRatePct} onChange={set("atMpRatePct")} placeholder="e.g. 2.09" /></Field>
      <Field id="rp-risk" label="Risk code"><input id="rp-risk" className={inputCls} value={form.atMpRiskCode} onChange={set("atMpRiskCode")} placeholder="e.g. 741GA" /></Field>
      <Field id="rp-atmp-ev" label="Evidence reference"><input id="rp-atmp-ev" className={inputCls} value={form.atMpEvidence} onChange={set("atMpEvidence")} /></Field>
      <Field id="rp-atmp-src" label="Source"><input id="rp-atmp-src" className={inputCls} value={form.atMpSource} onChange={set("atMpSource")} /></Field>
      <p className="col-span-full border-t border-border pt-3 text-[12px] font-bold text-foreground-secondary">Versement mobilité</p>
      <label className="col-span-full flex items-center gap-2 text-[12px] font-medium text-foreground-secondary">
        <input type="checkbox" checked={form.vmNotDue} onChange={set("vmNotDue")} /> Not due — establishment below the 11-employee threshold
      </label>
      {!form.vmNotDue && (
        <>
          <Field id="rp-vm" label="VM rate %" required><input id="rp-vm" type="number" min="0" max="100" step="0.01" className={inputCls} value={form.vmRatePct} onChange={set("vmRatePct")} placeholder="e.g. 2.95" /></Field>
          <Field id="rp-vm-ev" label="Evidence reference"><input id="rp-vm-ev" className={inputCls} value={form.vmEvidence} onChange={set("vmEvidence")} /></Field>
          <Field id="rp-vm-src" label="Source"><input id="rp-vm-src" className={inputCls} value={form.vmSource} onChange={set("vmSource")} /></Field>
        </>
      )}
      <p className="col-span-full border-t border-border pt-3 text-[12px] font-bold text-foreground-secondary">Employer-size classes &amp; special status</p>
      <Field id="rp-fnal" label="FNAL class"><select id="rp-fnal" className={inputCls} value={form.fnalClass} onChange={set("fnalClass")}>{Object.entries(FNAL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field id="rp-cfp" label="CFP class"><select id="rp-cfp" className={inputCls} value={form.cfpClass} onChange={set("cfpClass")}>{Object.entries(CFP).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field id="rp-ags" label="Unemployment / AGS status"><select id="rp-ags" className={inputCls} value={form.agsSpecialStatus} onChange={set("agsSpecialStatus")}>{AGS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}</select></Field>
      <Field id="rp-eff" label="Establishment effectif"><input id="rp-eff" type="number" min="0" className={inputCls} value={form.effectif} onChange={set("effectif")} /></Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel={edit ? "Save changes" : "Add period"} onCancel={onCancel} />
    </form>
  );
}

function ClosePeriodForm({ pack, onCancel, onSaved }) {
  const [date, setDate] = useState("");
  const { run, busy, error, setError } = useAction();
  async function submit(e) {
    e.preventDefault();
    if (!date) return setError("Choose the last day of the period.");
    if (date < String(pack.effectiveFrom)) return setError("The end date cannot be before the period start.");
    const res = await run(() => closeFranceRatePack(pack.id, date));
    if (res.ok) onSaved("Period closed.");
  }
  return (
    <form onSubmit={submit} className="mb-4 flex flex-wrap items-end gap-3 rounded-[14px] border border-border p-4" aria-label="Close rate period">
      <Field id="rp-close" label={`Last day of the period starting ${pack.effectiveFrom} (${pack.siret})`} required>
        <input id="rp-close" type="date" className={inputCls} value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>
      <FormActions busy={busy} submitLabel="Close period" onCancel={onCancel} />
      <div className="w-full"><Messages error={error} /></div>
    </form>
  );
}

export default function FranceEstablishmentsSection({ readOnly }) {
  const { data, error, initialLoading, reload } = useLoad(loadAll);
  const [estEdit, setEstEdit] = useState(null);     // null | {} | establishment
  const [rateEdit, setRateEdit] = useState(null);   // null | {} | period
  const [closing, setClosing] = useState(null);
  const [notice, setNotice] = useState(null);
  const toggle = useAction();

  if (initialLoading) return <LoadingState text="Loading establishments…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const establishments = data?.establishments || [];
  const packs = [...(data?.packs || [])].sort((a, b) =>
    String(a.siret).localeCompare(String(b.siret)) || String(b.effectiveFrom).localeCompare(String(a.effectiveFrom)));
  const active = establishments.filter((e) => e.isActive);
  const now = today();
  const done = (msg) => { setEstEdit(null); setRateEdit(null); setClosing(null); setNotice(msg); reload(); };

  async function toggleActive(est) {
    const res = await toggle.run(() => updateFranceEstablishment(est.id, {
      siret: est.siret, name: est.name, address: est.address, communeInsee: est.communeInsee,
      workforceLocation: est.workforceLocation, payrollIdentifier: est.payrollIdentifier, isActive: !est.isActive,
    }));
    if (res.ok) done(est.isActive ? "Establishment deactivated." : "Establishment reactivated.");
  }

  return (
    <div className="space-y-4">
      <Messages notice={notice} error={toggle.error} />
      <div className={cardCls}>
        <SectionHeader title="Establishments (SIRET)"
          description="Each SIRET you pay from. A SIRET cannot change once registered; an establishment is deactivated, never deleted.">
          {!readOnly && !estEdit && (
            <button type="button" className={btnPrimary} onClick={() => { setEstEdit({}); setNotice(null); }}>
              <Plus size={13} aria-hidden="true" /> Register establishment
            </button>
          )}
        </SectionHeader>
        {estEdit && <EstablishmentForm establishment={estEdit.id ? estEdit : null} onCancel={() => setEstEdit(null)} onSaved={done} />}
        {establishments.length === 0 ? (
          <EmptyState title="No establishments yet" text="Register at least one SIRET establishment before adding employer rates." />
        ) : (
          <DataTable label="France establishments" rows={establishments} columns={[
            { key: "siret", label: "SIRET", render: (e) => <span className="font-mono">{e.siret}</span> },
            { key: "name", label: "Name" },
            { key: "communeInsee", label: "Commune" },
            { key: "workforceLocation", label: "Location" },
            { key: "isActive", label: "Status", render: (e) => <StatusBadge status={e.isActive ? "Active" : "Inactive"} /> },
            { key: "actions", label: "", render: (e) => (readOnly ? null : (
              <div className="flex flex-wrap gap-1.5">
                <button type="button" className={btnSecondary} onClick={() => setEstEdit(e)}><Pencil size={12} aria-hidden="true" /> Edit</button>
                <button type="button" className={btnSecondary} disabled={toggle.busy} onClick={() => toggleActive(e)}>{e.isActive ? "Deactivate" : "Reactivate"}</button>
              </div>
            )) },
          ]} />
        )}
      </div>

      <div className={cardCls}>
        <SectionHeader title="Employer rates per establishment"
          description="AT/MP, versement mobilité, FNAL/CFP class and AGS status by effective period. A new period closes the open one; only periods that have not started can be edited.">
          {!readOnly && !rateEdit && (
            <button type="button" className={btnPrimary} disabled={active.length === 0}
              title={active.length === 0 ? "Register an active establishment first" : undefined}
              onClick={() => { setRateEdit({}); setClosing(null); setNotice(null); }}>
              <Plus size={13} aria-hidden="true" /> Add period
            </button>
          )}
        </SectionHeader>
        {rateEdit && <RatePackForm period={rateEdit.id ? rateEdit : null} establishments={active} onCancel={() => setRateEdit(null)} onSaved={done} />}
        {closing && <ClosePeriodForm pack={closing} onCancel={() => setClosing(null)} onSaved={done} />}
        {packs.length === 0 ? (
          <EmptyState title="No employer-rate periods yet" text="Payroll for France stays blocked until each establishment has rates in force." />
        ) : (
          <DataTable label="France employer-rate periods" rows={packs} columns={[
            { key: "siret", label: "SIRET", render: (p) => <span className="font-mono">{p.siret}</span> },
            { key: "period", label: "Period", render: (p) => period(p.effectiveFrom, p.effectiveTo) },
            { key: "atMpRatePct", label: "AT/MP %" },
            { key: "vmRatePct", label: "VM %", render: (p) => (p.vmThresholdApplies === false ? "Not due" : display(p.vmRatePct)) },
            { key: "fnalClass", label: "FNAL" },
            { key: "cfpClass", label: "CFP" },
            { key: "state", label: "State", render: (p) => {
              if (p.effectiveFrom > now) return <StatusBadge status="Future" tone="info" />;
              if (p.effectiveTo && p.effectiveTo < now) return <StatusBadge status="Closed" />;
              return <StatusBadge status="In force" tone="good" />;
            } },
            { key: "actions", label: "", render: (p) => (readOnly ? null : (
              <div className="flex flex-wrap gap-1.5">
                {p.effectiveFrom > now && (
                  <button type="button" className={btnSecondary} onClick={() => { setRateEdit(p); setClosing(null); }}><Pencil size={12} aria-hidden="true" /> Edit</button>
                )}
                {!p.effectiveTo && (
                  <button type="button" className={btnSecondary} onClick={() => { setClosing(p); setRateEdit(null); }}><CalendarX size={12} aria-hidden="true" /> Close</button>
                )}
              </div>
            )) },
          ]} />
        )}
      </div>
    </div>
  );
}
