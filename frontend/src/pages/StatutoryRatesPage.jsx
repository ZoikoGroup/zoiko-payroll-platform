import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, Building2, ArrowLeft, ArrowRight, Plus, Trash2, Pencil, Check, X, FolderTree } from "lucide-react";

import {
  getOrganizationContributionRates, getCompliancePolicies,
  getCanonicalContributionRates, upsertCanonicalContributionRate, deleteCanonicalContributionRate,
} from "../service/superAdminService";
import { getStatesForCountryCode } from "../utils/registrationRegions";
import { useToast } from "../context/ToastContext";
import ConfirmDialog from "../components/ConfirmDialog";
import JurisdictionCardGrid, { AddJurisdictionModal } from "./JurisdictionCardGrid";
import StatutoryRatesHierarchyPanel from "../components/hierarchy/StatutoryRatesHierarchyPanel";

const cellInput = "w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-focus-ring";
const emptyDraft = { componentKey: "", label: "", employeeRatePct: "", employerRatePct: "", flatAmount: "" };

// Generic Contribution Rates (component key, employee %, employer %, flat
// amount — PF/ESI and similar) for ONE selected Tax ID (JurisdictionPack).
// Tax Parameters (Standard Deduction, wage ceilings, rebates, ...) live in
// Compliance instead — only for country/federal/national-level packs —
// never here.
//
// Read-only by default. An explicit Edit action makes exactly ONE row
// editable at a time (with its own Save/Cancel); an explicit Delete asks
// for confirmation first. Nothing becomes editable just from being
// displayed or from the page loading.
function ContributionRatesEditor({ pack }) {
  const { addToast } = useToast() || {};
  const [rates, setRates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null); // an existing row's id, or "new"
  const [draft, setDraft] = useState(emptyDraft);
  const [deleting, setDeleting] = useState(null); // the row pending delete confirmation
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getCanonicalContributionRates({ jurisdictionPackId: pack.id });
      setRates(r);
    } catch (err) {
      addToast?.(err.message || "Failed to load contribution rates.", "error");
      setRates([]);
    } finally {
      setLoading(false);
    }
  }, [pack.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  function startAdd() {
    setEditingId("new");
    setDraft(emptyDraft);
  }

  function startEdit(rate) {
    setEditingId(rate.id);
    setDraft({
      componentKey: rate.componentKey, label: rate.label,
      employeeRatePct: rate.employeeRatePct ?? "", employerRatePct: rate.employerRatePct ?? "",
      flatAmount: rate.flatAmount ?? "",
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft(emptyDraft);
  }

  async function saveEdit() {
    if (!draft.componentKey.trim() || !draft.label.trim()) {
      addToast?.("Component key and label are required.", "error");
      return;
    }
    setSaving(true);
    try {
      const existing = editingId !== "new" ? rates.find((r) => r.id === editingId) : null;
      await upsertCanonicalContributionRate({
        id: editingId === "new" ? undefined : editingId,
        jurisdictionPackId: pack.id, jurisdictionCountry: pack.jurisdictionCountry, jurisdictionState: pack.jurisdictionState,
        componentKey: draft.componentKey.trim(), label: draft.label.trim(),
        employeeSharePct: draft.employeeRatePct || null, employerSharePct: draft.employerRatePct || null,
        flatAmount: draft.flatAmount || null, sortOrder: existing?.sortOrder,
      });
      addToast?.(editingId === "new" ? "Contribution rate added." : "Contribution rate updated.", "success");
      cancelEdit();
      await load();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteConfirm() {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await deleteCanonicalContributionRate(deleting.id);
      addToast?.("Contribution rate deleted.", "success");
      setDeleting(null);
      await load();
    } catch (err) {
      addToast?.(err.message || "Failed to delete.", "error");
    } finally {
      setDeleteBusy(false);
    }
  }

  if (loading) {
    return <p className="py-8 text-center text-sm text-foreground-disabled">Loading…</p>;
  }

  function draftRow(key) {
    return (
      <tr key={key} className="border-t border-border-light bg-primary/5">
        <td className="px-3 py-1.5"><input className={cellInput} placeholder="component_key" value={draft.componentKey} onChange={(e) => setDraft((d) => ({ ...d, componentKey: e.target.value }))} /></td>
        <td className="px-3 py-1.5"><input className={cellInput} placeholder="Label" value={draft.label} onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))} /></td>
        <td className="px-3 py-1.5"><input className={cellInput} type="number" step="0.01" value={draft.employeeRatePct} onChange={(e) => setDraft((d) => ({ ...d, employeeRatePct: e.target.value }))} /></td>
        <td className="px-3 py-1.5"><input className={cellInput} type="number" step="0.01" value={draft.employerRatePct} onChange={(e) => setDraft((d) => ({ ...d, employerRatePct: e.target.value }))} /></td>
        <td className="px-3 py-1.5"><input className={cellInput} type="number" step="0.01" value={draft.flatAmount} onChange={(e) => setDraft((d) => ({ ...d, flatAmount: e.target.value }))} /></td>
        <td className="px-3 py-1.5">
          <div className="flex items-center gap-1">
            <button type="button" title="Save" onClick={saveEdit} disabled={saving} className="rounded p-1 text-primary hover:bg-primary/10 disabled:opacity-50">
              <Check size={14} />
            </button>
            <button type="button" title="Cancel" onClick={cancelEdit} disabled={saving} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted disabled:opacity-50">
              <X size={14} />
            </button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border overflow-x-auto">
        <table className="w-full text-xs min-w-[560px]">
          <thead className="bg-background text-left text-foreground-muted">
            <tr>
              <th className="px-3 py-2">Component</th><th className="px-3 py-2">Label</th>
              <th className="px-3 py-2">Employee %</th><th className="px-3 py-2">Employer %</th>
              <th className="px-3 py-2">Flat Amount</th><th className="px-3 py-2 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {rates.map((r) => (
              editingId === r.id ? draftRow(r.id) : (
                <tr key={r.id} className="border-t border-border-light hover:bg-slate-50/60 dark:hover:bg-white/5">
                  <td className="px-3 py-1.5 font-mono text-foreground-secondary">{r.componentKey}</td>
                  <td className="px-3 py-1.5 text-foreground">{r.label}</td>
                  <td className="px-3 py-1.5 text-foreground-secondary">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                  <td className="px-3 py-1.5 text-foreground-secondary">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                  <td className="px-3 py-1.5 text-foreground-secondary">{r.flatAmount != null ? r.flatAmount : "—"}</td>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-1">
                      <button type="button" title="Edit" onClick={() => startEdit(r)} disabled={editingId !== null} className="rounded p-1 text-foreground-disabled hover:bg-surface-muted hover:text-primary disabled:opacity-40">
                        <Pencil size={12} />
                      </button>
                      <button type="button" title="Delete" onClick={() => setDeleting(r)} disabled={editingId !== null} className="rounded p-1 text-foreground-disabled hover:bg-error-light hover:text-error disabled:opacity-40">
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            ))}
            {editingId === "new" && draftRow("new")}
          </tbody>
        </table>
        {rates.length === 0 && editingId !== "new" && (
          <p className="px-3 py-6 text-center text-xs text-foreground-disabled">No contribution rates configured for this Tax ID yet.</p>
        )}
      </div>
      {editingId === null && (
        <button type="button" onClick={startAdd} className="flex items-center gap-1 rounded-md border border-dashed border-border px-2.5 py-1 text-xs font-medium text-foreground-muted hover:border-primary hover:text-primary">
          <Plus size={12} /> Add Rate
        </button>
      )}

      {deleting && (
        <ConfirmDialog
          title="Delete Contribution Rate"
          message={`Delete "${deleting.label}" (${deleting.componentKey})? This cannot be undone.`}
          busy={deleteBusy}
          onConfirm={handleDeleteConfirm}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

function ViewToggle({ view, setView }) {
  return (
    <div className="mb-6 flex gap-1 rounded-[14px] bg-surface-muted p-1 w-fit">
      {[
        { key: "legacy", label: "Jurisdiction Packs" },
        { key: "hierarchy", label: "New Hierarchy Engine (Preview)" },
      ].map((t) => (
        <button
          key={t.key}
          onClick={() => setView(t.key)}
          className={`px-4 py-2 rounded-[10px] text-xs font-semibold transition-colors ${
            view === t.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export default function StatutoryRatesPage() {
  const navigate = useNavigate();
  const [view, setView] = useState("legacy");

  if (view === "hierarchy") {
    return (
      <div>
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FolderTree size={22} /> Statutory Rates
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Numeric values only — rates, thresholds, slabs, and parameters from the new jurisdiction/tax hierarchy
            engine. Creating taxes/versions or changing their status happens in the Jurisdiction Explorer.
          </p>
        </div>
        <ViewToggle view={view} setView={setView} />
        <StatutoryRatesHierarchyPanel />
      </div>
    );
  }

  // null = jurisdiction card grid (same shared component/data Compliance
  // uses); set = drilled into one country (+ optional state) — every fetch
  // below scopes to this jurisdiction, so switching it changes the whole
  // context, same as Compliance.
  const [selectedJurisdiction, setSelectedJurisdiction] = useState(null);
  const [selectedState, setSelectedState] = useState(""); // "" = country-level
  const [showAddJurisdiction, setShowAddJurisdiction] = useState(false);

  // Every Tax pack (Tax ID) for the current country/state scope, and which
  // one is currently selected for Contribution Rate editing below.
  const [taxPacks, setTaxPacks] = useState([]);
  const [selectedPackId, setSelectedPackId] = useState(null);
  const [orgRates, setOrgRates] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const countryCode = selectedJurisdiction?.code || "";
  const availableStates = selectedJurisdiction ? getStatesForCountryCode(countryCode) : [];
  const selectedPack = taxPacks.find((p) => p.id === selectedPackId) || null;

  const load = useCallback(() => {
    if (!selectedJurisdiction) return;
    setLoading(true);
    setError("");
    Promise.all([
      // Omitting `state` here means "country-level only" on the backend
      // (not "every state blended together") — the same isolation
      // Compliance's Taxes/Policies tabs already enforce.
      getCompliancePolicies({ country: countryCode, state: selectedState || undefined, packType: "tax" }),
      getOrganizationContributionRates({ country: countryCode }),
    ])
      .then(([packs, orgRes]) => {
        setTaxPacks(packs);
        setOrgRates(orgRes);
        // Prefer the Active pack as the default selection; fall back to
        // whichever pack sorts first (list_all_jurisdiction_packs already
        // returns one row per Tax ID, latest version only).
        const active = packs.find((p) => p.status === "Active");
        setSelectedPackId((active || packs[0])?.id ?? null);
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
    setTaxPacks([]);
    setSelectedPackId(null);
    setOrgRates([]);
  }

  // Editing a pack's Tax Slabs (progressive brackets) or its identity/
  // metadata happens on Compliance — Contribution Rates are this page's
  // job, Tax Slabs are Compliance's.
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
            Pick a jurisdiction, select a Tax ID, and configure its Contribution Rates — the same jurisdictions as
            Compliance, isolated the same way.
          </p>
        </div>
        <ViewToggle view={view} setView={setView} />
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
            {selectedJurisdiction.currency || "N/A"} · Select a Tax ID to configure {selectedState || selectedJurisdiction.name}'s Contribution Rates.
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

      <div className="mb-8">
        <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
          <div className="min-w-[260px]">
            <label className="block text-xs font-semibold text-foreground-muted mb-1.5">Tax ID</label>
            {taxPacks.length > 0 ? (
              <select
                value={selectedPackId ?? ""}
                onChange={(e) => setSelectedPackId(Number(e.target.value))}
                className="w-full rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
              >
                {taxPacks.map((p) => (
                  <option key={p.id} value={p.id}>{p.packId} v{p.version} ({p.status})</option>
                ))}
              </select>
            ) : (
              <p className="text-sm text-foreground-disabled">
                No Tax ID configured for {selectedState || selectedJurisdiction.name} yet.
              </p>
            )}
          </div>
          <button
            onClick={goToComplianceEdit}
            className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary-hover"
          >
            {taxPacks.length > 0 ? "Edit in Compliance" : "Create a Tax ID in Compliance"} <ArrowRight size={13} />
          </button>
        </div>

        {selectedPack && (
          <div className="rounded-xl border border-border bg-surface p-4">
            <p className="text-xs font-semibold text-foreground-muted mb-3">
              Contribution Rates — {selectedPack.packId} v{selectedPack.version}
            </p>
            <ContributionRatesEditor key={selectedPack.id} pack={selectedPack} />
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
