// DEPRECATION NOTICE (Phase 9 cleanup inventory, see
// backend/scripts/HIERARCHY_V2_CLEANUP_INVENTORY.md): companion to
// EnterpriseJurisdictionsTab.jsx — same eventual fold-in target (the
// hierarchy engine's org-assignment UI), same "not yet, zero orgs cut
// over" status. Fully live, not touched here.
import { useState, useEffect, useCallback, useMemo } from "react";
import {
  ArrowLeft, Loader2, CheckCircle2, ShieldCheck, FileText, Sparkles,
  Settings2, Percent, Users, ListChecks, AlertTriangle, CircleDashed,
  Upload, Plus, Info, ClipboardList,
} from "lucide-react";
import TaxSlabTable from "../TaxSlabTable";
import { useToast } from "../../ToastContext";
import {
  addEnterpriseJurisdiction, updateEnterpriseJurisdiction, verifyEnterpriseJurisdiction,
  getEnterpriseContributionRates, updateEnterpriseContributionRate,
} from "../../../../service/payrollService";

const inputClass =
  "w-full h-10 rounded-[10px] border border-border bg-background px-3.5 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-category-teal/30 disabled:opacity-60 transition-all duration-150";
const textareaClass =
  "w-full rounded-[10px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-category-teal/30 disabled:opacity-60 transition-all duration-150";

// ── Shared presentational pieces ─────────────────────────────────────────

function Card({ title, icon: Icon, subtitle, actions, children }) {
  return (
    <div className="bg-surface border border-border rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-6 py-4 border-b border-border">
        <div className="flex items-center gap-2.5 min-w-0">
          {Icon && (
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-category-teal/10">
              <Icon size={15} className="text-category-teal" />
            </div>
          )}
          <div className="min-w-0">
            <p className="text-[14px] font-bold text-foreground truncate">{title}</p>
            {subtitle && <p className="text-[11px] text-foreground-muted truncate">{subtitle}</p>}
          </div>
        </div>
        {actions}
      </div>
      <div className="p-6">{children}</div>
    </div>
  );
}

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-semibold text-foreground-muted mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-foreground-muted mt-1">{hint}</span>}
    </label>
  );
}

function PercentInput({ value, onChange, disabled, placeholder }) {
  return (
    <div className="relative">
      <input
        type="number" step="0.01" disabled={disabled}
        // Native up/down steppers make going from e.g. 12.0000 to 0.0001 take
        // forever one click at a time — hidden here since typing/pasting the
        // value directly is the only realistic way to edit these rates.
        className={inputClass + " text-right pr-7 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
      />
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] font-semibold text-foreground-muted">%</span>
    </div>
  );
}

const STATUS_META = {
  draft: { label: "Draft", tone: "amber" },
  configured: { label: "Configured", tone: "blue" },
  verified: { label: "Verified", tone: "green" },
};
const TONE_CLASSES = {
  amber: "bg-warning/10 text-warning border-warning/20",
  blue: "bg-info/10 text-info border-info/20",
  green: "bg-primary/10 text-primary border-primary/20",
};

function StatusBadge({ status }) {
  const meta = STATUS_META[status] || STATUS_META.draft;
  return (
    <span className={`inline-flex items-center px-3 py-1.5 rounded-full border text-[12px] font-bold whitespace-nowrap ${TONE_CLASSES[meta.tone]}`}>
      {meta.label}
    </span>
  );
}

// ── Main component ───────────────────────────────────────────────────────
// All state, handlers, and API calls below are unchanged from the original
// drawer implementation — only the layout/markup around them was redesigned.

export default function JurisdictionConfigPanel({ meta, jurisdiction, onClose, onSaved, canEdit = true }) {
  const { addToast } = useToast();
  const [row, setRow] = useState(jurisdiction || null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rates, setRates] = useState([]);
  const [savingRateKey, setSavingRateKey] = useState(null);

  const [general, setGeneral] = useState({ payrollFrequency: "Monthly", timeZone: "" });
  const [compliance, setCompliance] = useState({
    governmentFilingSchedule: "", requiredReports: "", payrollRegistrationNumbers: "", taxIdentificationNumbers: "",
  });
  const [rules, setRules] = useState({ overtime: "", leave: "", holidayCalendar: "", terminationRules: "" });

  // UI-only state — drives the progress/validation panels, never sent anywhere.
  const [taxSlabStatus, setTaxSlabStatus] = useState({ loadState: "loading", activeSlabCount: 0 });
  const [showValidation, setShowValidation] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let current = jurisdiction;
      if (!current) {
        current = await addEnterpriseJurisdiction(meta.code);
      }
      setRow(current);
      if (current.generalConfig) setGeneral((g) => ({ ...g, ...current.generalConfig }));
      if (current.complianceConfig) {
        setCompliance((c) => ({
          ...c,
          ...current.complianceConfig,
          requiredReports: Array.isArray(current.complianceConfig.requiredReports)
            ? current.complianceConfig.requiredReports.join(", ")
            : current.complianceConfig.requiredReports || "",
        }));
      }
      if (current.payrollRulesConfig) setRules((r) => ({ ...r, ...current.payrollRulesConfig }));
      const rateRows = await getEnterpriseContributionRates(current.id);
      setRates(rateRows);
    } finally {
      setLoading(false);
    }
  }, [meta.code, jurisdiction]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRateChange = (componentKey, field, value) => {
    setRates((prev) => prev.map((r) => (r.componentKey === componentKey ? { ...r, [field]: value } : r)));
  };

  // A field is only ever "" while someone is actively typing in the
  // controlled input — once loaded from the server an unset rate is
  // `null`/`undefined`, not "". Treating only "" as blank (the original
  // bug) sent Number(null) === 0 for every untouched field on the row,
  // silently zeroing it out on every save.
  const toRateValueOrNull = (value) => (value === "" || value === null || value === undefined ? null : Number(value));

  const handleSaveRate = async (rate) => {
    setSavingRateKey(rate.componentKey);
    try {
      const updated = await updateEnterpriseContributionRate(row.id, rate.componentKey, {
        employeeRatePct: toRateValueOrNull(rate.employeeRatePct),
        employerRatePct: toRateValueOrNull(rate.employerRatePct),
        flatAmount: toRateValueOrNull(rate.flatAmount),
      });
      // Reconcile with whatever the server actually persisted, rather than
      // trusting the locally-typed strings stayed in sync.
      setRates((prev) => prev.map((r) => (r.componentKey === rate.componentKey ? { ...r, ...updated } : r)));
      addToast?.(`${rate.label} saved.`, "success");
    } catch (err) {
      addToast?.(err?.message || `Failed to save ${rate.label}.`, "error");
    } finally {
      setSavingRateKey(null);
    }
  };

  const handleSaveSections = async (markConfigured = false) => {
    setSaving(true);
    try {
      const updated = await updateEnterpriseJurisdiction(row.id, {
        generalConfig: general,
        complianceConfig: {
          ...compliance,
          requiredReports: compliance.requiredReports
            ? compliance.requiredReports.split(",").map((s) => s.trim()).filter(Boolean)
            : [],
        },
        payrollRulesConfig: rules,
        markConfigured,
      });
      setRow(updated);
      onSaved?.(updated);
    } finally {
      setSaving(false);
    }
  };

  const handleVerify = async () => {
    setSaving(true);
    try {
      const updated = await verifyEnterpriseJurisdiction(row.id);
      setRow(updated);
      onSaved?.(updated);
    } finally {
      setSaving(false);
    }
  };

  // ── Derived, read-only completeness checklist (display only — never
  // sent to the backend, never gates any action). ──
  const checklist = useMemo(() => {
    const detailsDone = Boolean(general.payrollFrequency && general.timeZone.trim());
    const taxSlabsDone = taxSlabStatus.activeSlabCount > 0;
    const ratesWithValue = rates.filter((r) => (r.employeeRatePct !== "" && r.employeeRatePct != null) || (r.employerRatePct !== "" && r.employerRatePct != null));
    const contributionsDone = rates.length > 0 && ratesWithValue.length === rates.length;
    const contributionsPartial = ratesWithValue.length > 0 && !contributionsDone;
    const complianceDone = Boolean(compliance.governmentFilingSchedule.trim() && compliance.payrollRegistrationNumbers.trim() && compliance.taxIdentificationNumbers.trim());
    const compliancePartial = !complianceDone && Boolean(compliance.governmentFilingSchedule.trim() || compliance.payrollRegistrationNumbers.trim() || compliance.taxIdentificationNumbers.trim());
    const reportsDone = Boolean(compliance.requiredReports.trim());

    const items = [
      { key: "details", label: "Jurisdiction Details", done: detailsDone },
      { key: "taxSlabs", label: "Tax Slabs", done: taxSlabsDone },
      { key: "contributions", label: "Contributions", done: contributionsDone, partial: contributionsPartial },
      { key: "compliance", label: "Compliance Rules", done: complianceDone, partial: compliancePartial },
      { key: "reports", label: "Reports", done: reportsDone },
    ];
    const credit = items.reduce((sum, i) => sum + (i.done ? 1 : i.partial ? 0.5 : 0), 0);
    const pct = Math.round((credit / items.length) * 100);
    return { items, pct };
  }, [general, taxSlabStatus, rates, compliance]);

  const missingItems = checklist.items.filter((i) => !i.done);

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-background">
      {/* ── Header (fixed) ── */}
      <header className="shrink-0 flex items-center justify-between gap-4 border-b border-border bg-surface px-6 py-4">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onClose}
            title="Back"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-border bg-surface-muted text-foreground-muted hover:border-category-teal hover:text-category-teal transition-all duration-200"
          >
            <ArrowLeft size={16} />
          </button>
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-surface-muted text-[20px] leading-none"
            title={meta.code}
          >
            {meta.flag}
          </span>
          <div className="min-w-0">
            <h1 className="text-[17px] font-bold text-foreground truncate">{meta.name}</h1>
            <p className="text-[12px] text-foreground-muted truncate">
              {meta.code} &middot; {meta.currency} &middot; Tax Year {meta.financialYear}
            </p>
          </div>
        </div>
        <StatusBadge status={row?.status} />
      </header>

      {/* ── Content (scrolls) ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[1440px] mx-auto p-6 lg:p-8">
          {loading ? (
            <div className="flex items-center justify-center py-32">
              <Loader2 size={24} className="animate-spin text-category-teal" />
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6 items-start">
              {/* ── Left column: main configuration ── */}
              <div className="space-y-6 min-w-0">
                <Card title="General" icon={Settings2} subtitle="Payroll cadence and locale for this jurisdiction">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field label="Payroll Frequency">
                      <select
                        className={inputClass}
                        disabled={!canEdit}
                        value={general.payrollFrequency}
                        onChange={(e) => setGeneral({ ...general, payrollFrequency: e.target.value })}
                      >
                        {["Weekly", "Bi-Weekly", "Semi-Monthly", "Monthly"].map((f) => (
                          <option key={f} value={f}>{f}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Time Zone">
                      <input
                        className={inputClass}
                        disabled={!canEdit}
                        placeholder="e.g. America/New_York"
                        value={general.timeZone}
                        onChange={(e) => setGeneral({ ...general, timeZone: e.target.value })}
                      />
                    </Field>
                  </div>
                </Card>

                <Card title="Tax Slabs" icon={Percent} subtitle="Live rates the payroll engine calculates against, plus anything extracted from uploaded documents">
                  <div className="space-y-4">
                    {taxSlabStatus.loadState === "ready" && taxSlabStatus.activeSlabCount === 0 && (
                      <div className="rounded-[14px] border border-dashed border-border bg-background px-6 py-8 text-center">
                        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-category-teal/10">
                          <Percent size={20} className="text-category-teal" />
                        </div>
                        <p className="text-[14px] font-bold text-foreground">No Tax Slabs Configured</p>
                        <p className="text-[12px] text-foreground-muted mt-1 mb-4">
                          Upload a compliance document to auto-extract slabs, or add one manually below.
                        </p>
                        <div className="flex items-center justify-center gap-2.5">
                          <button
                            onClick={onClose}
                            title="Closes this workspace so you can open the Documents tab"
                            className="flex items-center gap-2 rounded-[10px] border border-border bg-surface px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:border-category-teal hover:text-category-teal transition-all duration-200"
                          >
                            <Upload size={14} /> Upload Compliance Document
                          </button>
                          <button
                            disabled
                            title="Coming soon"
                            className="flex items-center gap-2 rounded-[10px] border border-border bg-surface px-4 py-2 text-[13px] font-semibold text-foreground-muted opacity-60 cursor-not-allowed"
                          >
                            <Plus size={14} /> Add Tax Slab Manually
                          </button>
                        </div>
                      </div>
                    )}
                    <TaxSlabTable country={meta.code} onStatusChange={setTaxSlabStatus} />
                  </div>
                </Card>

                <Card title="Employer &amp; Employee Contributions" icon={Users} subtitle="Statutory contribution rates for this jurisdiction">
                  {rates.length === 0 ? (
                    <p className="text-[13px] text-foreground-muted">No contribution components for this jurisdiction.</p>
                  ) : (
                    <div className="space-y-3">
                      {rates.map((r) => (
                        <div
                          key={r.componentKey}
                          className="grid grid-cols-1 sm:grid-cols-[1fr_140px_140px_auto] items-center gap-3 rounded-[12px] bg-background px-4 py-3"
                        >
                          <span className="text-[13px] font-semibold text-foreground truncate">{r.label}</span>
                          <PercentInput
                            disabled={!canEdit}
                            placeholder="Employee"
                            value={r.employeeRatePct ?? ""}
                            onChange={(e) => handleRateChange(r.componentKey, "employeeRatePct", e.target.value)}
                          />
                          <PercentInput
                            disabled={!canEdit}
                            placeholder="Employer"
                            value={r.employerRatePct ?? ""}
                            onChange={(e) => handleRateChange(r.componentKey, "employerRatePct", e.target.value)}
                          />
                          <button
                            disabled={!canEdit || savingRateKey === r.componentKey}
                            onClick={() => handleSaveRate(r)}
                            className="flex items-center justify-center gap-1.5 rounded-[10px] bg-category-teal/10 px-4 py-2 text-[12px] font-bold text-category-teal hover:bg-category-teal/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            {savingRateKey === r.componentKey && <Loader2 size={12} className="animate-spin" />}
                            {savingRateKey === r.componentKey ? "Saving…" : "Save"}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>

                <Card title="Compliance Settings" icon={ShieldCheck} subtitle="Registration and filing identifiers">
                  <div className="space-y-4">
                    <Field label="Government Filing Schedule">
                      <textarea
                        rows={2} disabled={!canEdit} className={textareaClass}
                        value={compliance.governmentFilingSchedule}
                        onChange={(e) => setCompliance({ ...compliance, governmentFilingSchedule: e.target.value })}
                      />
                    </Field>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <Field label="Payroll Registration Numbers">
                        <input
                          className={inputClass} disabled={!canEdit}
                          value={compliance.payrollRegistrationNumbers}
                          onChange={(e) => setCompliance({ ...compliance, payrollRegistrationNumbers: e.target.value })}
                        />
                      </Field>
                      <Field label="Tax Identification Numbers">
                        <input
                          className={inputClass} disabled={!canEdit}
                          value={compliance.taxIdentificationNumbers}
                          onChange={(e) => setCompliance({ ...compliance, taxIdentificationNumbers: e.target.value })}
                        />
                      </Field>
                    </div>
                  </div>
                </Card>

                <Card title="Required Reports" icon={FileText} subtitle="Statutory reports this jurisdiction must file">
                  <Field label="Required Reports (comma-separated)">
                    <input
                      className={inputClass} disabled={!canEdit}
                      placeholder="e.g. Form 24Q, Annual Return"
                      value={compliance.requiredReports}
                      onChange={(e) => setCompliance({ ...compliance, requiredReports: e.target.value })}
                    />
                  </Field>
                </Card>

                <Card title="Payroll Rules" icon={ListChecks} subtitle="Overtime, leave, holidays, and termination handling">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field label="Overtime">
                      <textarea rows={2} disabled={!canEdit} className={textareaClass} value={rules.overtime} onChange={(e) => setRules({ ...rules, overtime: e.target.value })} />
                    </Field>
                    <Field label="Leave">
                      <textarea rows={2} disabled={!canEdit} className={textareaClass} value={rules.leave} onChange={(e) => setRules({ ...rules, leave: e.target.value })} />
                    </Field>
                    <Field label="Holiday Calendar">
                      <textarea rows={2} disabled={!canEdit} className={textareaClass} value={rules.holidayCalendar} onChange={(e) => setRules({ ...rules, holidayCalendar: e.target.value })} />
                    </Field>
                    <Field label="Termination Rules">
                      <textarea rows={2} disabled={!canEdit} className={textareaClass} value={rules.terminationRules} onChange={(e) => setRules({ ...rules, terminationRules: e.target.value })} />
                    </Field>
                  </div>
                </Card>
              </div>

              {/* ── Right column: context, status, summary ── */}
              <div className="space-y-6 min-w-0">
                <Card title="Uploaded Compliance Document" icon={FileText}>
                  <p className="text-[12px] text-foreground-muted">
                    No document is linked to this jurisdiction from this screen. Upload and manage compliance
                    documents from the Documents tab — extracted tax slabs will then appear above automatically.
                  </p>
                </Card>

                <Card title="AI Extraction Status" icon={Sparkles}>
                  <div className="flex items-center gap-2.5">
                    <CircleDashed size={16} className="text-foreground-muted" />
                    <p className="text-[12px] text-foreground-muted">No extraction run yet for this jurisdiction.</p>
                  </div>
                </Card>

                <Card title="Configuration Summary" icon={ClipboardList}>
                  <dl className="space-y-2.5">
                    {[
                      ["Payroll Frequency", general.payrollFrequency || "—"],
                      ["Time Zone", general.timeZone || "—"],
                      ["Active Tax Slabs", taxSlabStatus.activeSlabCount],
                      ["Contribution Components", rates.length],
                      ["Required Reports", compliance.requiredReports ? compliance.requiredReports.split(",").filter((s) => s.trim()).length : 0],
                    ].map(([label, value]) => (
                      <div key={label} className="flex items-center justify-between gap-3 text-[12px]">
                        <dt className="text-foreground-muted">{label}</dt>
                        <dd className="font-semibold text-foreground text-right">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>

                {showValidation && (
                  <Card title="Validation" icon={AlertTriangle}>
                    {missingItems.length === 0 ? (
                      <div className="flex items-center gap-2 text-[13px] font-semibold text-primary">
                        <CheckCircle2 size={16} /> Everything looks complete.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <p className="text-[12px] text-foreground-muted">Not yet complete:</p>
                        {missingItems.map((i) => (
                          <div key={i.key} className="flex items-center gap-2 text-[12px] font-semibold text-warning">
                            <AlertTriangle size={13} /> {i.label}
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                )}

                <Card title="Configuration Progress" icon={CheckCircle2}>
                  <div className="space-y-2.5 mb-4">
                    {checklist.items.map((i) => (
                      <div key={i.key} className="flex items-center gap-2.5 text-[13px]">
                        {i.done ? (
                          <CheckCircle2 size={15} className="text-primary shrink-0" />
                        ) : i.partial ? (
                          <AlertTriangle size={15} className="text-warning shrink-0" />
                        ) : (
                          <CircleDashed size={15} className="text-foreground-muted shrink-0" />
                        )}
                        <span className={i.done ? "text-foreground font-semibold" : "text-foreground-muted"}>
                          {i.label}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="h-2 bg-surface-muted rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-300"
                      style={{ width: `${checklist.pct}%` }}
                    />
                  </div>
                  <p className="text-[11px] font-bold text-foreground-muted mt-2 text-right">{checklist.pct}% Complete</p>
                </Card>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer (fixed) ── */}
      {!loading && (
        <footer className="shrink-0 flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface px-6 py-4">
          <div className="flex items-center gap-2 text-[12px] text-foreground-muted">
            <Info size={13} />
            {checklist.pct}% complete
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => setShowValidation(true)}
              className="flex items-center gap-2 rounded-[10px] border border-border bg-surface-muted px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:border-category-teal hover:text-category-teal transition-all duration-200"
            >
              <ListChecks size={14} /> Validate
            </button>
            {canEdit && (
              <button
                onClick={() => handleSaveSections(false)}
                disabled={saving}
                className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted transition-colors disabled:opacity-60"
              >
                Save Draft
              </button>
            )}
            {canEdit && row?.status === "draft" && (
              <button
                onClick={() => handleSaveSections(true)}
                disabled={saving}
                className="flex items-center gap-2 rounded-[10px] bg-info px-4 py-2 text-[13px] font-bold text-white hover:bg-info transition-colors disabled:opacity-60"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                Mark as Configured
              </button>
            )}
            {canEdit && row?.status === "configured" && (
              <button
                onClick={handleVerify}
                disabled={saving}
                className="flex items-center gap-2 rounded-[10px] bg-primary px-4 py-2 text-[13px] font-bold text-white hover:bg-primary-hover transition-colors disabled:opacity-60"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
                Verify
              </button>
            )}
          </div>
        </footer>
      )}
    </div>
  );
}
