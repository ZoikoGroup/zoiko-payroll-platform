import { useState, useEffect } from "react";
import {
  ChevronDown, ChevronRight, MapPin, Pencil, ShieldCheck,
  Percent, ScrollText, ArrowLeftRight, FileCheck2, History,
} from "lucide-react";
import ConfirmDialog from "../../../ConfirmDialog";
import StatusPill from "../../../StatusPill";
import { useToast } from "../../../../context/ToastContext";
import {
  getCanonicalContributionRates, getCanonicalTaxSlabs,
  deleteCanonicalContributionRate, deleteCanonicalTaxSlab,
  setCompliancePolicyStatus, approveCompliancePolicy,
} from "../../../../service/superAdminService";
import { inputClass, STATUS_PILL_MAP, STATUS_OPTIONS } from "../../constants";
import EditOverviewModal from "../../EditOverviewModal";
import USTaxComponentsTab from "../USTaxComponentsTab";
import USIncomeTaxBracketsTab from "../USIncomeTaxBracketsTab";
import USStateSuiSection from "./USStateSuiSection";
import USStateReciprocitySection from "./USStateReciprocitySection";
import USStateSourceEvidenceNote from "./USStateSourceEvidenceNote";
import USStateVersionAuditSection from "./USStateVersionAuditSection";

const TABS = [
  { key: "components", label: "Tax Components", icon: Percent },
  { key: "incomeTax", label: "Income Tax Brackets", icon: ScrollText },
  { key: "sui", label: "SUI Employer Rates", icon: Percent },
  { key: "reciprocity", label: "Reciprocity & Sourcing", icon: ArrowLeftRight },
  { key: "sourceEvidence", label: "Source Evidence", icon: FileCheck2 },
  { key: "versionAudit", label: "Version / Audit", icon: History },
];

// One state's collapsed summary row + expanded detail. This is the new,
// dedicated replacement for what used to be a click into JurisdictionLayout
// (a second sidebar + detail panel) — everything that belongs to this state
// now renders inline, in place. Rates/slabs for the currently-displayed pack
// arrive as props (already fetched once by the workspace for the collapsed
// summary line), so expanding a row never re-issues that fetch; switching to
// a different pack version via the picker below does fetch fresh, since the
// workspace only ever caches each state's ACTIVE-or-first pack.
export default function USStateAccordionRow({
  stateName, pack, packs, rates: initialRates, slabs: initialSlabs,
  isExpanded, onToggle, onPackUpdated, onReloadSummary,
}) {
  const { addToast } = useToast() || {};
  const [selectedPack, setSelectedPack] = useState(pack);
  const [rates, setRates] = useState(initialRates || []);
  const [slabs, setSlabs] = useState(initialSlabs || []);
  const [tab, setTab] = useState("components");
  const [showEditOverview, setShowEditOverview] = useState(false);
  const [deletingRate, setDeletingRate] = useState(null);
  const [deletingSlab, setDeletingSlab] = useState(null);

  useEffect(() => { setSelectedPack(pack); }, [pack]);
  useEffect(() => { setRates(initialRates || []); }, [initialRates]);
  useEffect(() => { setSlabs(initialSlabs || []); }, [initialSlabs]);

  function reloadRatesAndSlabs() {
    if (!selectedPack) return;
    getCanonicalContributionRates({ jurisdictionPackId: selectedPack.id }).then(setRates);
    getCanonicalTaxSlabs({ jurisdictionPackId: selectedPack.id }).then(setSlabs);
    onReloadSummary?.();
  }

  function switchPack(nextPack) {
    setSelectedPack(nextPack);
    getCanonicalContributionRates({ jurisdictionPackId: nextPack.id }).then(setRates);
    getCanonicalTaxSlabs({ jurisdictionPackId: nextPack.id }).then(setSlabs);
  }

  async function changeStatus(newStatus) {
    try {
      const updated = await setCompliancePolicyStatus(selectedPack.id, newStatus);
      addToast?.(`Status set to ${newStatus}.`, "success");
      setSelectedPack(updated);
      onPackUpdated?.(updated);
    } catch (err) {
      addToast?.(err.message || "Failed to change status.", "error");
    }
  }

  async function handleApprove() {
    try {
      const updated = await approveCompliancePolicy(selectedPack.id);
      addToast?.("You're now recorded as this pack's approver.", "success");
      setSelectedPack(updated);
      onPackUpdated?.(updated);
    } catch (err) {
      addToast?.(err.message || "Failed to record approval.", "error");
    }
  }

  const summary = pack ? `${(rates || []).length} Tax Components · ${(slabs || []).length} Income Tax Brackets` : "Not configured";

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button onClick={onToggle} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left">
        <div className="flex min-w-0 items-center gap-3">
          {isExpanded ? <ChevronDown size={16} className="shrink-0 text-foreground-muted" /> : <ChevronRight size={16} className="shrink-0 text-foreground-muted" />}
          <MapPin size={14} className="shrink-0 text-foreground-muted" />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{stateName}</p>
            <p className="truncate text-xs text-foreground-muted">
              {pack ? `${pack.packId} · v${pack.version} · ${summary}` : summary}
            </p>
          </div>
        </div>
        {pack && <StatusPill status={STATUS_PILL_MAP[pack.status] || "pending"} label={pack.status} />}
      </button>

      {isExpanded && (
        <div className="border-t border-border p-4">
          {!selectedPack ? (
            <p className="py-6 text-center text-xs text-foreground-disabled">
              No tax pack configured for {stateName} yet — use "New State / Tax" above to create one.
            </p>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-bold text-foreground">{selectedPack.packId}</h3>
                    <StatusPill status={STATUS_PILL_MAP[selectedPack.status] || "pending"} label={selectedPack.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-foreground-muted">
                    v{selectedPack.version} · {stateName}
                    {selectedPack.taxYear ? ` · FY ${selectedPack.taxYear}` : ""}
                    {selectedPack.effectiveFrom ? ` · ${selectedPack.effectiveFrom} → ${selectedPack.effectiveTo || "open"}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {packs && packs.length > 1 && (
                    <select
                      className={inputClass + " w-auto"} value={selectedPack.id}
                      onChange={(e) => switchPack(packs.find((p) => String(p.id) === e.target.value))}
                      title="Switch pack version"
                    >
                      {packs.map((p) => <option key={p.id} value={p.id}>v{p.version} — {p.status}</option>)}
                    </select>
                  )}
                  <button
                    onClick={() => setShowEditOverview(true)}
                    className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                  >
                    <Pencil size={13} /> Edit
                  </button>
                  <button
                    onClick={handleApprove}
                    title={selectedPack.approvedById ? `Currently approved by user #${selectedPack.approvedById}` : "Not yet approved"}
                    className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                  >
                    <ShieldCheck size={13} /> Approve
                  </button>
                  <select className={inputClass + " w-auto"} value={selectedPack.status} onChange={(e) => changeStatus(e.target.value)}>
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>

              <div className="mb-4 flex items-center gap-1 border-b border-border overflow-x-auto">
                {TABS.map((t) => (
                  <button
                    key={t.key} onClick={() => setTab(t.key)}
                    className={`flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${
                      tab === t.key ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"
                    }`}
                  >
                    <t.icon size={13} /> {t.label}
                  </button>
                ))}
              </div>

              {tab === "components" && (
                <USTaxComponentsTab
                  pack={selectedPack} rates={rates} slabs={slabs}
                  onReload={reloadRatesAndSlabs} onDeleteRate={setDeletingRate}
                  onNavigateTab={setTab}
                />
              )}
              {tab === "incomeTax" && (
                <USIncomeTaxBracketsTab
                  pack={selectedPack} slabs={slabs}
                  onReload={reloadRatesAndSlabs} onDeleteSlab={setDeletingSlab}
                />
              )}
              {tab === "sui" && <USStateSuiSection stateName={stateName} />}
              {tab === "reciprocity" && <USStateReciprocitySection stateName={stateName} />}
              {tab === "sourceEvidence" && <USStateSourceEvidenceNote />}
              {tab === "versionAudit" && <USStateVersionAuditSection pack={selectedPack} />}
            </>
          )}
        </div>
      )}

      {showEditOverview && selectedPack && (
        <EditOverviewModal
          pack={selectedPack} onClose={() => setShowEditOverview(false)}
          onSaved={(updated) => { setShowEditOverview(false); setSelectedPack(updated); onPackUpdated?.(updated); }}
        />
      )}
      {deletingRate && (
        <ConfirmDialog
          title="Delete Contribution Rate" message={`Delete "${deletingRate.label}"? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalContributionRate(deletingRate.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingRate(null);
            reloadRatesAndSlabs();
          }}
          onClose={() => setDeletingRate(null)}
        />
      )}
      {deletingSlab && (
        <ConfirmDialog
          title="Delete Tax Bracket" message={`Delete the "${deletingSlab.rateLabel}" bracket? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalTaxSlab(deletingSlab.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingSlab(null);
            reloadRatesAndSlabs();
          }}
          onClose={() => setDeletingSlab(null)}
        />
      )}
    </div>
  );
}
