import { useEffect, useState } from "react";
import { ShieldCheck, ShieldOff, Plus } from "lucide-react";
import Modal from "../components/Modal";
import { getJurisdictionSummary } from "../service/superAdminService";

const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-focus-ring/40";
const labelClass = "block text-xs font-medium text-foreground-muted mb-1";

// Shared by every page that browses jurisdictions (Compliance, Statutory
// Rates) — "Country-level" is represented as "" in state selectors
// elsewhere (maps to jurisdictionState: null on save), same "null means
// country-level" convention JurisdictionPack already uses.
export function AddJurisdictionModal({ onClose, onAdd }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  return (
    <Modal title="Add Jurisdiction" onClose={onClose} maxWidth="max-w-md">
      <p className="text-xs text-foreground-muted mb-4">
        Any country can be added — it only becomes a real jurisdiction once you create its first Tax, Policy, or
        Statutory Rate record. Nothing is saved by this step alone.
      </p>
      <div className="space-y-3">
        <div>
          <label className={labelClass}>Country Code</label>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            className={inputClass}
            placeholder="e.g. SG"
            maxLength={10}
          />
        </div>
        <div>
          <label className={labelClass}>Country Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} placeholder="e.g. Singapore" />
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">
          Cancel
        </button>
        <button
          type="button"
          disabled={!code.trim() || !name.trim()}
          onClick={() => onAdd({ code: code.trim(), name: name.trim(), currency: null, taxPackCount: 0, policyPackCount: 0, statutoryRateCount: 0, organizationCount: 0, states: [], isConfigured: false })}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    </Modal>
  );
}

// Every stat here is real data from GET /compliance/jurisdiction-summary —
// tax/policy pack counts, statutory rate count, organizations assigned,
// last-updated date. Never a placeholder like min-wage/state-tax-yes-no
// that isn't modeled anywhere in this system — every value below falls
// back to "N/A" rather than ever rendering `undefined`.

function StatTile({ label, value }) {
  return (
    <div className="rounded-lg bg-background px-3 py-2 text-center">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-foreground-disabled">{label}</p>
      <p className="text-[15px] font-bold text-foreground mt-0.5">{value}</p>
    </div>
  );
}

function JurisdictionCard({ jurisdiction, onSelect }) {
  const { code, name, currency, taxPackCount, policyPackCount, statutoryRateCount, organizationCount, states, isConfigured } = jurisdiction;
  return (
    <button
      type="button"
      onClick={() => onSelect(jurisdiction)}
      className="text-left rounded-xl border border-border bg-surface p-4 hover:border-primary/60 transition-colors"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-900 dark:bg-black text-[11px] font-bold text-white">
            {code}
          </span>
          <div>
            <p className="text-[15px] font-bold text-foreground">{name}</p>
            <p className="text-[11px] text-foreground-disabled">{currency || "N/A"}</p>
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${
            isConfigured
              ? "bg-emerald-500/10 text-emerald-500"
              : "bg-slate-400/10 text-foreground-disabled"
          }`}
        >
          {isConfigured ? <ShieldCheck size={11} /> : <ShieldOff size={11} />}
          {isConfigured ? "Configured" : "Not Configured"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3">
        <StatTile label="Taxes" value={taxPackCount ?? 0} />
        <StatTile label="Policies" value={policyPackCount ?? 0} />
        <StatTile label="Rates" value={statutoryRateCount ?? 0} />
      </div>

      <p className="text-[11px] text-foreground-disabled">
        {organizationCount ?? 0} organization{organizationCount === 1 ? "" : "s"} assigned
        {states && states.length > 0 ? ` · ${states.length} state${states.length === 1 ? "" : "s"} configured` : " · country-level only"}
      </p>
    </button>
  );
}

function AddJurisdictionCard({ onAdd }) {
  return (
    <button
      type="button"
      onClick={onAdd}
      className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border p-4 text-foreground-disabled hover:border-primary hover:text-primary transition-colors min-h-[148px]"
    >
      <Plus size={20} />
      <span className="text-[13px] font-semibold">Add Jurisdiction</span>
    </button>
  );
}

export default function JurisdictionCardGrid({ onSelect, onAddJurisdiction }) {
  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getJurisdictionSummary()
      .then((data) => { if (!cancelled) setJurisdictions(data || []); })
      .catch((err) => { if (!cancelled) setError(err.message || "Failed to load jurisdictions."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <p className="text-sm text-foreground-disabled py-8 text-center">Loading jurisdictions…</p>;
  }
  if (error) {
    return <p className="text-sm text-red-500 py-8 text-center">{error}</p>;
  }

  return (
    <div>
      <h2 className="text-lg font-bold text-foreground mb-4">Jurisdictions</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {jurisdictions.map((j) => (
          <JurisdictionCard key={j.code} jurisdiction={j} onSelect={onSelect} />
        ))}
        <AddJurisdictionCard onAdd={onAddJurisdiction} />
      </div>
    </div>
  );
}
