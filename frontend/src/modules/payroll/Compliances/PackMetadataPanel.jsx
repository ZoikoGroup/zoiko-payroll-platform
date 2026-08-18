import { useState, useEffect } from "react";
import { Layers, Loader2, Info } from "lucide-react";
import {
  fetchJurisdictionPack,
  upsertJurisdictionPack,
} from "../../../service/payrollService";

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

export default function PackMetadataPanel({ country, state, addToast }) {
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
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const update = (field, value) => setMeta((prev) => ({ ...prev, [field]: value }));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchJurisdictionPack(country, state).then((pack) => {
      if (cancelled) return;
      if (pack) {
        setMeta({
          packId: pack.packId || "",
          version: pack.version || "1.0",
          status: pack.status || "Draft",
          effectiveFrom: pack.effectiveFrom || "",
          effectiveTo: pack.effectiveTo || "",
          complianceOwner: pack.complianceOwner || "",
          engineeringOwner: pack.engineeringOwner || "",
          sourceReferences: pack.sourceReferences || "",
        });
        setLoaded(true);
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [country, state]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await upsertJurisdictionPack({
        packId: meta.packId,
        jurisdictionCountry: country,
        jurisdictionState: state || null,
        version: meta.version,
        status: meta.status,
        effectiveFrom: meta.effectiveFrom || null,
        effectiveTo: meta.effectiveTo || null,
        complianceOwner: meta.complianceOwner,
        engineeringOwner: meta.engineeringOwner,
        sourceReferences: meta.sourceReferences,
      });
      addToast?.("Pack metadata saved successfully.", "success");
    } catch {
      addToast?.("Failed to save pack metadata.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center gap-2 mb-5">
        <div className="p-1.5 rounded-[10px] bg-category-teal/10">
          <Layers size={16} className="text-category-teal" />
        </div>
        <h3 className="text-[15px] font-bold text-foreground">Pack Identity & Metadata</h3>
      </div>

      <div className="rounded-[12px] bg-info/5 border border-info/15 px-4 py-3 mb-5 text-[12px] text-foreground-muted flex items-center gap-2">
        <Info size={14} className="text-info shrink-0" />
        <span>Values below are inherited from the <strong>Super Admin's</strong> jurisdiction pack configuration. You can overwrite fields where permitted.</span>
      </div>

      <div className="rounded-[12px] bg-warning/10 border border-warning/20 px-4 py-3 mb-5">
        <p className="text-[12px] font-semibold text-warning">
          Note: Activation changes governance metadata only. Live payroll calculations must be updated via the Tax Engine Configuration.
        </p>
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        <TextField label="Pack ID" placeholder="e.g. IN-PAYROLL-2026-V1" value={meta.packId} onChange={(v) => update("packId", v)} />
        <TextField label="Version" placeholder="e.g. 1.0" value={meta.version} onChange={(v) => update("version", v)} />

        <div>
          <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 block">Pack Status</label>
          <select
            value={meta.status}
            onChange={(e) => update("status", e.target.value)}
            className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
          >
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <TextField label="Effective From" type="date" value={meta.effectiveFrom} onChange={(v) => update("effectiveFrom", v)} />
        <TextField label="Effective To" type="date" value={meta.effectiveTo} onChange={(v) => update("effectiveTo", v)} />
        <TextField label="Compliance Owner" placeholder="Named person or team" value={meta.complianceOwner} onChange={(v) => update("complianceOwner", v)} />
        <TextField label="Engineering Owner" placeholder="Named person or team" value={meta.engineeringOwner} onChange={(v) => update("engineeringOwner", v)} />
        <div className="md:col-span-2 lg:col-span-3">
          <TextField
            label="Source References"
            placeholder="Official legal, tax, or government source(s) this pack is built from"
            value={meta.sourceReferences}
            onChange={(v) => update("sourceReferences", v)}
          />
        </div>
      </div>

      <div className="flex items-center justify-between mt-6 pt-5 border-t border-border">
        <p className="text-[13px] text-foreground-muted">
          {loading
            ? "Loading pack metadata..."
            : !loaded
              ? "No existing pack metadata — filling defaults."
              : "Loaded from server."}
        </p>
        <button
          onClick={handleSave}
          disabled={saving || loading}
          className="rounded-[12px] bg-primary px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-50 flex items-center gap-2"
        >
          {saving && <Loader2 size={14} className="animate-spin" />}
          {saving ? "Saving..." : "Save Pack Metadata"}
        </button>
      </div>
    </div>
  );
}

function TextField({ label, value, onChange, placeholder, type = "text" }) {
  return (
    <div>
      <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 block">{label}</label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
      />
    </div>
  );
}
