import { useState } from "react";
import { History, Pencil } from "lucide-react";
import {
  correctFranceEffectif, getFranceEmployerProfile, recordFranceEffectif, upsertFranceEmployerProfile,
} from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import {
  btnPrimary, btnSecondary, cardCls, DataTable, EmptyState, ErrorState, Field, FormActions, inputCls,
  LoadingState, Messages, SectionHeader, StatusBadge,
} from "./ui";
import { display, opt, when } from "./format";

const DUE_CLASSES = {
  M15: "15th of M+1 (< 50 employees)",
  M5: "5th of M+1 (≥ 50 employees)",
  DEFERRED_M15: "Deferred M15 (authority-granted deferral)",
};
const IDCC_STATUSES = {
  APPLICABLE: "Applicable (IDCC code set)",
  NOT_APPLICABLE: "Not applicable",
  UNDER_REVIEW: "Unknown — under review (blocks launch)",
};
const EFFECTIF_SOURCES = ["DSN", "PAYE", "AUTHORITY", "MANUAL"];

const TEXT_FIELDS = [
  { key: "siren", label: "SIREN (9 digits)", placeholder: "552100554", required: true, numeric: true },
  { key: "legalName", label: "Legal name", placeholder: "ACME SAS", required: true },
  { key: "legalForm", label: "Legal form", placeholder: "SAS / SARL / SA …" },
  { key: "payrollContact", label: "Payroll contact", placeholder: "Name · email · phone" },
  { key: "address", label: "Registered address", placeholder: "Street, postcode, city", wide: true },
  { key: "urssafAccount", label: "Urssaf account", placeholder: "7500000000001", numeric: true },
  { key: "dsnDeclarant", label: "DSN declarant", placeholder: "Declarant / software id" },
  { key: "paymentMandateRef", label: "Payment mandate (SEPA)", placeholder: "Mandate reference" },
  { key: "pasCollectorIdentity", label: "DGFiP PAS collector identity", placeholder: "Collector id" },
];

function toForm(p) {
  return {
    siren: p?.siren || "", legalName: p?.legalName || "", legalForm: p?.legalForm || "",
    payrollContact: p?.payrollContact || "", address: p?.address || "",
    idcc: p?.idcc || "", idccStatus: p?.idccStatus || (p?.idcc ? "APPLICABLE" : "UNDER_REVIEW"),
    urssafAccount: p?.urssafAccount || "", dsnDeclarant: p?.dsnDeclarant || "",
    filingDueDateClass: p?.filingDueDateClass || "M15",
    paymentMandateRef: p?.paymentMandateRef || "", pasCollectorIdentity: p?.pasCollectorIdentity || "",
  };
}

function effectifHistory(state) {
  if (!state || typeof state !== "object") return [];
  return Object.entries(state)
    .map(([year, info]) => ({
      year: Number(year),
      value: info && typeof info === "object" ? info.value : info,
      source: info && typeof info === "object" ? info.source : "—",
      history: info && typeof info === "object" && Array.isArray(info.history) ? info.history : [],
    }))
    .filter((h) => Number.isFinite(h.year))
    .sort((a, b) => b.year - a.year);
}

function ProfileForm({ profile, onCancel, onSaved }) {
  const [form, setForm] = useState(() => toForm(profile));
  const { run, busy, error, setError } = useAction();
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!/^\d{9}$/.test(form.siren.trim())) return setError("SIREN must be exactly 9 digits.");
    if (!form.legalName.trim()) return setError("Legal name is required.");
    if (form.idccStatus === "APPLICABLE" && !form.idcc.trim()) {
      return setError("Enter the IDCC code, or choose Not applicable / Under review.");
    }
    const payload = {};
    Object.entries(form).forEach(([k, v]) => { payload[k] = opt(v); });
    payload.siren = form.siren.trim();
    payload.filingDueDateClass = form.filingDueDateClass;
    payload.idcc = form.idccStatus === "APPLICABLE" ? form.idcc.trim() : null;
    const res = await run(() => upsertFranceEmployerProfile(payload));
    if (res.ok) onSaved(res.data);
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="France employer profile">
      {TEXT_FIELDS.map((f) => (
        <Field key={f.key} id={`fr-${f.key}`} label={f.label} required={f.required} className={f.wide ? "md:col-span-2" : ""}>
          <input id={`fr-${f.key}`} className={inputCls} value={form[f.key]} placeholder={f.placeholder}
            inputMode={f.numeric ? "numeric" : "text"} required={f.required} onChange={set(f.key)} />
        </Field>
      ))}
      <Field id="fr-idccStatus" label="Collective agreement (IDCC)" required>
        <select id="fr-idccStatus" className={inputCls} value={form.idccStatus} onChange={set("idccStatus")}>
          {Object.entries(IDCC_STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <Field id="fr-idcc" label="IDCC code" required={form.idccStatus === "APPLICABLE"}>
        <input id="fr-idcc" className={inputCls} value={form.idcc} placeholder="e.g. 1596"
          disabled={form.idccStatus !== "APPLICABLE"} onChange={set("idcc")} />
      </Field>
      <Field id="fr-due" label="Filing due-date class" hint="M5 for 50+ staff, M15 below 50; Deferred M15 only under an authority-granted deferral.">
        <select id="fr-due" className={inputCls} value={form.filingDueDateClass} onChange={set("filingDueDateClass")}>
          {Object.entries(DUE_CLASSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </Field>
      <div className="col-span-full"><Messages error={error} /></div>
      <FormActions busy={busy} submitLabel="Save profile" onCancel={onCancel} />
    </form>
  );
}

function EffectifPanel({ profile, readOnly, onSaved }) {
  const [form, setForm] = useState({ year: String(new Date().getFullYear() - 1), value: "", source: "DSN", reason: "" });
  const { run, busy, error, notice, setError } = useAction();
  const history = effectifHistory(profile?.effectifState);
  const yearNumber = form.year === "" ? null : Number(form.year);
  const correcting = history.some((h) => h.year === yearNumber);

  async function submit(e) {
    e.preventDefault();
    const maxYear = new Date().getFullYear() + 1;
    if (!Number.isInteger(yearNumber) || yearNumber < 2000 || yearNumber > maxYear) return setError("Enter a plausible year.");
    const value = Number(form.value);
    if (form.value === "" || !Number.isInteger(value) || value < 0) return setError("Effectif must be a whole number of 0 or more.");
    if (correcting && !form.reason.trim()) return setError("A correction needs a reason — it is kept in the history.");
    const payload = { year: yearNumber, value, source: form.source };
    const res = await run(
      () => (correcting ? correctFranceEffectif({ ...payload, reason: form.reason.trim() }) : recordFranceEffectif(payload)),
      correcting ? `Effectif ${yearNumber} corrected — the previous value is kept in history.` : "Effectif recorded.",
    );
    if (res.ok) {
      setForm((f) => ({ ...f, value: "", reason: "" }));
      onSaved(res.data);
    }
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="Governed effectif"
        description="Annual average headcount from a governed source. Drives the 11-employee (CFP, versement mobilité) and 50-employee (FNAL, RGDU, M5 filing) thresholds." />
      {!readOnly && (
        <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Record effectif">
          <Field id="fr-eff-year" label="Year" required>
            <input id="fr-eff-year" type="number" min="2000" className={inputCls} value={form.year}
              onChange={(e) => setForm((f) => ({ ...f, year: e.target.value }))} />
          </Field>
          <Field id="fr-eff-value" label="Annual average effectif" required>
            <input id="fr-eff-value" type="number" min="0" step="1" className={inputCls} value={form.value} placeholder="e.g. 47"
              onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} />
          </Field>
          <Field id="fr-eff-source" label="Governed source">
            <select id="fr-eff-source" className={inputCls} value={form.source} onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}>
              {EFFECTIF_SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
          {correcting && (
            <Field id="fr-eff-reason" label="Reason for correction" required className="col-span-full">
              <input id="fr-eff-reason" className={inputCls} value={form.reason} placeholder="e.g. Urssaf recount notice of 12/03"
                onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
              <p className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold text-warning">
                <History size={13} aria-hidden="true" /> {yearNumber} is already recorded — this saves a correction.
              </p>
            </Field>
          )}
          <div className="col-span-full"><Messages error={error} notice={notice} /></div>
          <FormActions busy={busy} submitLabel={correcting ? "Save correction" : "Record effectif"} />
        </form>
      )}
      {history.length === 0 ? (
        <EmptyState title="No effectif recorded yet" text="Record the annual average headcount for the last completed year." />
      ) : (
        <DataTable label="Effectif history" rowKey={(h) => h.year} rows={history} columns={[
          { key: "year", label: "Year" },
          { key: "value", label: "Effectif" },
          { key: "source", label: "Source" },
          { key: "t11", label: "11+ (CFP / VM)", render: (h) => <StatusBadge status={h.value >= 11 ? "11+" : "Under 11"} tone={h.value >= 11 ? "good" : "muted"} /> },
          { key: "t50", label: "50+ (FNAL / M5)", render: (h) => <StatusBadge status={h.value >= 50 ? "50+" : "Under 50"} tone={h.value >= 50 ? "good" : "muted"} /> },
          { key: "corr", label: "Corrections", render: (h) => (h.history.length
            ? h.history.map((c, i) => <div key={i} className="text-[11px] text-foreground-muted">was {display(c?.value)} ({display(c?.source)}) — {display(c?.reason)}</div>)
            : "—") },
        ]} />
      )}
    </div>
  );
}

export default function FranceProfileSection({ readOnly }) {
  const { data: profile, error, notFound, initialLoading, reload, setData } = useLoad(getFranceEmployerProfile);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState(null);

  if (initialLoading) return <LoadingState text="Loading employer profile…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const p = notFound ? null : profile;
  const facts = p ? [
    ["SIREN", p.siren], ["Legal entity", [p.legalName, p.legalForm].filter(Boolean).join(" · ")],
    ["Payroll contact", p.payrollContact], ["Address", p.address],
    ["IDCC", p.idcc || IDCC_STATUSES[p.idccStatus] || "Not set"], ["Urssaf account", p.urssafAccount],
    ["DSN declarant", p.dsnDeclarant], ["Filing due date", DUE_CLASSES[p.filingDueDateClass] || p.filingDueDateClass],
    ["Payment mandate", p.paymentMandateRef], ["PAS collector", p.pasCollectorIdentity],
    ["PAS CRM status", p.pasCrmStatus], ["Last updated", when(p.updatedAt || p.createdAt)],
  ] : [];

  const saved = (data) => { setData(data); setEditing(false); setNotice("Employer profile saved."); };

  return (
    <div className="space-y-4">
      <div className={cardCls}>
        <SectionHeader title="Employer profile"
          description="Legal entity, collective agreement, Urssaf/DSN identity and DGFiP PAS collector. Readiness is computed from these records — it is never set by hand.">
          {!editing && !readOnly && (
            <button type="button" className={btnPrimary} onClick={() => { setEditing(true); setNotice(null); }}>
              <Pencil size={13} aria-hidden="true" /> {p ? "Edit profile" : "Set up profile"}
            </button>
          )}
        </SectionHeader>
        <Messages notice={notice} />
        {editing ? (
          <ProfileForm profile={p} onCancel={() => setEditing(false)} onSaved={saved} />
        ) : p ? (
          <>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-4 text-[12px] sm:grid-cols-2 lg:grid-cols-4">
              {facts.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-foreground-muted">{label}</dt>
                  <dd className="mt-0.5 break-words font-medium text-foreground">{display(value)}</dd>
                </div>
              ))}
            </dl>
            {p.idccStatus === "UNDER_REVIEW" && (
              <p className="mt-3 text-[11px] text-warning">The IDCC is under review — France go-live stays blocked until it is resolved.</p>
            )}
          </>
        ) : (
          <EmptyState title="France employer profile not configured yet"
            text={readOnly ? "Open this page on a larger screen to set it up." : "Use “Set up profile” to record the SIREN identity."}>
            {!readOnly && <button type="button" className={btnSecondary} onClick={() => setEditing(true)}>Set up profile</button>}
          </EmptyState>
        )}
      </div>
      {p ? (
        <EffectifPanel profile={p} readOnly={readOnly} onSaved={setData} />
      ) : (
        <div className={cardCls}>
          <SectionHeader title="Governed effectif" />
          <EmptyState title="Set up the employer profile first" text="The effectif history is recorded on the employer profile." />
        </div>
      )}
    </div>
  );
}
