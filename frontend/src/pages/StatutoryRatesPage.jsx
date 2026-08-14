import React, { useEffect, useState, useCallback } from "react";
import { Plus, Pencil, Trash2, RefreshCw, Landmark, Building2, ArrowLeft } from "lucide-react";

import { apiFetch } from "../api/client";
import { useToast } from "../context/ToastContext";
import StatutoryRateModal from "../components/StatutoryRateModal";
import ConfirmDialog from "../components/ConfirmDialog";
import StatusPill from "../components/StatusPill";
import { getOrganizationContributionRates, seedStatutoryRateDefaults } from "../service/superAdminService";
import { getStatesForCountryCode } from "../utils/registrationRegions";
import JurisdictionCardGrid, { AddJurisdictionModal } from "./JurisdictionCardGrid";

export default function StatutoryRatesPage() {
  const { addToast } = useToast();

  // null = jurisdiction card grid (same shared component/data Compliance
  // uses); set = drilled into one country (+ optional state) — every fetch
  // below scopes to this jurisdiction, so switching it changes the whole
  // context, same as Compliance.
  const [selectedJurisdiction, setSelectedJurisdiction] = useState(null);
  const [selectedState, setSelectedState] = useState(""); // "" = country-level
  const [showAddJurisdiction, setShowAddJurisdiction] = useState(false);

  const [rates, setRates] = useState([]);
  const [orgRates, setOrgRates] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);

  const countryCode = selectedJurisdiction?.code || "";
  const availableStates = selectedJurisdiction ? getStatesForCountryCode(countryCode) : [];

  const load = useCallback(() => {
    if (!selectedJurisdiction) return;
    setLoading(true);
    setError("");
    Promise.all([
      apiFetch("/api/super-admin/statutory-rates", {
        // Omitting `state` here means "country-level only" on the backend
        // (not "every state blended together") — the same isolation
        // Compliance's Taxes/Policies tabs already enforce.
        params: { country: countryCode, state: selectedState || undefined },
      }),
      getOrganizationContributionRates({ country: countryCode }),
    ])
      .then(([platformRes, orgRes]) => {
        setRates(platformRes.rates);
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
    setRates([]);
    setOrgRates([]);
  }

  async function handleSave(payload) {
    setBusy(true);
    try {
      if (modal && modal !== "new") {
        await apiFetch(`/api/super-admin/statutory-rates/${modal.id}`, { method: "PUT", body: payload });
        addToast?.("Statutory rate updated.");
      } else {
        await apiFetch("/api/super-admin/statutory-rates", { method: "POST", body: payload });
        addToast?.("Statutory rate created.");
      }
      setModal(null);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await apiFetch(`/api/super-admin/statutory-rates/${deleting.id}`, { method: "DELETE" });
      addToast?.("Statutory rate deleted.");
      setDeleting(null);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleSeedDefaults() {
    setBusy(true);
    try {
      const res = await seedStatutoryRateDefaults();
      addToast?.(res.message);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  if (!selectedJurisdiction) {
    return (
      <div>
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-foreground">Statutory Rates</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Pick a jurisdiction to manage its platform default rates and see every organization's actual configured
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
            {selectedJurisdiction.currency || "N/A"} · Rates configured here apply only to{" "}
            {selectedState || selectedJurisdiction.name}.
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
            onClick={handleSeedDefaults}
            disabled={busy}
            title="Backfill from the payroll engine's existing per-country defaults — safe to run anytime, never overwrites an existing rate"
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCw size={15} className={busy ? "animate-spin" : ""} />
            Sync Engine Defaults
          </button>
          <button
            onClick={() => setModal("new")}
            className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white hover:bg-primary-hover"
          >
            <Plus size={16} />
            Add Rate
          </button>
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

      <h2 className="text-sm font-semibold text-foreground-secondary mb-3">Platform Default Rates</h2>
      <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden mb-8">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Key</th>
              <th className="px-4 py-3">Label</th>
              <th className="px-4 py-3">Employee</th>
              <th className="px-4 py-3">Employer</th>
              <th className="px-4 py-3">Total</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rates.map((r) => (
              <tr key={r.id} className="border-t border-border-light hover:bg-slate-50/60 dark:hover:bg-white/5 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-foreground-secondary">{r.component_key}</td>
                <td className="px-4 py-3 font-medium text-foreground">{r.label}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.employee_share || "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.employer_share || "—"}</td>
                <td className="px-4 py-3 text-foreground-secondary">{r.total || "—"}</td>
                <td className="px-4 py-3">
                  <StatusPill status={r.is_active ? "active" : "inactive"} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setModal(r)}
                      title="Edit rate"
                      className="rounded-lg bg-slate-100 dark:bg-white/10 p-1.5 text-foreground-secondary hover:bg-slate-200 dark:hover:bg-white/20"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => setDeleting(r)}
                      title="Delete rate"
                      className="rounded-lg bg-red-50 dark:bg-red-950/40 p-1.5 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-950/60"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && rates.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Landmark size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">
              No platform default rates for {selectedJurisdiction.name}{selectedState ? ` / ${selectedState}` : ""} yet.
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

      {modal && (
        <StatutoryRateModal
          rate={modal === "new" ? null : modal}
          defaultCountry={countryCode}
          defaultState={selectedState}
          lockJurisdiction={modal === "new"}
          busy={busy}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete Statutory Rate"
          message={`Delete "${deleting.label}" (${deleting.jurisdiction_country}${deleting.jurisdiction_state ? "/" + deleting.jurisdiction_state : ""}/${deleting.component_key})? This cannot be undone.`}
          busy={busy}
          onConfirm={handleDelete}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
