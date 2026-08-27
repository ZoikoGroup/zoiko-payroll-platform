import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, History, ShieldCheck, Users, ScrollText } from "lucide-react";
import ConfirmDialog from "../ConfirmDialog";
import StatusPill from "../StatusPill";
import { useToast } from "../../context/ToastContext";
import {
  getComplianceJurisdictions, getCompliancePolicies, upsertCompliancePolicy,
  getCompliancePolicyVersions, setCompliancePolicyStatus, approveCompliancePolicy,
  getCompliancePolicyOrganizations, getCompliancePolicyEligibleOrganizations, assignCompliancePolicy,
  hardDeleteCompliancePolicy,
  getCanonicalTaxSlabs, upsertCanonicalTaxSlab, deleteCanonicalTaxSlab,
  getCanonicalContributionRates, upsertCanonicalContributionRate, deleteCanonicalContributionRate,
  getTaxConfigurationAudit,
} from "../../service/superAdminService";
import { STATUS_PILL_MAP, STATUS_OPTIONS, inputClass, PACK_TABS } from "./constants";
import Field from "./Field";
import RatesTab from "./RatesTab";
import SlabsTab from "./SlabsTab";
import OrgsTab from "./OrgsTab";
import NewPackModal from "./NewPackModal";
import EditOverviewModal from "./EditOverviewModal";
import AssignOrgsModal from "./AssignOrgsModal";
import RateFormModal from "./RateFormModal";
import SlabFormModal from "./SlabFormModal";

// The one shared pack-management surface every Jurisdiction Compliance
// page renders — wires the already-built canonical JurisdictionPack/
// ContributionRate/TaxSlab API surface to a real UI, no new endpoints.
// `country` is fixed per page (chosen by routing, not a dropdown here —
// that's the one thing that moved out compared to the old, single
// monolithic CompliancePage.jsx). `extraTabs`/`slabsTabOverride` are the
// only two country-specific extension points that exist anywhere in this
// codebase today (both India-only) — every other country passes neither.
const BASE_TABS = [
  { key: "overview", label: "Overview", icon: ShieldCheck },
  { key: "rates", label: "Contribution Rates", icon: ScrollText },
  { key: "slabs", label: "Tax Slabs", icon: ScrollText },
  { key: "organizations", label: "Organizations", icon: Users },
  { key: "versions", label: "Versions", icon: History },
  { key: "audit", label: "Audit", icon: ScrollText },
];

export default function JurisdictionLayout({
  country, countryName, initialState = "", onStateChange,
  extraTabs = [], slabsTabOverride,
  hiddenTabs = [], slabsLabel = "Tax Slabs", countryLevelLabel = "Country-level (no state)",
  additionalStateOptions = [], slabsFilter = (s) => s,
  // Safe, purely-additive override for the "New Tax Pack" form — defaults
  // to the shared NewPackModal used by every country. Only USA passes its
  // own (USANewPackModal, which hides the India/UK-oriented Tax Regime
  // field and uses a wider layout); every other country is unaffected
  // since this prop is never passed for them.
  newPackFormComponent: NewPackFormComponent = NewPackModal,
}) {
  const { addToast } = useToast() || {};
  const navigate = useNavigate();
  const [jurisdictions, setJurisdictions] = useState([]);
  const [state, setStateRaw] = useState(initialState || "");
  const [packType, setPackType] = useState("tax");
  const [packs, setPacks] = useState([]);
  const [loadingPacks, setLoadingPacks] = useState(false);
  const [selectedPack, setSelectedPack] = useState(null);
  const [tab, setTab] = useState("overview");

  const [rates, setRates] = useState([]);
  const [slabs, setSlabs] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [eligibleOrgs, setEligibleOrgs] = useState([]);
  const [versions, setVersions] = useState([]);
  const [audit, setAudit] = useState([]);

  const [showNewPack, setShowNewPack] = useState(false);
  const [showEditOverview, setShowEditOverview] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const [assignIds, setAssignIds] = useState(new Set());
  const [showNewRate, setShowNewRate] = useState(false);
  const [editingRate, setEditingRate] = useState(null);
  const [deletingRate, setDeletingRate] = useState(null);
  const [showNewSlab, setShowNewSlab] = useState(false);
  const [editingSlab, setEditingSlab] = useState(null);
  const [deletingSlab, setDeletingSlab] = useState(null);
  const [deletingPack, setDeletingPack] = useState(null);

  function setState(next) {
    setStateRaw(next);
    onStateChange?.(next);
  }

  const loadJurisdictions = useCallback(() => {
    return getComplianceJurisdictions().then(setJurisdictions);
  }, []);

  useEffect(() => { loadJurisdictions(); }, [loadJurisdictions]);

  const selectedJurisdiction = jurisdictions.find((j) => j.code === country);
  // additionalStateOptions lets a country (UK: England/Wales/Northern
  // Ireland) offer a sub-jurisdiction as selectable in the dropdown even
  // before any real pack exists for it — selecting it and hitting "New
  // Tax" is the real, data-driven way to configure it, exactly like every
  // other state on this page. Never fabricates pack DATA — only the
  // option to create one. Real states already in jurisdictions.states
  // (Scotland today) aren't duplicated.
  const stateOptions = [
    ...(selectedJurisdiction?.states || []),
    ...additionalStateOptions.filter((s) => !(selectedJurisdiction?.states || []).includes(s)),
  ];

  // Policy packs aren't a state-level concept in this app (nothing today
  // scopes a Policy pack to a state) — once a state is selected, force
  // Tax and hide the Tax/Policy switcher entirely rather than let it
  // imply a combination that doesn't exist.
  useEffect(() => { if (state) setPackType("tax"); }, [state]);

  const loadPacks = useCallback(() => {
    if (!country) return;
    setLoadingPacks(true);
    getCompliancePolicies({ country, state: state || undefined, packType })
      .then(setPacks)
      .finally(() => setLoadingPacks(false));
  }, [country, state, packType]);

  useEffect(() => { loadPacks(); setSelectedPack(null); }, [loadPacks]);

  const loadPackDetail = useCallback(() => {
    if (!selectedPack) return;
    setTab("overview");
    getCanonicalContributionRates({ jurisdictionPackId: selectedPack.id }).then(setRates);
    getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs);
    getCompliancePolicyOrganizations(selectedPack.id).then(setOrgs);
    getCompliancePolicyEligibleOrganizations(selectedPack.id).then(setEligibleOrgs);
    getCompliancePolicyVersions(selectedPack.packId).then(setVersions);
    getTaxConfigurationAudit({ jurisdictionPackId: selectedPack.id }).then(setAudit);
  }, [selectedPack]);

  useEffect(() => { loadPackDetail(); }, [loadPackDetail]);

  async function changeStatus(newStatus) {
    try {
      const updated = await setCompliancePolicyStatus(selectedPack.id, newStatus);
      addToast?.(`Status set to ${newStatus}.`, "success");
      setSelectedPack(updated);
      loadPacks();
    } catch (err) {
      addToast?.(err.message || "Failed to change status.", "error");
    }
  }

  async function handleApprove() {
    try {
      const updated = await approveCompliancePolicy(selectedPack.id);
      addToast?.("You're now recorded as this pack's approver.", "success");
      setSelectedPack(updated);
      loadPacks();
    } catch (err) {
      addToast?.(err.message || "Failed to record approval.", "error");
    }
  }

  async function handleAssign() {
    try {
      const res = await assignCompliancePolicy(selectedPack.id, Array.from(assignIds));
      addToast?.(res.message || "Assigned.", "success");
      setShowAssign(false);
      setAssignIds(new Set());
      getCompliancePolicyOrganizations(selectedPack.id).then(setOrgs);
    } catch (err) {
      addToast?.(err.message || "Failed to assign.", "error");
    }
  }

  async function handleDeletePack() {
    try {
      const res = await hardDeleteCompliancePolicy(deletingPack.id);
      addToast?.(res.message || "Deleted.", "success");
      setDeletingPack(null);
      setSelectedPack(null);
      loadPacks();
    } catch (err) {
      addToast?.(err.message || "Failed to delete — it may have assigned organizations or payroll history.", "error");
      setDeletingPack(null);
    }
  }

  function reloadRatesAndSlabs() {
    getCanonicalContributionRates({ jurisdictionPackId: selectedPack.id }).then(setRates);
    getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs);
  }

  const slabsOverrideActive = Boolean(selectedPack && slabsTabOverride?.isActive(selectedPack));
  // A slabs override can also restrict the WHOLE tab set (India's
  // state-scoped PT packs show only Overview/PT Slabs/Organizations/Audit
  // — Contribution Rates and Versions don't apply to a single-purpose PT
  // pack). Every other country's tab set is untouched, always the full
  // base six plus any visible extra tabs.
  const visibleExtraTabs = selectedPack ? extraTabs.filter((t) => t.isVisible(selectedPack)) : [];
  const restrictTo = slabsOverrideActive ? slabsTabOverride.restrictTabsTo : null;
  // hiddenTabs drops base tabs unconditionally (not pack-dependent, unlike
  // restrictTabsTo above) — UK uses this to drop the generic "Contribution
  // Rates"/"Versions" tabs in favor of its own NI & Pension Rates /
  // Statutory Thresholds extra tabs. Every other country passes [].
  let tabs = BASE_TABS.filter((t) => !hiddenTabs.includes(t.key));
  // Each extra tab anchors after a given base-tab key (default "slabs",
  // preserving the original fixed insertion point so India's existing Tax
  // Parameters tab — which doesn't set `after` — lands exactly where it
  // always has). Lets UK insert "NI & Pension Rates" before Slabs while
  // "HMRC Statutory Thresholds" lands after it, in one pass.
  visibleExtraTabs.forEach((extraTab) => {
    const anchorIndex = tabs.findIndex((t) => t.key === (extraTab.after || "slabs"));
    tabs.splice(anchorIndex === -1 ? tabs.length : anchorIndex + 1, 0, extraTab);
  });
  if (restrictTo) tabs = tabs.filter((t) => restrictTo.includes(t.key));

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">{countryName} Compliance</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Manage {countryName}'s tax and policy packs — versions, canonical rates/slabs, organization assignment, and audit history.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <select className={inputClass + " w-auto min-w-[160px]"} value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">{countryLevelLabel}</option>
          {stateOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {!state && (
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-border bg-surface-muted p-1">
          {PACK_TABS.map((t) => (
            <button
              key={t.key} onClick={() => setPackType(t.key)}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${packType === t.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        )}
        <button
          onClick={() => {
            if (packType === "policy") {
              navigate(`/super-admin/compliance/policy/new?mode=new&country=${country}${state ? `&state=${encodeURIComponent(state)}` : ""}`);
            } else {
              setShowNewPack(true);
            }
          }}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={14} /> New {packType === "tax" ? "Tax" : "Policy"}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <div className="rounded-xl border border-border bg-surface p-2">
          {loadingPacks ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
          ) : packs.length === 0 ? (
            <p className="py-8 text-center text-xs text-foreground-disabled">No {packType} packs for this jurisdiction yet.</p>
          ) : (
            <div className="space-y-1">
              {packs.map((p) => (
                <button
                  key={p.id} onClick={() => setSelectedPack(p)}
                  className={`flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left text-xs ${
                    selectedPack?.id === p.id ? "bg-primary/10 text-primary" : "text-foreground-secondary hover:bg-surface-muted"
                  }`}
                >
                  <span className="font-semibold">{p.packId}</span>
                  <span className="flex items-center gap-2 text-foreground-muted">
                    v{p.version}{p.taxYear ? ` · FY ${p.taxYear}` : ""} <StatusPill status={STATUS_PILL_MAP[p.status] || "pending"} label={p.status} />
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-border bg-surface p-5">
          {!selectedPack ? (
            <div className="flex h-64 items-center justify-center">
              <p className="text-sm text-foreground-disabled">Select a pack from the list to view/edit it.</p>
            </div>
          ) : (
            <>
              <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-foreground">{selectedPack.packId}</h2>
                    <StatusPill status={STATUS_PILL_MAP[selectedPack.status] || "pending"} label={selectedPack.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-foreground-muted">
                    v{selectedPack.version} · {selectedPack.jurisdictionCountry}{selectedPack.jurisdictionState ? ` / ${selectedPack.jurisdictionState}` : ""}
                    {selectedPack.taxYear ? ` · FY ${selectedPack.taxYear}` : ""}
                    {selectedPack.effectiveFrom ? ` · ${selectedPack.effectiveFrom} → ${selectedPack.effectiveTo || "open"}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {selectedPack.packType === "tax" && (
                    <>
                      <button
                        onClick={() => setShowEditOverview(true)}
                        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                      >
                        <Pencil size={13} /> Edit
                      </button>
                      {/* Maker-checker (ZP-TAX-UK-2026-27-001 section 19.2): a
                          distinct Super Admin from whoever last edited the pack
                          must approve it before it can go Active — enforced
                          server-side in set_jurisdiction_pack_status; this
                          button just records "I approve this," it doesn't
                          change status itself. */}
                      <button
                        onClick={handleApprove}
                        title={selectedPack.approvedById ? `Currently approved by user #${selectedPack.approvedById}` : "Not yet approved"}
                        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                      >
                        <ShieldCheck size={13} /> Approve
                      </button>
                    </>
                  )}
                  {selectedPack.packType === "policy" && (
                    <>
                      <button
                        onClick={() => navigate(`/super-admin/compliance/policy/new?mode=edit&packId=${encodeURIComponent(selectedPack.packId)}&version=${encodeURIComponent(selectedPack.version)}&country=${country}`)}
                        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                      >
                        <Pencil size={13} /> Edit
                      </button>
                      <button
                        onClick={() => navigate(`/super-admin/compliance/policy/new?mode=newVersion&packId=${encodeURIComponent(selectedPack.packId)}&version=${encodeURIComponent(selectedPack.version)}&country=${country}`)}
                        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                      >
                        <Plus size={13} /> New Version
                      </button>
                    </>
                  )}
                  <select
                    className={inputClass + " w-auto"} value={selectedPack.status}
                    onChange={(e) => changeStatus(e.target.value)}
                  >
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <button onClick={() => setDeletingPack(selectedPack)} className="rounded-lg border border-border p-2 text-error hover:bg-error-light"><Trash2 size={14} /></button>
                </div>
              </div>

              <div className="mb-4 flex items-center gap-1 border-b border-border overflow-x-auto">
                {tabs.map((t) => (
                  <button
                    key={t.key} onClick={() => setTab(t.key)}
                    className={`flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${
                      tab === t.key ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    <t.icon size={13} /> {t.key === "slabs" ? (slabsOverrideActive ? slabsTabOverride.label : slabsLabel) : t.label}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                  <Field label="Regulatory Authority" value={selectedPack.regulatoryAuthority} />
                  <Field label="Compliance Category" value={selectedPack.complianceCategory} />
                  <Field label="Compliance Owner" value={selectedPack.complianceOwner} />
                  <Field label="Engineering Owner" value={selectedPack.engineeringOwner} />
                  <Field label="Tax Regime" value={selectedPack.taxRegime} />
                  <Field label="Currency" value={selectedPack.currency} />
                  <Field label="Next Review Date" value={selectedPack.nextReviewDate} />
                  <Field label="Source References" value={selectedPack.sourceReferences} />
                  <div className="sm:col-span-2">
                    <p className="text-foreground-muted mb-1">Change Summary</p>
                    <p className="font-medium text-foreground">{selectedPack.changeSummary || "—"}</p>
                  </div>
                </div>
              )}

              {tab === "rates" && (
                <RatesTab
                  pack={selectedPack} rates={rates} onAdd={() => setShowNewRate(true)}
                  onEdit={setEditingRate} onDelete={setDeletingRate}
                />
              )}
              {tab === "slabs" && slabsOverrideActive && (
                slabsTabOverride.renderTab({ pack: selectedPack, slabs: slabsFilter(slabs), onAdd: () => setShowNewSlab(true), onEdit: setEditingSlab, onDelete: setDeletingSlab })
              )}
              {tab === "slabs" && !slabsOverrideActive && (
                <SlabsTab
                  pack={selectedPack} slabs={slabsFilter(slabs)} onAdd={() => setShowNewSlab(true)}
                  onEdit={setEditingSlab} onDelete={setDeletingSlab}
                />
              )}
              {visibleExtraTabs.map((extraTab) => (
                tab === extraTab.key && (
                  <div key={extraTab.key}>
                    {extraTab.render({
                      pack: selectedPack, rates, slabs, addToast,
                      onReload: reloadRatesAndSlabs,
                      onPublish: () => changeStatus("Active"),
                      // Purely additive — lets one extraTab switch to a
                      // sibling extraTab (e.g. USA's "Federal Income Tax"
                      // picker entry jumping to the Income Tax Brackets
                      // tab). No existing key changed; every extraTab that
                      // doesn't use this (every country besides USA today)
                      // is completely unaffected.
                      onNavigateTab: setTab,
                      onAddRate: () => setShowNewRate(true),
                      onEditRate: setEditingRate,
                      onDeleteRate: setDeletingRate,
                      onAddSlab: () => setShowNewSlab(true),
                      onEditSlab: setEditingSlab,
                      onDeleteSlab: setDeletingSlab,
                    })}
                  </div>
                )
              ))}
              {tab === "organizations" && (
                <OrgsTab orgs={orgs} onAssign={() => setShowAssign(true)} />
              )}
              {tab === "versions" && (
                <div className="space-y-2">
                  {versions.map((v) => (
                    <button
                      key={v.id} onClick={() => setSelectedPack(v)}
                      className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-xs text-left ${
                        v.id === selectedPack.id ? "border-primary bg-primary/5" : "border-border-light hover:bg-surface-muted"
                      }`}
                    >
                      <span className="font-medium text-foreground">v{v.version}</span>
                      <span className="flex items-center gap-2 text-foreground-muted">
                        {v.effectiveFrom} → {v.effectiveTo || "open"}
                        <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {tab === "audit" && (
                <div className="space-y-2">
                  {audit.length === 0 ? (
                    <p className="py-6 text-center text-xs text-foreground-disabled">No audit history yet.</p>
                  ) : audit.map((a) => {
                    // oldValue/newValue were always in the API response —
                    // just never rendered. Only show keys that actually
                    // changed, so a no-op field isn't noise in the diff.
                    const changedKeys = Object.keys({ ...(a.oldValue || {}), ...(a.newValue || {}) })
                      .filter((k) => JSON.stringify(a.oldValue?.[k]) !== JSON.stringify(a.newValue?.[k]));
                    return (
                      <div key={a.id} className="rounded-lg border border-border-light p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-foreground">
                            {a.action} — {a.entityType} {a.actorId ? <span className="text-foreground-disabled">· by user #{a.actorId}</span> : null}
                          </span>
                          <span className="text-foreground-disabled">{new Date(a.createdAt).toLocaleString()}</span>
                        </div>
                        {a.reason && <p className="mt-1 text-foreground-secondary">{a.reason}</p>}
                        {changedKeys.length > 0 && (
                          <div className="mt-1.5 space-y-0.5 border-t border-border-light pt-1.5">
                            {changedKeys.map((k) => (
                              <div key={k} className="flex items-center gap-1.5 font-mono text-[11px]">
                                <span className="text-foreground-disabled">{k}:</span>
                                <span className="text-error line-through">{a.oldValue?.[k] ?? "—"}</span>
                                <span className="text-foreground-disabled">→</span>
                                <span className="text-success">{a.newValue?.[k] ?? "—"}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {showNewPack && (
        <NewPackFormComponent
          country={country} state={state} packType={packType}
          onClose={() => setShowNewPack(false)}
          onCreated={(created) => {
            setShowNewPack(false);
            loadPacks();
            setSelectedPack(created);
            // A brand-new state (e.g. typed into the pack's State field)
            // only becomes a real filter option once this refetches —
            // without it, the new state wouldn't show up until a full
            // page reload, even though the pack itself is already usable.
            loadJurisdictions();
          }}
        />
      )}
      {showEditOverview && (
        <EditOverviewModal
          pack={selectedPack} onClose={() => setShowEditOverview(false)}
          onSaved={(updated) => { setShowEditOverview(false); setSelectedPack(updated); loadPacks(); }}
        />
      )}
      {showAssign && (
        <AssignOrgsModal
          eligibleOrgs={eligibleOrgs} assignedIds={new Set(orgs.map((o) => o.id))}
          selected={assignIds} setSelected={setAssignIds}
          onClose={() => setShowAssign(false)} onSave={handleAssign}
        />
      )}
      {showNewRate && (
        <RateFormModal
          pack={selectedPack} onClose={() => setShowNewRate(false)}
          onSaved={() => { setShowNewRate(false); getCanonicalContributionRates({ jurisdictionPackId: selectedPack.id }).then(setRates); }}
        />
      )}
      {editingRate && (
        <RateFormModal
          pack={selectedPack} rate={editingRate} onClose={() => setEditingRate(null)}
          onSaved={() => { setEditingRate(null); getCanonicalContributionRates({ jurisdictionPackId: selectedPack.id }).then(setRates); }}
        />
      )}
      {deletingRate && (
        <ConfirmDialog
          title="Delete Contribution Rate" message={`Delete "${deletingRate.label}"? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalContributionRate(deletingRate.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingRate(null);
            getCanonicalContributionRates({ jurisdictionPackId: selectedPack.id }).then(setRates);
          }}
          onClose={() => setDeletingRate(null)}
        />
      )}
      {showNewSlab && slabsOverrideActive && (
        slabsTabOverride.renderAddModal({
          pack: selectedPack, slabs, addToast, onClose: () => setShowNewSlab(false),
          onSaved: () => { setShowNewSlab(false); getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs); },
        })
      )}
      {showNewSlab && !slabsOverrideActive && (
        <SlabFormModal
          pack={selectedPack} onClose={() => setShowNewSlab(false)}
          onSaved={() => { setShowNewSlab(false); getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs); }}
        />
      )}
      {editingSlab && slabsOverrideActive && (
        slabsTabOverride.renderEditModal({
          pack: selectedPack, slab: editingSlab, slabs, addToast, onClose: () => setEditingSlab(null),
          onSaved: () => { setEditingSlab(null); getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs); },
        })
      )}
      {editingSlab && !slabsOverrideActive && (
        <SlabFormModal
          pack={selectedPack} slab={editingSlab} onClose={() => setEditingSlab(null)}
          onSaved={() => { setEditingSlab(null); getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs); }}
        />
      )}
      {deletingSlab && (
        <ConfirmDialog
          title={slabsOverrideActive ? (slabsTabOverride.deleteTitle || "Delete Slab") : "Delete Tax Slab"}
          message={slabsOverrideActive ? slabsTabOverride.deleteMessage(deletingSlab) : `Delete the "${deletingSlab.rateLabel}" bracket? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalTaxSlab(deletingSlab.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingSlab(null);
            getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs);
          }}
          onClose={() => setDeletingSlab(null)}
        />
      )}
      {deletingPack && (
        <ConfirmDialog
          title="Delete Pack" message={`Permanently delete "${deletingPack.packId}" v${deletingPack.version}? Only allowed with no assigned organizations and no payroll history.`}
          onConfirm={handleDeletePack} onClose={() => setDeletingPack(null)}
        />
      )}
    </div>
  );
}
