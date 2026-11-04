import { useState, useEffect } from "react";
import { Layers, Loader2, Info, Save, Edit, X } from "lucide-react";
import { useToast } from "../ToastContext";
import { fetchJurisdictionPack } from "../../../service/payrollService";
import { upsertCompliancePolicy } from "../../../service/superAdminService";

const STATUS_OPTIONS = ["Draft", "In Review", "QA", "Approved", "Active", "Deprecated", "Retired"];

const STATUS_COLORS = {
  Draft: "bg-foreground-muted/10 text-foreground-muted",
  "In Review": "bg-info/10 text-info",
  QA: "bg-warning/10 text-warning",
  Approved: "bg-primary/10 text-primary",
  Active: "bg-primary/10 text-primary",
  Deprecated: "bg-error/10 text-error",
  Retired: "bg-foreground-muted/10 text-foreground-muted",
};

// Pack metadata for a jurisdiction. Editable by Org Admin — changes write back
// to the canonical JurisdictionPack via upsertCompliancePolicy, which affects
// all organizations sharing this pack. Use with care.
export default function PackMetadataPanel({ country, state }) {
  const { addToast } = useToast() || {};
  const [meta, setMeta] = useState({
    packId: "",
    version: "1.0",
    status: "Draft",
    effectiveFrom: "",
    effectiveTo: "",
    complianceOwner: "",
    engineeringOwner: "",
    sourceReferences: "",
  });

  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [statePackNote, setStatePackNote] = useState(null); // { packId } | null
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchJurisdictionPack(country, null),
      state ? fetchJurisdictionPack(country, state) : Promise.resolve(null),
    ]).then(([countryPack, statePack]) => {
      if (cancelled) return;
      const primary = countryPack || statePack;
      if (primary) {
        setMeta({
          packId: primary.packId || "",
          version: primary.version || "1.0",
          status: primary.status || "Draft",
          effectiveFrom: primary.effectiveFrom || "",
          effectiveTo: primary.effectiveTo || "",
          complianceOwner: primary.complianceOwner || "",
          engineeringOwner: primary.engineeringOwner || "",
          sourceReferences: primary.sourceReferences || "",
        });
        setLoaded(true);
      }
      setStatePackNote(countryPack && statePack ? { packId: statePack.packId, state } : null);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [country, state]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await upsertCompliancePolicy({
        packId: meta.packId,
        jurisdictionCountry: country,
        jurisdictionState: state || null,
        packType: "tax",
        version: meta.version,
        status: meta.status,
        effectiveFrom: meta.effectiveFrom || undefined,
        effectiveTo: meta.effectiveTo || undefined,
        taxYear: "",
        taxRegime: "",
        currency: "",
        regulatoryAuthority: "",
        complianceCategory: "",
        complianceOwner: meta.complianceOwner || "",
        engineeringOwner: meta.engineeringOwner || "",
        nextReviewDate: "",
        sourceReferences: meta.sourceReferences || "",
        changeSummary: "",
      });
      setEditing(false);
      addToast?.("Pack metadata updated.", "success");
    } catch (err) {
      addToast?.(err.message || "Failed to update pack metadata.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between gap-2 mb-5">
        <div className="p-1.5 rounded-[10px] bg-category-teal/10">
          <Layers size={16} className="text-category-teal" />
        </div>
        <div>
          <h3 className="text-[15px] font-bold text-foreground">Pack Identity & Metadata</h3>
          {editing && (
            <span className="inline-flex items-center gap-1 mt-0.5 rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-bold text-success">
              Editing &mdash; changes apply to all orgs using this pack
            </span>
          )}
        </div>
        {!editing ? (
          <button
            onClick={() => setEditing(true)}
            className="rounded-[10px] px-3 py-1.5 text-[13px] font-bold text-foreground-secondary hover:bg-surface-muted transition-colors"
          >
            <Edit size={14} /> Edit
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => setEditing(false)}
              className="rounded-[10px] p-1.5 text-foreground-muted hover:bg-surface-muted transition-colors"
              aria-label="Cancel"
            >
              <X size={14} />
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-[10px] px-3 py-1.5 text-[13px] font-bold text-white bg-primary hover:bg-primary-hover disabled:opacity-60"
            >
              {saving ? "Saving&hellip;" : "Save"}
            </button>
          </div>
        )}
      </div>

      {!editing && (
        <div className="rounded-[12px] bg-info/5 border border-info/15 px-4 py-3 mb-5 text-[12px] text-foreground-muted flex items-center gap-2">
          <Info size={14} className="text-info shrink-0" />
          <span>Values below are inherited from the <strong>Super Admin&apos;s</strong> jurisdiction pack configuration.</span>
        </div>
      )}

      {!editing && (
        <div className="rounded-[12px] bg-warning/10 border border-warning/20 px-4 py-3 mb-5">
          <p className="text-[12px] font-semibold text-warning">
            Note: Activation changes governance metadata only. Live payroll calculations must be updated via the Tax Engine Configuration.
          </p>
        </div>
      )}

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        <TextField label="Pack ID" placeholder="e.g. IN-PAYROLL-2026-V1" value={meta.packId} onChange={(e) => setMeta({ ...meta, packId: e.target.value })} loading={loading} disabled={!editing} />
        <TextField label="Version" placeholder="e.g. 1.0" value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })} loading={loading} disabled={!editing} />

        <div>
          <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 block">Pack Status</label>
          <select
            value={meta.status}
            onChange={(e) => setMeta({ ...meta, status: e.target.value })}
            disabled={!editing}
            className="w-full rounded-[12px] border border-border px-3.5 py-2.5 text-[13px] font-bold transition-colors focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          >
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <TextField label="Effective From" type="date" value={meta.effectiveFrom} onChange={(e) => setMeta({ ...meta, effectiveFrom: e.target.value })} loading={loading} disabled={!editing} />
        <TextField label="Effective To" type="date" value={meta.effectiveTo} onChange={(e) => setMeta({ ...meta, effectiveTo: e.target.value })} loading={loading} disabled={!editing} />
        <TextField label="Compliance Owner" placeholder="Named person or team" value={meta.complianceOwner} onChange={(e) => setMeta({ ...meta, complianceOwner: e.target.value })} loading={loading} disabled={!editing} />
        <TextField label="Engineering Owner" placeholder="Named person or team" value={meta.engineeringOwner} onChange={(e) => setMeta({ ...meta, engineeringOwner: e.target.value })} loading={loading} disabled={!editing} />
        <div className="md:col-span-2 lg:col-span-3">
          <TextField
            label="Source References"
            placeholder="Official legal, tax, or government source(s) this pack is built from"
            value={meta.sourceReferences}
            onChange={(e) => setMeta({ ...meta, sourceReferences: e.target.value })}
            loading={loading}
            disabled={!editing}
          />
        </div>
      </div>

      {statePackNote && (
        <div className="rounded-[12px] bg-info/5 border border-info/15 px-4 py-3 mt-5 text-[12px] text-foreground-muted">
          A state-specific pack (<strong>{statePackNote.packId}</strong>) is also configured for {statePackNote.state} — see Compliance for details.
        </div>
      )}

      <div className="flex items-center gap-2 mt-6 pt-5 border-t border-border">
        {!editing && (
          <>
            {loading && <Loader2 size={14} className="animate-spin text-foreground-muted" />}
            <p className="text-[13px] text-foreground-muted">
              {loading
                ? "Loading pack metadata..."
                : !loaded
                  ? "No pack assigned for this jurisdiction yet."
                  : "Loaded from Super Admin's configuration."}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

// TextField supports editing when not disabled. While loading, shows a neutral placeholder.
function TextField({ label, value, placeholder, type = "text", loading, disabled, onChange }) {
  return (
    <div>
      <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 block">{label}</label>
      <input
        type={type}
        value={loading ? "" : value}
        placeholder={loading ? "Loading&hellip;" : placeholder}
        disabled={disabled}
        aria-readonly={disabled}
        readOnly={disabled}
        onChange={onChange}
        className={`w-full rounded-[12px] border border-border px-3.5 py-2.5 text-[13px] transition-colors duration-200 ${
          disabled
            ? "bg-surface-muted text-foreground-muted cursor-not-allowed placeholder:text-foreground-muted"
            : "bg-surface text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        }`}
      />
    </div>
  );
}
