import { useState, useEffect, useCallback } from "react";
import { Pencil, Landmark } from "lucide-react";
import Modal from "../Modal";
import StatusPill from "../StatusPill";
import { useToast } from "../../context/ToastContext";
import {
  getComplianceJurisdictions, getCompliancePolicies,
  getCanonicalContributionRates, upsertCanonicalContributionRate,
  getCanonicalTaxSlabs,
} from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

const STATUS_PILL_MAP = { Active: "active", Draft: "pending", "In Review": "pending", QA: "pending", Approved: "pending", Deprecated: "inactive", Retired: "suspended" };

// The one shared Statutory Rates surface every per-country page renders —
// same role as JurisdictionLayout plays for Compliance, but deliberately
// narrower: Statutory Rates is "a simpler, numeric-values-only view over
// the exact same canonical ContributionRate/TaxSlab data Compliance
// manages" (its own original docstring, preserved below) — no pack
// creation, no status changes, no versions/organizations/audit, no
// renaming a rate's component_key/label. `country` is fixed per page
// (chosen by routing), matching JurisdictionLayout's convention exactly.
export default function StatutoryRatesLayout({ country, countryName, initialState = "", onStateChange }) {
  const [jurisdictions, setJurisdictions] = useState([]);
  const [state, setStateRaw] = useState(initialState || "");
  const [packs, setPacks] = useState([]);
  const [selectedPackId, setSelectedPackId] = useState(null);
  const [rates, setRates] = useState([]);
  const [slabs, setSlabs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editingRate, setEditingRate] = useState(null);

  function setState(next) {
    setStateRaw(next);
    onStateChange?.(next);
  }

  useEffect(() => { getComplianceJurisdictions().then(setJurisdictions); }, []);

  const selectedJurisdiction = jurisdictions.find((j) => j.code === country);

  const load = useCallback(() => {
    if (!country) return;
    setLoading(true);
    getCompliancePolicies({ country, state: state || undefined, packType: "tax" })
      .then((rows) => {
        setPacks(rows);
        const active = rows.find((p) => p.status === "Active");
        setSelectedPackId((active || rows[0])?.id ?? null);
      })
      .finally(() => setLoading(false));
  }, [country, state]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selectedPackId) { setRates([]); setSlabs([]); return; }
    getCanonicalContributionRates({ jurisdictionPackId: selectedPackId }).then(setRates);
    getCanonicalTaxSlabs({ jurisdictionPackId: selectedPackId }).then(setSlabs);
  }, [selectedPackId]);

  const selectedPack = packs.find((p) => p.id === selectedPackId);

  function reloadRates() {
    if (selectedPackId) getCanonicalContributionRates({ jurisdictionPackId: selectedPackId }).then(setRates);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-[12px] bg-primary/10 flex items-center justify-center">
          <Landmark size={20} className="text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-foreground">{countryName} Statutory Rates</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Configure statutory contribution rates used by the payroll engine. Creating tax packs or changing their status happens in Compliance.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select className={inputClass + " w-auto min-w-[160px]"} value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Country-level (no state)</option>
          {/* States whose only configured tax data is Professional Tax
              brackets are excluded here — PT is managed in Compliance
              only, not Statutory Rates. */}
          {(selectedJurisdiction?.states || [])
            .filter((s) => !(selectedJurisdiction?.ptOnlyStates || []).includes(s))
            .map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {packs.length > 0 && (
          <select className={inputClass + " w-auto min-w-[220px]"} value={selectedPackId || ""} onChange={(e) => setSelectedPackId(Number(e.target.value))}>
            {packs.map((p) => <option key={p.id} value={p.id}>{p.packId} (v{p.version}, {p.status})</option>)}
          </select>
        )}
      </div>

      <div className="bg-surface border border-border rounded-[18px] p-5">
        <div className="mb-4 flex items-center justify-between flex-wrap gap-2">
          <h3 className="text-sm font-bold text-foreground">
            Contribution Rates {selectedPack && <StatusPill status={STATUS_PILL_MAP[selectedPack.status] || "pending"} label={selectedPack.status} />}
          </h3>
        </div>

        {loading ? (
          <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
        ) : !selectedPack ? (
          <p className="py-8 text-center text-xs text-foreground-disabled">No tax pack configured for this jurisdiction yet — create one in Compliance.</p>
        ) : rates.length === 0 ? (
          <p className="py-8 text-center text-xs text-foreground-disabled">No contribution rates configured for this pack yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-xs min-w-[720px]">
              <thead className="bg-background text-left text-foreground-muted">
                <tr>
                  <th className="px-3 py-2">Component</th>
                  <th className="px-3 py-2">State</th>
                  <th className="px-3 py-2">Employee</th>
                  <th className="px-3 py-2">Employer</th>
                  <th className="px-3 py-2">Flat Amount</th>
                  <th className="px-3 py-2 w-16"></th>
                </tr>
              </thead>
              <tbody>
                {rates.map((r) => (
                  <tr key={r.id} className="border-t border-border-light hover:bg-surface-muted/40">
                    <td className="px-3 py-2.5">
                      <p className="font-semibold text-foreground">{r.label}</p>
                      <p className="font-mono text-[10px] text-foreground-disabled">{r.componentKey}</p>
                    </td>
                    <td className="px-3 py-2.5 text-foreground-secondary">{r.jurisdictionState || "—"}</td>
                    <td className="px-3 py-2.5 text-foreground-secondary">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                    <td className="px-3 py-2.5 text-foreground-secondary">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                    <td className="px-3 py-2.5 text-foreground-secondary">{r.flatAmount != null ? r.flatAmount : "—"}</td>
                    <td className="px-3 py-2.5">
                      <button type="button" onClick={() => setEditingRate(r)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted">
                        <Pencil size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {slabs.length > 0 && (
        <div className="bg-surface border border-border rounded-[18px] p-5">
          <h3 className="mb-4 text-sm font-bold text-foreground">Tax Slabs</h3>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-xs">
              <thead className="bg-background text-left text-foreground-muted">
                <tr><th className="px-3 py-2">Min</th><th className="px-3 py-2">Max</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">Label</th><th className="px-3 py-2">State</th></tr>
              </thead>
              <tbody>
                {slabs.map((s) => (
                  <tr key={s.id} className="border-t border-border-light">
                    <td className="px-3 py-2.5">{s.minAmount}</td>
                    <td className="px-3 py-2.5">{s.maxAmount ?? "and above"}</td>
                    <td className="px-3 py-2.5 font-semibold text-foreground">{s.ratePct}%</td>
                    <td className="px-3 py-2.5 text-foreground-secondary">{s.rateLabel}</td>
                    <td className="px-3 py-2.5 text-foreground-secondary">{s.jurisdictionState || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-foreground-disabled">Editing tax brackets happens in Compliance's Tax Slabs tab.</p>
        </div>
      )}

      {editingRate && (
        <QuickEditRateModal
          rate={editingRate} pack={selectedPack}
          onClose={() => setEditingRate(null)}
          onSaved={() => { setEditingRate(null); reloadRates(); }}
        />
      )}
    </div>
  );
}

// Deliberately narrower than Compliance's full RateFormModal — no
// componentKey/label/state editing here, matching this page's own
// "quick-edit the numbers, not the identity" purpose.
function QuickEditRateModal({ rate, pack, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [employeeSharePct, setEmployeeSharePct] = useState(rate.employeeRatePct ?? "");
  const [employerSharePct, setEmployerSharePct] = useState(rate.employerRatePct ?? "");
  const [flatAmount, setFlatAmount] = useState(rate.flatAmount ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: rate.id, jurisdictionPackId: rate.jurisdictionPackId, jurisdictionCountry: rate.jurisdictionCountry,
        jurisdictionState: rate.jurisdictionState, taxRegime: rate.taxRegime,
        componentKey: rate.componentKey, label: rate.label,
        employeeSharePct: employeeSharePct === "" ? null : employeeSharePct,
        employerSharePct: employerSharePct === "" ? null : employerSharePct,
        flatAmount: flatAmount === "" ? null : flatAmount,
        sortOrder: rate.sortOrder,
      });
      addToast?.("Rate updated.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to update rate.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Edit "${rate.label}"`} onClose={onClose} maxWidth="max-w-sm">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Employee Rate %</label><input className={inputClass} value={employeeSharePct} onChange={(e) => setEmployeeSharePct(e.target.value)} /></div>
        <div><label className={labelClass}>Employer Rate %</label><input className={inputClass} value={employerSharePct} onChange={(e) => setEmployerSharePct(e.target.value)} /></div>
        <div className="col-span-2"><label className={labelClass}>Flat Amount</label><input className={inputClass} value={flatAmount} onChange={(e) => setFlatAmount(e.target.value)} /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save Changes"}</button>
      </div>
    </Modal>
  );
}
