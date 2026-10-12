import { useState } from "react";
import { Building2, Pencil, AlertTriangle } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import { getFranceEmployerProfile, upsertFranceEmployerProfile } from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass, labelClass } from "../constants";
import { dueDateClassLabel, IDCC_STATUSES } from "./franceStatutoryConfig";
import { useFranceOrgData } from "./useFranceOrgData";

const DUE_CLASSES = ["M15", "M5", "DEFERRED_M15"];

const TEXT_FIELDS = [
  { key: "siren", label: "SIREN (9 digits) *", placeholder: "552100554", section: "A" },
  { key: "legalName", label: "Legal name *", placeholder: "ACME SAS", section: "A" },
  { key: "legalForm", label: "Legal form", placeholder: "SAS / SARL / SA …", section: "A" },
  { key: "payrollContact", label: "Payroll contact", placeholder: "Name · email · phone", section: "A" },
  { key: "address", label: "Registered address", placeholder: "Street, postcode, city", section: "A", wide: true },
  { key: "urssafAccount", label: "Urssaf account", placeholder: "7500000000001", section: "C" },
  { key: "dsnDeclarant", label: "DSN declarant", placeholder: "Declarant / software id", section: "C" },
  { key: "paymentMandateRef", label: "Payment mandate (SEPA)", placeholder: "Mandate reference", section: "C" },
  { key: "pasCollectorIdentity", label: "DGFiP PAS collector identity", placeholder: "Collector id", section: "D" },
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

// France employer profile (FR §11 panels A, C, D). Readiness is NOT set here
// — it is computed from the real records (Overview & Readiness) and LIVE is
// a separate, gated action. The governed effectif has its own section.
export default function FranceEmployerProfilePanel({ organizationId }) {
  const { addToast } = useToast() || {};
  const { data: profile, error, loading, setData } = useFranceOrgData(organizationId, getFranceEmployerProfile);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  async function save() {
    if (!/^\d{9}$/.test(form.siren.trim())) return setFormError("SIREN must be exactly 9 digits.");
    if (!form.legalName.trim()) return setFormError("Legal name is required.");
    if (form.idccStatus === "APPLICABLE" && !form.idcc.trim()) {
      return setFormError("Enter the IDCC code, or choose Not applicable / Under review (FR-035).");
    }
    setFormError("");
    setSaving(true);
    try {
      const payload = { ...form, siren: form.siren.trim(), idcc: form.idccStatus === "APPLICABLE" ? form.idcc.trim() : null };
      Object.keys(payload).forEach((k) => { if (payload[k] === "") payload[k] = null; });
      const updated = await upsertFranceEmployerProfile(payload, { organizationId });
      setData(updated);
      setForm(null);
      addToast?.("Employer profile saved.", "success");
    } catch (err) {
      setFormError(loadErrorText(describeLoadError(err)));
    } finally {
      setSaving(false);
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to manage its employer profile.</p>;
  }

  const p = profile;
  const facts = p ? [
    ["SIREN", p.siren, true],
    ["Legal entity", [p.legalName, p.legalForm].filter(Boolean).join(" · ")],
    ["Payroll contact", p.payrollContact],
    ["Address", p.address],
    ["IDCC", p.idcc ? `${p.idcc}` : IDCC_STATUSES[p.idccStatus] || "Not set"],
    ["Urssaf account", p.urssafAccount, true],
    ["DSN declarant", p.dsnDeclarant],
    ["Filing due date", dueDateClassLabel(p.filingDueDateClass)],
    ["Payment mandate", p.paymentMandateRef],
    ["PAS collector", p.pasCollectorIdentity, true],
    ["PAS CRM status", p.pasCrmStatus],
  ] : [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
            <Building2 size={15} className="text-primary" /> Employer profile (§11 panels A, C, D)
          </h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            Legal entity, collective agreement, Urssaf/DSN identity and DGFiP PAS collector.
          </p>
        </div>
        <button
          onClick={() => { setForm(toForm(p)); setFormError(""); }}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Pencil size={13} /> {p ? "Edit profile" : "Set up profile"}
        </button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading employer profile…</p>
      ) : error ? (
        <p className="py-8 text-center text-xs text-foreground-muted">
          <AlertTriangle size={14} className="inline mr-1" /> {loadErrorText(error)}
        </p>
      ) : p ? (
        <div className="rounded-xl border border-border bg-surface p-4">
          <dl className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-4 text-xs">
            {facts.map(([label, value, mono]) => (
              <div key={label}>
                <dt className="text-foreground-muted">{label}</dt>
                <dd className={`mt-0.5 font-medium text-foreground ${mono ? "font-mono" : ""}`}>{value || "—"}</dd>
              </div>
            ))}
          </dl>
          {p.idccStatus === "UNDER_REVIEW" && (
            <p className="mt-3 text-[11px] text-warning">IDCC is under review — France launch stays blocked until it is resolved (gate G3).</p>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted py-10 text-center">
          <p className="text-xs text-foreground-disabled">No France employer profile yet.</p>
          <p className="mt-1 text-[10px] text-foreground-disabled">Use “Set up profile” to record the SIREN identity.</p>
        </div>
      )}

      {form && (
        <Modal title={p ? "Edit France employer profile" : "Set up France employer profile"} onClose={() => setForm(null)} maxWidth="max-w-2xl">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {TEXT_FIELDS.map((f) => (
              <div key={f.key} className={f.wide ? "md:col-span-2" : ""}>
                <label className={labelClass}>{f.label}</label>
                <input
                  className={inputClass} value={form[f.key]} placeholder={f.placeholder}
                  inputMode={f.key === "siren" || f.key === "urssafAccount" ? "numeric" : "text"}
                  onChange={(e) => setForm((x) => ({ ...x, [f.key]: e.target.value }))}
                />
              </div>
            ))}
            <div>
              <label className={labelClass}>Collective agreement (IDCC) *</label>
              <select className={inputClass} value={form.idccStatus} onChange={(e) => setForm((x) => ({ ...x, idccStatus: e.target.value }))}>
                {Object.entries(IDCC_STATUSES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </div>
            <div>
              <label className={labelClass}>IDCC code</label>
              <input
                className={inputClass} value={form.idcc} placeholder="e.g. 1596"
                disabled={form.idccStatus !== "APPLICABLE"}
                onChange={(e) => setForm((x) => ({ ...x, idcc: e.target.value }))}
              />
            </div>
            <div>
              <label className={labelClass}>Filing due-date class</label>
              <select className={inputClass} value={form.filingDueDateClass} onChange={(e) => setForm((x) => ({ ...x, filingDueDateClass: e.target.value }))}>
                {DUE_CLASSES.map((c) => <option key={c} value={c}>{dueDateClassLabel(c)}</option>)}
              </select>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-foreground-disabled">
            M5 for ≥ 50 staff, M15 for &lt; 50, DEFERRED_M15 only under an authority-granted deferral. Readiness is computed
            from these records — see Overview &amp; Readiness.
          </p>
          {formError && <p className="mt-2 text-xs text-error">{formError}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setForm(null)} disabled={saving} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {saving ? "Saving…" : "Save profile"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
