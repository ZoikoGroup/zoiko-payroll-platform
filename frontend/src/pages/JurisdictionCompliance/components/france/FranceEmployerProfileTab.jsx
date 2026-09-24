import { useEffect, useState } from "react";
import { Building2, CheckCircle2, AlertTriangle } from "lucide-react";
import { getFranceEmployerProfile, upsertFranceEmployerProfile } from "../../../../service/superAdminService";
import { describeLoadError } from "../../../../service/errorClassification";
import { dueDateClassLabel, readinessLabel, readinessChip } from "./franceOverviewSummaries";

const DUE_CLASSES = ["M15", "M5", "DEFERRED_M15"];
const READINESS_STATUSES = ["NOT_CONFIGURED", "NOT_READY", "READY", "LIVE"];

const BLANK = {
  siren: "",
  legalName: "",
  legalForm: "",
  idcc: "",
  urssafAccount: "",
  dsnDeclarant: "",
  filingDueDateClass: "M15",
  paymentMandateRef: "",
  pasCollectorIdentity: "",
  readinessStatus: "NOT_CONFIGURED",
};

export default function FranceEmployerProfileTab({ organizationId }) {
  const [state, setState] = useState({ loading: true, profile: null, error: null });
  const [form, setForm] = useState(BLANK);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    if (!organizationId) {
      setState({ loading: false, profile: null, error: null });
      return;
    }
    let cancelled = false;
    setState({ loading: true, profile: null, error: null });
    getFranceEmployerProfile({ organizationId })
      .then((p) => {
        if (cancelled) return;
        setState({ loading: false, profile: p || null, error: null });
        setForm({
          siren: p?.siren || "",
          legalName: p?.legalName || "",
          legalForm: p?.legalForm || "",
          idcc: p?.idcc || "",
          urssafAccount: p?.urssafAccount || "",
          dsnDeclarant: p?.dsnDeclarant || "",
          filingDueDateClass: p?.filingDueDateClass || "M15",
          paymentMandateRef: p?.paymentMandateRef || "",
          pasCollectorIdentity: p?.pasCollectorIdentity || "",
          readinessStatus: p?.readinessStatus || "NOT_CONFIGURED",
        });
      })
      .catch((err) => {
        if (!cancelled) setState({ loading: false, error: describeLoadError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [organizationId]);

  function setField(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    setDirty(true);
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await upsertFranceEmployerProfile(form, { organizationId });
      setState((s) => ({ ...s, profile: updated }));
      setDirty(false);
      setSaved(true);
    } catch (err) {
      setSaveError(describeLoadError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-sm text-foreground-muted">Select an organization to manage its France employer profile.</p>;
  }
  if (state.loading) {
    return <p className="py-10 text-sm text-foreground-disabled">Loading employer profile…</p>;
  }
  if (state.error && !state.profile) {
    return (
      <p className="py-10 text-sm text-foreground-muted">
        <AlertTriangle size={14} className="inline mr-1" />
        {state.error}
      </p>
    );
  }

  const inputs = [
    { key: "siren", label: "SIREN (9 digits)", placeholder: "552100554", required: true },
    { key: "legalName", label: "Legal name", placeholder: "ACME SAS" },
    { key: "legalForm", label: "Legal form", placeholder: "SAS / SARL / SA / ..." },
    { key: "idcc", label: "IDCC (convention collective)", placeholder: "1596, or 'unknown under review'" },
    { key: "urssafAccount", label: "URSSAF account", placeholder: "7500000000001" },
    { key: "dsnDeclarant", label: "DSN declarant", placeholder: "ACME" },
    { key: "paymentMandateRef", label: "Payment mandate ref", placeholder: "SEPA mandate reference" },
    { key: "pasCollectorIdentity", label: "PAS collector identity", placeholder: "DGFiP collector id (optional)" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Building2 size={16} className="text-primary" />
        <h2 className="text-sm font-bold text-foreground">France employer profile (FR A11 panels C/D)</h2>
      </div>

      {state.profile ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
            <div>
              <p className="text-foreground-muted">SIREN</p>
              <p className="mt-0.5 font-bold text-foreground">{state.profile.siren}</p>
            </div>
            <div>
              <p className="text-foreground-muted">Filing due-date class</p>
              <p className="mt-0.5 font-bold text-foreground">{dueDateClassLabel(state.profile.filingDueDateClass)}</p>
            </div>
            <div>
              <p className="text-foreground-muted">Readiness</p>
              <p className="mt-0.5">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${readinessChip(state.profile.readinessStatus)}`}>
                  {readinessLabel(state.profile.readinessStatus)}
                </span>
              </p>
            </div>
            <div>
              <p className="text-foreground-muted">PAS CRM status</p>
              <p className="mt-0.5 font-bold text-foreground">{state.profile.pasCrmStatus || "—"}</p>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-xs text-foreground-muted">
          No profile yet — SIREN identity is authority-held (write-once facts are not payload-editable upstream).
        </p>
      )}

      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {inputs.map((i) => (
            <label key={i.key} className="block">
              <span className="text-xs font-semibold text-foreground-muted">
                {i.label}
                {i.required ? " *" : ""}
              </span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form[i.key]}
                placeholder={i.placeholder}
                inputMode={i.key === "siren" || i.key === "urssafAccount" ? "numeric" : "text"}
                onChange={(e) => setField(i.key, e.target.value)}
              />
            </label>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Filing due-date class</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.filingDueDateClass}
              onChange={(e) => setField("filingDueDateClass", e.target.value)}
            >
              {DUE_CLASSES.map((c) => (
                <option key={c} value={c}>
                  {dueDateClassLabel(c)}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Readiness status (evidence-gate H)</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.readinessStatus}
              onChange={(e) => setField("readinessStatus", e.target.value)}
            >
              {READINESS_STATUSES.map((r) => (
                <option key={r} value={r}>
                  {readinessLabel(r)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={save}
            disabled={saving || !form.siren || !dirty}
            className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
          >
            {saving ? "Saving…" : dirty ? "Save profile" : "Profile saved"}
          </button>
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-600">
              <CheckCircle2 size={13} /> Saved
            </span>
          )}
          {saveError && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600">
              <AlertTriangle size={13} /> {saveError}
            </span>
          )}
        </div>
        <p className="mt-2 text-[11px] text-foreground-disabled">
          SIREN must be exactly 9 digits. IDCC is mandatory or explicitly "unknown under review" (FR-035) — never silently
          defaulted to the Code du travail floor.
        </p>
      </div>
    </div>
  );
}