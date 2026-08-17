import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Landmark, Building2, ArrowLeft, ArrowRight } from "lucide-react";

import { getOrganizationContributionRates, getActiveTaxConfiguration } from "../service/superAdminService";
import { getStatesForCountryCode } from "../utils/registrationRegions";
import JurisdictionCardGrid, { AddJurisdictionModal } from "./JurisdictionCardGrid";

export default function StatutoryRatesPage() {
  const navigate = useNavigate();

  // null = jurisdiction card grid (same shared component/data Compliance
  // uses); set = drilled into one country (+ optional state) — every fetch
  // below scopes to this jurisdiction, so switching it changes the whole
  // context, same as Compliance.
  const [selectedJurisdiction, setSelectedJurisdiction] = useState(null);
  const [selectedState, setSelectedState] = useState(""); // "" = country-level
  const [showAddJurisdiction, setShowAddJurisdiction] = useState(false);

  // { pack, rates, slabs } from the canonical tax pack currently Active
  // for this jurisdiction — pack is null when nothing has been configured
  // yet. This is a read-only mirror of the exact data Compliance's Rates
  // editor writes to, not a separate dataset — see getActiveTaxConfiguration.
  const [activeConfig, setActiveConfig] = useState({ pack: null, rates: [], slabs: [] });
  const [orgRates, setOrgRates] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const countryCode = selectedJurisdiction?.code || "";
  const availableStates = selectedJurisdiction ? getStatesForCountryCode(countryCode) : [];

  const load = useCallback(() => {
    if (!selectedJurisdiction) return;
    setLoading(true);
    setError("");
    Promise.all([
      // Omitting `state` here means "country-level only" on the backend
      // (not "every state blended together") — the same isolation
      // Compliance's Taxes/Policies tabs already enforce.
      getActiveTaxConfiguration({ country: countryCode, state: selectedState || undefined }),
      getOrganizationContributionRates({ country: countryCode }),
    ])
      .then(([configRes, orgRes]) => {
        setActiveConfig(configRes);
        setOrgRates(orgRes);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [selectedJurisdiction, countryCode, selectedState]);

  useEffect(() => { load(); }, [load]);

  function handleSelectJurisdiction(jurisdiction) {
    setSelectedJurisdiction(jurisdiction);
    setSelectedState("");
  }

  function handleBackToGrid() {
    setSelectedJurisdiction(null);
    setActiveConfig({ pack: null, rates: [], slabs: [] });
    setOrgRates([]);
  }

  // Editing canonical rates happens in exactly one place — Compliance's
  // Rates editor — so this just lands the admin on the right jurisdiction/
  // tab there instead of duplicating an editor here.
  function goToComplianceEdit() {
    navigate("/super-admin/compliance", {
      state: { restoreJurisdiction: selectedJurisdiction, restoreState: selectedState, tab: "taxes" },
    });
  }

  if (!selectedJurisdiction) {
    return (
      <div>
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-foreground">Statutory Rates</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Pick a jurisdiction to see its currently-active platform rates and every organization's actual configured
            contribution rates — the same jurisdictions as Compliance, isolated the same way.
          </p>
        </div>
        <JurisdictionCardGrid onSelect={handleSelectJurisdiction} onAddJurisdiction={() => setShowAddJurisdiction(true)} />
        {showAddJurisdiction && (
          <AddJurisdictionModal
            onClose={() => setShowAddJurisdiction(false)}
            onAdd={(j) => { setShowAddJurisdiction(false); handleSelectJurisdiction(j); }}
          />
        )}
      </div>
    );
  }

  const { pack, rates } = activeConfig;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <button
            onClick={handleBackToGrid}
            className="flex items-center gap-1.5 text-xs font-medium text-foreground-muted hover:text-primary mb-2"
          >
            <ArrowLeft size={13} /> All Jurisdictions
          </button>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-900 dark:bg-black text-[10px] font-bold text-white">
              {countryCode}
            </span>
            {selectedJurisdiction.name}
            {selectedState && <span className="text-foreground-disabled font-normal">/ {selectedState}</span>}
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            {selectedJurisdiction.currency || "N/A"} · Read-only view of{" "}
            {selectedState || selectedJurisdiction.name}'s currently active tax configuration.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {availableStates.length > 0 && (
            <select
              value={selectedState}
              onChange={(e) => setSelectedState(e.target.value)}
              className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
            >
              <option value="">Country-level (no state)</option>
              {availableStates.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-foreground-secondary">
          Platform Rates {pack ? `— ${pack.packId} v${pack.version}` : ""}
        </h2>
        <button
          onClick={goToComplianceEdit}
          className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary-hover"
        >
          Edit in Compliance <ArrowRight size={13} />
        </button>
      </div>
      <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden mb-8">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Key</th>
              <th className="px-4 py-3">Label</th>
              <th className="px-4 py-3">Employee %</th>
              <th className="px-4 py-3">Employer %</th>
              <th className="px-4 py-3">Flat Amount</th>
            </tr>
          </thead>
          <tbody>
            {rates.map((r) => (
              <tr key={r.id} className="border-t border-border-light hover:bg-slate-50/60 dark:hover:bg-white/5 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-foreground-secondary">{r.componentKey}</td>
                <td className="px-4 py-3 font-medium text-foreground">{r.label}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.flatAmount != null ? r.flatAmount : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !pack && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Landmark size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">
              No active tax pack configured for {selectedJurisdiction.name}{selectedState ? ` / ${selectedState}` : ""} yet
              — configure one in Compliance.
            </p>
          </div>
        )}
        {!loading && pack && rates.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Landmark size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">
              {pack.packId} v{pack.version} has no contribution rates configured yet.
            </p>
          </div>
        )}
      </div>

      <h2 className="text-sm font-semibold text-foreground-secondary mb-3">Organization Contribution Rates (actual, currently configured)</h2>
      <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Key</th>
              <th className="px-4 py-3">Label</th>
              <th className="px-4 py-3">Employee</th>
              <th className="px-4 py-3">Employer</th>
              <th className="px-4 py-3">Total</th>
              <th className="px-4 py-3">Last Updated</th>
            </tr>
          </thead>
          <tbody>
            {orgRates.map((r) => (
              <tr key={r.id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">
                  {r.organizationName} <span className="ml-1 font-mono text-xs text-foreground-disabled">{r.organizationCode}</span>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-foreground-secondary">{r.componentKey}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.label}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.employeeShare || "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.employerShare || "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.total || "—"}</td>
                <td className="px-4 py-3 text-xs text-foreground-muted">
                  {r.updatedAt ? new Date(r.updatedAt).toLocaleDateString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && orgRates.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Building2 size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">
              No organization in {selectedJurisdiction.name} has configured contribution rates yet.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
