import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, Landmark, Coins, CheckCircle2, Users2, GraduationCap } from "lucide-react";
import JurisdictionLayout from "../../components/jurisdiction/JurisdictionLayout";
import SlabsTab from "../../components/jurisdiction/SlabsTab";
import ComplianceConfigModal, { CONFIG_TYPES } from "../../components/jurisdiction/ComplianceConfigModal";

// UK — everything country-specific for this jurisdiction lives in this one
// file, same pattern as INCompliancePage.jsx.
//
// Every Add/Edit modal on this page now goes through the shared, type-
// aware ComplianceConfigModal (components/jurisdiction/ComplianceConfigModal.jsx)
// instead of one generic "Edit Contribution Rate" form — each tab passes
// the configType that actually matches what it's editing (threshold /
// contribution_rate / employee_deduction / tax_slab / ni_category), so
// the fields shown always match the real payroll shape (a threshold
// never shows Employee/Employer %, a Student Loan never shows an
// employer field, etc.). All add/edit state below is LOCAL to each tab
// (not JurisdictionLayout's shared showNewRate/editingRate/showNewSlab/
// editingSlab) precisely so two different tabs can never fight over
// which modal shape a shared "+ Add" click should open. Delete stays on
// JurisdictionLayout's own existing ConfirmDialog/delete-API flow
// throughout (onDeleteRate/onDeleteSlab) — a delete confirmation doesn't
// have a "wrong fields" problem, so there's nothing to gain from a
// bespoke one per type.
//
// PAYE Income Tax Slabs: the sub-jurisdiction case (Scotland today) is
// routed through slabsTabOverride so its Add/Edit modal is the dedicated
// "PAYE Tax Band" form (Min/Max/Rate) below. The NATIONAL pack's own PAYE
// slabs still open the shared, generic SlabFormModal every other
// country's tax-slab tab uses — JurisdictionLayout.jsx (shared infra,
// deliberately not touched here) hard-couples slabsTabOverride's
// isActive() flag to its OWN tab-set restriction, so making it always-
// active for UK would also hide NI Categories/Workplace Pension/Student
// Loans/Thresholds on the national pack. See slabsTabOverride's own
// comment below for the full reasoning.

const isThreshold = (r) => r.flatAmount != null && r.employeeRatePct == null && r.employerRatePct == null;

// Component keys that used to live in "HMRC Statutory Thresholds" but
// have their own dedicated homes now — Workplace Pension for the QE
// limits, Student Loans for every loan/postgraduate threshold.
const PENSION_QE_KEYS = ["pension_qe_lower", "pension_qe_upper"];
const STUDENT_LOAN_KEYS = ["sl_plan1_thresh", "sl_plan2_thresh", "sl_plan4_thresh", "sl_plan5_thresh", "pg_loan_thresh"];

// Student Loan/Postgraduate Loan employee deduction rates are NOT stored
// as a ContributionRate field at all — engine/countries/uk.py's
// _UK_STUDENT_LOAN_PLANS hardcodes them per plan (only the THRESHOLD is
// resolved from the row's flatAmount; the rate never is) — shown here as
// read-only reference so the rate the UI displays always matches what
// the engine actually applies.
const STUDENT_LOAN_PLANS = [
  { componentKey: "sl_plan1_thresh", label: "Plan 1", rate: "9%" },
  { componentKey: "sl_plan2_thresh", label: "Plan 2", rate: "9%" },
  { componentKey: "sl_plan4_thresh", label: "Plan 4", rate: "9%" },
  { componentKey: "sl_plan5_thresh", label: "Plan 5", rate: "9%" },
  { componentKey: "pg_loan_thresh", label: "Postgraduate Loan", rate: "6%" },
];

// ── HMRC Statutory Thresholds ────────────────────────────────────────────
function StatutoryThresholdsTab({ pack, rates, onDeleteRate, onReload, addToast }) {
  const [modal, setModal] = useState(null); // { mode, initialData } | null
  const movedKeys = new Set([...PENSION_QE_KEYS, ...STUDENT_LOAN_KEYS]);
  const thresholds = rates.filter((r) => isThreshold(r) && !movedKeys.has(r.componentKey));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          General statutory thresholds — Personal Allowance and its taper, and the NI Primary/Secondary/Upper thresholds.
        </p>
        <button onClick={() => setModal({ mode: "add", initialData: null })} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
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
                <button onClick={() => setModal({ mode: "edit", initialData: t })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                <button onClick={() => onDeleteRate(t)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
      {modal && (
        <ComplianceConfigModal
          configType={CONFIG_TYPES.THRESHOLD} mode={modal.mode} pack={pack} initialData={modal.initialData}
          componentKey={modal.initialData?.componentKey || ""} lockComponentKey={Boolean(modal.initialData)}
          addToast={addToast} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); onReload(); }}
        />
      )}
    </div>
  );
}

// ── NI Categories ─────────────────────────────────────────────────────────
// NI Category bands (rule_type="NI_BAND") were previously invisible —
// UKCompliancePage's own slabsFilter (below) explicitly excludes them
// from the PAYE Income Tax Slabs tab, and no other tab rendered them.
// Add/Edit now use the dedicated NI_CATEGORY form (NI Category letter,
// Earnings Range, Employee/Employer %) — never Flat Amount, which no
// NI_BAND row in this engine has ever used.
function NICategoriesTab({ pack, slabs, onDeleteSlab, onReload, addToast }) {
  const [modal, setModal] = useState(null);
  const niBands = slabs.filter((s) => s.ruleType === "NI_BAND");
  const byCategory = {};
  niBands.forEach((b) => {
    (byCategory[b.niCategory || "—"] ||= []).push(b);
  });
  const categories = Object.keys(byCategory).sort();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          National Insurance bands by HMRC category letter — employee rate on the left of each row, employer rate on the right.
        </p>
        <button onClick={() => setModal({ mode: "add", initialData: null })} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Band
        </button>
      </div>
      {categories.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">
          No NI category bands configured yet — only a flat National Insurance % applies until bands exist for a category.
        </p>
      ) : (
        categories.map((cat) => (
          <div key={cat} className="rounded-lg border border-border-light p-3">
            <p className="mb-2 text-xs font-bold text-foreground">Category {cat}</p>
            <div className="space-y-1">
              {byCategory[cat]
                .sort((a, b) => Number(a.minAmount) - Number(b.minAmount))
                .map((band) => (
                  <div key={band.id} className="flex items-center justify-between rounded border border-border-light px-2.5 py-1.5 text-xs">
                    <span className="font-mono tabular-nums text-foreground-secondary">
                      £{Number(band.minAmount).toLocaleString()} – {band.maxAmount != null ? `£${Number(band.maxAmount).toLocaleString()}` : "and above"}
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="font-mono tabular-nums text-foreground">Employee {Number(band.ratePct)}%</span>
                      <span className="font-mono tabular-nums text-foreground-muted">Employer {band.employerRatePct != null ? `${Number(band.employerRatePct)}%` : "—"}</span>
                      <button onClick={() => setModal({ mode: "edit", initialData: band })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      <button onClick={() => onDeleteSlab(band)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                    </span>
                  </div>
                ))}
            </div>
          </div>
        ))
      )}
      {modal && (
        <ComplianceConfigModal
          configType={CONFIG_TYPES.NI_CATEGORY} mode={modal.mode} pack={pack} initialData={modal.initialData}
          addToast={addToast} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); onReload(); }}
        />
      )}
    </div>
  );
}

// ── Workplace Pension ────────────────────────────────────────────────────
// Split out of the old combined "NI & Pension Rates" tab — National
// Insurance now lives ONLY in NI Categories; this tab shows nothing but
// pension. "Contribution Rates" is the employer-pension ContributionRate
// row (the one uk.py actually reads for both employee and employer %),
// joined for DISPLAY with the separate "pension_basis" row's text value
// for Calculation Basis, and with the pack's own effective window for
// Effective Period. "Qualifying Earnings" is the two QE threshold rows,
// moved here from HMRC Statutory Thresholds.
const PENSION_BASIS_LABELS = {
  QUALIFYING_EARNINGS: "Qualifying Earnings",
  BASIC_PAY: "Basic Pay",
  PENSIONABLE_EARNINGS: "Pensionable Earnings",
};

function WorkplacePensionContributionRates({ pack, rates, onDeleteRate, onReload, addToast }) {
  const [modal, setModal] = useState(false);
  const pensionRate = rates.find((r) => r.componentKey === "employer-pension");
  const basisRow = rates.find((r) => r.componentKey === "pension_basis");
  const basisLabel = PENSION_BASIS_LABELS[basisRow?.textValue] || basisRow?.textValue || "Qualifying Earnings";
  const employeePct = pensionRate?.employeeRatePct;
  const employerPct = pensionRate?.employerRatePct;
  const totalPct = (employeePct != null || employerPct != null) ? (Number(employeePct || 0) + Number(employerPct || 0)) : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Workplace pension contribution rates for this Compliance Pack.</p>
        <button onClick={() => setModal(true)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
          <Plus size={13} /> Add Contribution
        </button>
      </div>
      {!pensionRate ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No workplace pension rule configured yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Component</th>
                <th className="px-3 py-2">Calculation Basis</th>
                <th className="px-3 py-2">Employee Contribution</th>
                <th className="px-3 py-2">Employer Contribution</th>
                <th className="px-3 py-2">Total Contribution</th>
                <th className="px-3 py-2">Effective Period</th>
                <th className="px-3 py-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-border-light">
                <td className="px-3 py-2"><p className="font-semibold text-foreground">{pensionRate.label}</p><p className="font-mono text-[10px] text-foreground-disabled">{pensionRate.componentKey}</p></td>
                <td className="px-3 py-2 text-foreground-secondary">{basisLabel}</td>
                <td className="px-3 py-2 text-foreground-secondary">{employeePct != null ? `${employeePct}%` : "—"}</td>
                <td className="px-3 py-2 text-foreground-secondary">{employerPct != null ? `${employerPct}%` : "—"}</td>
                <td className="px-3 py-2 font-semibold text-foreground">{totalPct != null ? `${totalPct}%` : "—"}</td>
                <td className="px-3 py-2 text-foreground-secondary whitespace-nowrap">{pack.effectiveFrom || "—"} → {pack.effectiveTo || "open"}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    <button onClick={() => setModal(true)} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                    <button onClick={() => onDeleteRate(pensionRate)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {modal && (
        <ComplianceConfigModal
          configType={CONFIG_TYPES.CONTRIBUTION_RATE} mode={pensionRate ? "edit" : "add"}
          pack={pack} pensionRate={pensionRate} basisRow={basisRow} addToast={addToast}
          onClose={() => setModal(false)}
          onSaved={() => { setModal(false); onReload(); }}
        />
      )}
    </div>
  );
}

function WorkplacePensionQualifyingEarnings({ pack, rates, onDeleteRate, onReload, addToast }) {
  const [modal, setModal] = useState(null);
  const qeRows = PENSION_QE_KEYS
    .map((key) => rates.find((r) => r.componentKey === key))
    .filter(Boolean);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">Qualifying Earnings band used to compute pensionable pay when the calculation basis is "Qualifying Earnings".</p>
        <button
          onClick={() => {
            const missingKey = PENSION_QE_KEYS.find((k) => !rates.some((r) => r.componentKey === k));
            const key = missingKey || PENSION_QE_KEYS[0];
            setModal({ initialData: rates.find((r) => r.componentKey === key) || null, componentKey: key });
          }}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Qualifying Earnings Limit
        </button>
      </div>
      {qeRows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">No Qualifying Earnings limits configured yet.</p>
      ) : (
        <div className="rounded-xl border border-border overflow-hidden">
          {qeRows.map((r, i) => (
            <div key={r.id} className={`flex items-center justify-between px-4 py-3 ${i > 0 ? "border-t border-border-light" : ""}`}>
              <div>
                <p className="text-xs font-semibold text-foreground">{r.label}</p>
                <p className="font-mono text-[10px] text-foreground-disabled">{r.componentKey}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm tabular-nums text-foreground">£{Number(r.flatAmount).toLocaleString()}</span>
                <button onClick={() => setModal({ initialData: r, componentKey: r.componentKey })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                <button onClick={() => onDeleteRate(r)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
      {modal && (
        <ComplianceConfigModal
          configType={CONFIG_TYPES.THRESHOLD} mode={modal.initialData ? "edit" : "add"}
          title={`${modal.initialData ? "Edit" : "Add"} Qualifying Earnings Threshold`}
          description="Configure the earnings limit used for workplace pension calculation."
          pack={pack} initialData={modal.initialData} componentKey={modal.componentKey} lockComponentKey
          defaultLabel={modal.componentKey === "pension_qe_lower" ? "Pension QE Lower Limit" : "Pension QE Upper Limit"}
          addToast={addToast} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); onReload(); }}
        />
      )}
    </div>
  );
}

function WorkplacePensionTab(props) {
  const [subView, setSubView] = useState("rates");
  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-bold text-foreground">Workplace Pension</h4>
        <p className="text-xs text-foreground-muted mt-0.5">Configure workplace pension contribution rates and qualifying earnings limits for this Compliance Pack.</p>
      </div>
      <div className="flex gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {[{ key: "rates", label: "Contribution Rates" }, { key: "qe", label: "Qualifying Earnings" }].map((t) => (
          <button
            key={t.key} onClick={() => setSubView(t.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${subView === t.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {subView === "rates"
        ? <WorkplacePensionContributionRates {...props} />
        : <WorkplacePensionQualifyingEarnings {...props} />}
    </div>
  );
}

// ── Student Loans ─────────────────────────────────────────────────────────
function StudentLoansTab({ pack, rates, onDeleteRate, onReload, addToast }) {
  const [modal, setModal] = useState(null); // { plan, rate, allowPlanChange } | null

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-bold text-foreground">Student Loans</h4>
        <p className="text-xs text-foreground-muted mt-0.5">Configure repayment thresholds and employee deduction rates for UK Student Loan and Postgraduate Loan plans.</p>
      </div>
      <div className="flex justify-end">
        <button
          onClick={() => {
            const unconfigured = STUDENT_LOAN_PLANS.find((p) => !rates.some((r) => r.componentKey === p.componentKey));
            const plan = unconfigured || STUDENT_LOAN_PLANS[0];
            setModal({ plan, rate: rates.find((r) => r.componentKey === plan.componentKey), allowPlanChange: true });
          }}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
        >
          <Plus size={13} /> Add Student Loan Plan
        </button>
      </div>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead className="bg-background text-left text-foreground-muted">
            <tr>
              <th className="px-3 py-2">Loan Plan</th>
              <th className="px-3 py-2">Annual Threshold</th>
              <th className="px-3 py-2">Employee Rate</th>
              <th className="px-3 py-2">Employer Rate</th>
              <th className="px-3 py-2 w-20"></th>
            </tr>
          </thead>
          <tbody>
            {STUDENT_LOAN_PLANS.map((plan) => {
              const rate = rates.find((r) => r.componentKey === plan.componentKey);
              return (
                <tr key={plan.componentKey} className="border-t border-border-light">
                  <td className="px-3 py-2 font-semibold text-foreground">{plan.label}</td>
                  <td className="px-3 py-2 font-mono tabular-nums text-foreground-secondary">
                    {rate?.flatAmount != null ? `£${Number(rate.flatAmount).toLocaleString()}` : "Not configured"}
                  </td>
                  <td className="px-3 py-2 text-foreground-secondary">{plan.rate}</td>
                  <td className="px-3 py-2 text-foreground-disabled">N/A</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => setModal({ plan, rate })} className="rounded p-1 text-foreground-disabled hover:text-primary hover:bg-surface-muted"><Pencil size={12} /></button>
                      {rate && <button onClick={() => onDeleteRate(rate)} className="rounded p-1 text-foreground-disabled hover:text-error hover:bg-error-light"><Trash2 size={12} /></button>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {modal && (
        <ComplianceConfigModal
          configType={CONFIG_TYPES.EMPLOYEE_DEDUCTION} mode={modal.rate ? "edit" : "add"}
          pack={pack} plan={modal.plan} rate={modal.rate} plans={STUDENT_LOAN_PLANS} rates={rates}
          allowPlanChange={modal.allowPlanChange} addToast={addToast}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); onReload(); }}
        />
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

// ── PAYE Income Tax Slabs ────────────────────────────────────────────────
// Always active for UK now (both the national pack AND a sub-jurisdiction
// pack like Scotland) so its own Add/Edit modal can be the dedicated
// "PAYE Tax Band" form — the shared SlabFormModal every other country's
// tax-slab tab still uses (with its Employee/Employer %/Flat Amount/NI
// Category fields, none of which apply to a plain income-tax bracket)
// never appears for UK's own income-tax brackets any more.
function PAYESlabsTab({ pack, slabs, onAdd, onEdit, onDelete }) {
  return (
    <div>
      {pack.jurisdictionState && <InheritedFromNationalBanner />}
      <SlabsTab pack={pack} slabs={slabs} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
    </div>
  );
}

const slabsTabOverride = {
  // Scoped to sub-jurisdiction packs only (Scotland today), NOT always
  // true: JurisdictionLayout.jsx hard-couples this same isActive() flag
  // to restrictTabsTo below (shared infra used by every other country's
  // page too, so it's deliberately not touched here) — making this
  // always-true would also always-restrict the tab set, hiding NI
  // Categories/Workplace Pension/Student Loans/Thresholds on the
  // NATIONAL pack. Net effect: Scotland's Income Tax Rules tab gets the
  // dedicated "PAYE Tax Band" modal below; the national pack's own PAYE
  // Income Tax Slabs tab still opens the shared, generic SlabFormModal
  // (extra Rule Type/State fields, but the same underlying Min/Max/Rate
  // data) — a real, honest limitation of this being a same-file-only
  // refactor rather than a JurisdictionLayout.jsx change.
  isActive: (pack) => Boolean(pack.jurisdictionState),
  label: "Income Tax Rules",
  restrictTabsTo: ["overview", "slabs", "organizations", "audit"],
  renderTab: ({ pack, slabs, onAdd, onEdit, onDelete }) => (
    <PAYESlabsTab pack={pack} slabs={slabs} onAdd={onAdd} onEdit={onEdit} onDelete={onDelete} />
  ),
  renderAddModal: ({ pack, onClose, onSaved, addToast }) => (
    <ComplianceConfigModal configType={CONFIG_TYPES.TAX_SLAB} mode="add" pack={pack} addToast={addToast} onClose={onClose} onSaved={onSaved} />
  ),
  renderEditModal: ({ pack, slab, onClose, onSaved, addToast }) => (
    <ComplianceConfigModal configType={CONFIG_TYPES.TAX_SLAB} mode="edit" pack={pack} initialData={slab} addToast={addToast} onClose={onClose} onSaved={onSaved} />
  ),
  deleteTitle: "Delete PAYE Tax Band",
  deleteMessage: (slab) => `Delete the "${slab.rateLabel}" tax band? This cannot be undone.`,
};

// A sub-jurisdiction pack (Scotland today, England/Wales/Northern
// Ireland the moment a real pack is created for them) only ever shows
// its own Income Tax bands — NI/Pension/Thresholds/Student Loans stay
// national (restrictTabsTo above), matching real HMRC structure.
const ukComplianceConfig = {
  extraTabs: [
    {
      key: "ni-categories", label: "NI Categories", icon: Users2, after: "overview",
      isVisible: (pack) => !pack.jurisdictionState,
      render: (p) => <NICategoriesTab {...p} />,
    },
    {
      key: "workplace-pension", label: "Workplace Pension", icon: Landmark, after: "ni-categories",
      isVisible: (pack) => !pack.jurisdictionState,
      render: (p) => <WorkplacePensionTab {...p} />,
    },
    {
      key: "student-loans", label: "Student Loans", icon: GraduationCap, after: "workplace-pension",
      isVisible: (pack) => !pack.jurisdictionState,
      render: (p) => <StudentLoansTab {...p} />,
    },
    {
      key: "thresholds", label: "HMRC Statutory Thresholds", icon: Coins,
      isVisible: (pack) => !pack.jurisdictionState,
      render: (p) => <StatutoryThresholdsTab {...p} />,
    },
  ],
  slabsTabOverride,
  // The generic Contribution Rates tab is fully replaced by the tabs
  // above; Versions isn't part of the requested tab set for this jurisdiction.
  hiddenTabs: ["rates", "versions"],
  slabsLabel: "PAYE Income Tax Slabs",
  countryLevelLabel: "UK National (Personal Allowance, NI, Pension, Student Loans)",
  // Scotland already has real data and appears automatically. England/
  // Wales/Northern Ireland are offered here so all four constituent
  // nations are genuinely selectable today — selecting one and using
  // "New Tax" creates its real pack, exactly how Scotland's was created.
  additionalStateOptions: ["England", "Wales", "Northern Ireland"],
  // NI Category bands (Section D) live as TaxSlab rows too (rule_type=
  // "NI_BAND") — filtered out here so they don't show up as bogus extra
  // brackets in the PAYE Income Tax Slabs table; they're edited from
  // their own NI Categories tab instead.
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
        // Push (not replace) — see INCompliancePage.jsx's matching comment.
        navigate(state ? `/super-admin/compliance/united-kingdom/${encodeURIComponent(state)}` : "/super-admin/compliance/united-kingdom")
      }
      {...ukComplianceConfig}
    />
  );
}
