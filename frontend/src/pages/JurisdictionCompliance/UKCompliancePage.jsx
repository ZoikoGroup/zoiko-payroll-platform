import { useParams, useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, Landmark, Coins, CheckCircle2 } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import RatesTab from "../../components/jurisdiction/RatesTab";
import SlabsTab from "../../components/jurisdiction/SlabsTab";
import SlabFormModal from "../../components/jurisdiction/SlabFormModal";

// UK — everything country-specific for this jurisdiction lives in this one
// file, same pattern as INCompliancePage.jsx. HMRC's real structure splits
// cleanly into two shapes that were previously crammed into one generic
// Contribution Rates table: percentage-based NI/Pension rates, and flat
// monetary statutory thresholds (Personal Allowance, NI thresholds,
// Student/Postgraduate Loan thresholds) — both are still plain
// ContributionRate rows underneath (no schema change), just split by shape
// across two tabs instead of one. PAYE Income Tax Slabs is the existing
// generic Tax Slabs tab, only relabeled — it already renders whatever real
// TaxSlab rows exist for the selected pack (the national 4-band matrix, or
// Scotland's real 6-band matrix once Scotland is selected, or any number
// of brackets any other sub-jurisdiction ends up with), so the "dynamic
// regional matrix" behaviour needs no new code here.
//
// UK NATIONAL vs sub-jurisdiction (England/Scotland/Wales/Northern
// Ireland) is decided purely by whether the selected pack has a
// jurisdictionState — no hardcoded jurisdiction name anywhere in this
// file either. A sub-jurisdiction pack is income-tax-only (NI/Pension/
// Thresholds live at the national level, matching real HMRC structure —
// National Insurance isn't devolved), so its tab set narrows to
// Overview/Income Tax/Organizations/Audit and shows which national rules
// it inherits.

// A row is "percentage-based" (NI & Pension Rates) if either rate-pct field
// is set; "a statutory threshold" if only flatAmount is set. This mirrors
// exactly what's already stored — filtering, not a schema change.
const isPercentageRate = (r) => r.employeeRatePct != null || r.employerRatePct != null;
const isThreshold = (r) => r.flatAmount != null && r.employeeRatePct == null && r.employerRatePct == null;

function NIPensionRatesTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  return (
    <RatesTab
      pack={pack} rates={rates.filter(isPercentageRate)}
      onAdd={onAddRate} onEdit={onEditRate} onDelete={onDeleteRate}
    />
  );
}

function StatutoryThresholdsTab({ rates, onAddRate, onEditRate, onDeleteRate }) {
  const thresholds = rates.filter(isThreshold);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          Statutory monetary thresholds — Personal Allowance, NI thresholds, Student/Postgraduate Loan thresholds.
        </p>
        <button onClick={onAddRate} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Threshold
        </button>
      </div>
      {thresholds.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No statutory thresholds yet.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {thresholds.map((t) => (
            <div key={t.id} className="flex items-center justify-between rounded-lg border border-border-light p-3">
              <div>
                <p className="text-xs font-semibold text-foreground">{t.label}</p>
                <p className="font-mono text-[10px] text-foreground-disabled">{t.componentKey}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm tabular-nums text-foreground">£{Number(t.flatAmount).toLocaleString()}</span>
                <button onClick={() => onEditRate(t)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                <button onClick={() => onDeleteRate(t)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const INHERITED_NATIONAL_RULES = ["Personal Allowance", "National Insurance", "Student Loan Rules", "Statutory Payments"];

function InheritedFromNationalBanner() {
  return (
    <div className="mb-3 rounded-lg border border-border-light bg-surface-muted/50 p-3">
      <p className="text-xs font-semibold text-foreground-secondary mb-1.5">Inherited from UK National</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {INHERITED_NATIONAL_RULES.map((rule) => (
          <span key={rule} className="flex items-center gap-1 text-xs text-foreground-muted">
            <CheckCircle2 size={12} className="text-success" /> {rule}
          </span>
        ))}
      </div>
    </div>
  );
}

// A sub-jurisdiction pack (any jurisdictionState — Scotland today, England/
// Wales/Northern Ireland the moment a real pack is created for them)
// overrides ONLY its own Income Tax bands; NI/Pension/Thresholds stay
// national. Reuses the generic SlabsTab/SlabFormModal unchanged — this
// override adds the inheritance banner and narrows the tab set, nothing else.
const slabsTabOverride = {
  isActive: (pack) => Boolean(pack.jurisdictionState),
  label: "Income Tax Rules",
  restrictTabsTo: ["overview", "slabs", "organizations", "audit"],
  renderTab: ({ pack, slabs, onAdd, onEdit, onDelete }) => (
    <div>
      <InheritedFromNationalBanner />
      <SlabsTab pack={pack} slabs={slabs} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
    </div>
  ),
  renderAddModal: ({ pack, onClose, onSaved }) => <SlabFormModal pack={pack} onClose={onClose} onSaved={onSaved} />,
  renderEditModal: ({ pack, slab, onClose, onSaved }) => <SlabFormModal pack={pack} slab={slab} onClose={onClose} onSaved={onSaved} />,
  deleteTitle: "Delete Tax Bracket",
  deleteMessage: (slab) => `Delete the "${slab.rateLabel}" bracket? This cannot be undone.`,
};

// Both extra tabs reuse the existing RateFormModal/ConfirmDialog flow
// (via onAddRate/onEditRate/onDeleteRate, wired by JurisdictionLayout) —
// a threshold is just a ContributionRate row with only flatAmount set, so
// no new modal is needed for either tab. Both are national-only — NI/
// Pension/Thresholds aren't devolved, so a sub-jurisdiction pack never
// shows them (matches slabsTabOverride's restrictTabsTo above).
const ukComplianceConfig = {
  extraTabs: [
    {
      key: "ni-pension", label: "NI & Pension Rates", icon: Landmark, after: "overview",
      isVisible: (pack) => !pack.jurisdictionState,
      render: (p) => <NIPensionRatesTab {...p} />,
    },
    {
      key: "thresholds", label: "HMRC Statutory Thresholds", icon: Coins,
      isVisible: (pack) => !pack.jurisdictionState,
      render: (p) => <StatutoryThresholdsTab {...p} />,
    },
  ],
  slabsTabOverride,
  // The generic Contribution Rates tab is fully replaced by NI & Pension
  // Rates + HMRC Statutory Thresholds above; Versions isn't part of the
  // requested tab set for this jurisdiction.
  hiddenTabs: ["rates", "versions"],
  slabsLabel: "PAYE Income Tax Slabs",
  countryLevelLabel: "UK National (Personal Allowance, NI, Pension, Student Loans)",
  // Scotland already has real data and appears automatically. England/
  // Wales/Northern Ireland are offered here so all four constituent
  // nations are genuinely selectable today — selecting one and using
  // "New Tax" creates its real pack, exactly how Scotland's was created.
  // Never fabricates jurisdiction data, only the option to configure it.
  additionalStateOptions: ["England", "Wales", "Northern Ireland"],
  // NI Category bands (Section D) live as TaxSlab rows too (rule_type=
  // "NI_BAND", so the engine can filter them out of a country's own
  // income-tax bracket loop) — filtered out here for the same reason, so
  // they don't show up as bogus extra brackets in the PAYE Income Tax
  // Slabs table. Not yet independently editable through this UI (only
  // seeded via the Category A migration) — a small NI_BAND-specific form
  // would be the natural next step whenever a second category is needed.
  slabsFilter: (slabs) => slabs.filter((s) => s.ruleType !== "NI_BAND"),
};

export default function UKCompliancePage() {
  const { jurisdiction } = useParams();
  const navigate = useNavigate();
  return (
    <JurisdictionLayout
      country="UK" countryName="United Kingdom"
      initialState={jurisdiction ? decodeURIComponent(jurisdiction) : ""}
      onStateChange={(state) =>
        navigate(state ? `/super-admin/compliance/united-kingdom/${encodeURIComponent(state)}` : "/super-admin/compliance/united-kingdom", { replace: true })
      }
      {...ukComplianceConfig}
    />
  );
}
