import { useState, useEffect } from "react";
import { Layers, Loader2, Info } from "lucide-react";
import { fetchJurisdictionPack } from "../../../service/payrollService";

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

// Read-only mirror of the canonical JurisdictionPack Super Admin owns —
// this panel used to let an Org Admin call upsertJurisdictionPack and write
// straight into that same canonical row. There is no org-scoped copy of
// JurisdictionPack (unlike ContributionRate/TaxSlab's organization_id
// split), so that write path was editing Super Admin's actual master
// record. Display-only now: fetches whichever pack matches this org's own
// jurisdiction and renders it, nothing more.
//
// Fetches BOTH the country-level pack (state=null) and, if the org has its
// own state set, that state's pack — list_jurisdiction_packs (service.py)
// treats these as two genuinely separate queries ("state=None returns
// country-level packs only... does NOT also return every state-level pack
// under that country"), so a single call can only ever see one layer. For
// India specifically, a state pack is typically a narrow, single-purpose
// Professional Tax pack — showing IT as if it were "the" governing pack
// would hide the country-level one that actually configures PF/ESI/TDS.
// Country-level is always the primary display; a state pack (when one also
// exists) is surfaced as a small supplementary note instead of replacing it.
export default function PackMetadataPanel({ country, state }) {
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
      // Only worth noting when it's genuinely a SECOND pack alongside the
      // primary one being shown — if there's no country pack at all, the
      // state pack IS the primary (already reflected in `meta` above), not
      // a supplementary note about itself.
      setStatePackNote(countryPack && statePack ? { packId: statePack.packId, state } : null);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [country, state]);

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
        <span>Values below are strictly read-only and inherited from the <strong>Super Admin's</strong> jurisdiction pack configuration.</span>
      </div>

      <div className="rounded-[12px] bg-warning/10 border border-warning/20 px-4 py-3 mb-5">
        <p className="text-[12px] font-semibold text-warning">
          Note: Activation changes governance metadata only. Live payroll calculations must be updated via the Tax Engine Configuration.
        </p>
      </div>

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        <TextField label="Pack ID" placeholder="e.g. IN-PAYROLL-2026-V1" value={meta.packId} loading={loading} />
        <TextField label="Version" placeholder="e.g. 1.0" value={meta.version} loading={loading} />

        <div>
          <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 block">Pack Status</label>
          <select
            value={meta.status}
            disabled
            aria-readonly="true"
            className="w-full rounded-[12px] border border-border bg-surface-muted px-3.5 py-2.5 text-[13px] text-foreground-muted cursor-not-allowed focus:outline-none"
          >
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <TextField label="Effective From" type="date" value={meta.effectiveFrom} loading={loading} />
        <TextField label="Effective To" type="date" value={meta.effectiveTo} loading={loading} />
        <TextField label="Compliance Owner" placeholder="Named person or team" value={meta.complianceOwner} loading={loading} />
        <TextField label="Engineering Owner" placeholder="Named person or team" value={meta.engineeringOwner} loading={loading} />
        <div className="md:col-span-2 lg:col-span-3">
          <TextField
            label="Source References"
            placeholder="Official legal, tax, or government source(s) this pack is built from"
            value={meta.sourceReferences}
            loading={loading}
          />
        </div>
      </div>

      {statePackNote && (
        <div className="rounded-[12px] bg-info/5 border border-info/15 px-4 py-3 mt-5 text-[12px] text-foreground-muted">
          A state-specific pack (<strong>{statePackNote.packId}</strong>) is also configured for {statePackNote.state} — see Compliance for details.
        </div>
      )}

      <div className="flex items-center gap-2 mt-6 pt-5 border-t border-border">
        {loading && <Loader2 size={14} className="animate-spin text-foreground-muted" />}
        <p className="text-[13px] text-foreground-muted">
          {loading
            ? "Loading pack metadata..."
            : !loaded
              ? "No pack assigned for this jurisdiction yet."
              : "Loaded from Super Admin's configuration."}
        </p>
      </div>
    </div>
  );
}

// Read-only by construction — `disabled` (not `readOnly`) so it's excluded
// from focus/selection entirely, matching "user interaction... completely
// disabled" for every field in this panel. While `loading` is true there's
// nothing fetched yet, so the field shows a neutral placeholder rather than
// a stale/empty value flashing before the real one arrives.
function TextField({ label, value, placeholder, type = "text", loading }) {
  return (
    <div>
      <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1.5 block">{label}</label>
      <input
        type={type}
        value={loading ? "" : value}
        placeholder={loading ? "Loading…" : placeholder}
        disabled
        aria-readonly="true"
        readOnly
        className="w-full rounded-[12px] border border-border bg-surface-muted px-3.5 py-2.5 text-[13px] text-foreground-muted cursor-not-allowed placeholder:text-foreground-muted focus:outline-none"
      />
    </div>
  );
}
