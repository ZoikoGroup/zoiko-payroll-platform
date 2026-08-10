import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Settings, ChevronDown, Users, Plug, CalendarClock, Lock } from "lucide-react";
import { useToast } from "../ToastContext";
import EnterpriseConfirmModal from "./EnterpriseConfirmModal";
import PayrollEmailSettingsPanel from "./PayrollEmailSettingsPanel";
import {
  getActivePolicy,
  updatePolicy,
  enablePolicyIntegration,
  disablePolicyIntegration,
  CALCULATION_MODE_LABELS,
  INTEGRATION_LABELS,
  EMPLOYEE_CATEGORY_LABELS,
  ENTERPRISE_STATUS_LABELS,
} from "../../../service/payrollService";
import { usePayrollSetup } from "../PayrollSetupContext";

const tabs = ["General", "Employee Categories", "Leave & Overtime", "Integrations"];

const INTEGRATION_CATEGORY_ORDER = ["attendance", "banking", "notifications"];
const INTEGRATION_CATEGORY_LABELS = {
  attendance: "Attendance",
  banking: "Banking",
  notifications: "Notifications",
};

// Providers that are locked from editing for product/rollout reasons.
// `forceOff` = the toggle is shown off and can't be enabled (not yet available).
// !forceOff  = the provider keeps its current on/off state but can't be changed.
const INTEGRATION_STATUS = {
  biometric: {
    label: "Coming Soon", tone: "amber", forceOff: true,
    tooltip: "Biometric attendance integration is coming soon and can't be enabled yet.",
  },
  zoiko_time: {
    label: "Under Maintenance", tone: "amber", forceOff: false,
    tooltip: "Zoiko Time integration is under maintenance. Editing is temporarily disabled.",
  },
  bank_api: {
    label: "Under Production", tone: "blue", forceOff: true,
    tooltip: "Bank API integration is under production and isn't available yet.",
  },
  csv_export: {
    label: "Coming Soon", tone: "amber", forceOff: true,
    tooltip: "CSV Bank Export is coming soon.",
  },
  whatsapp: {
    label: "Coming Soon", tone: "amber", forceOff: true,
    tooltip: "WhatsApp notifications are coming soon and can't be enabled yet.",
  },
  sms: {
    label: "Coming Soon", tone: "amber", forceOff: true,
    tooltip: "SMS notifications are coming soon and can't be enabled yet.",
  },
  slack: {
    label: "Coming Soon", tone: "amber", forceOff: true,
    tooltip: "Slack notifications are coming soon and can't be enabled yet.",
  },
  teams: {
    label: "Coming Soon", tone: "amber", forceOff: true,
    tooltip: "Microsoft Teams notifications are coming soon and can't be enabled yet.",
  },
};

function StatusBadge({ label, tone = "amber" }) {
  const toneClasses = {
    amber: "bg-[#F8A60A]/10 text-[#F8A60A]",
    blue: "bg-[#35B6F5]/10 text-[#35B6F5]",
    green: "bg-[#19C58A]/10 text-[#19C58A]",
    gray: "bg-[#9E9690]/10 text-[#9E9690]",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold whitespace-nowrap ${toneClasses[tone] || toneClasses.amber}`}>
      {label}
    </span>
  );
}

// ── Small shared UI bits ─────────────────────────────────────────────

function Toggle({ checked, onChange, disabled = false, title }) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200 ${
        checked ? "bg-[#FF6E86]" : "bg-[#E5E0D9] dark:bg-[#38312D]"
      } ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200 ${
          checked ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function Card({ children, className = "" }) {
  return (
    <div
      className={`rounded-[16px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#221D1A] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] ${className}`}
    >
      {children}
    </div>
  );
}

function ExpandableCard({ title, subtitle, badge, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card className="!p-0 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <div>
          <p className="text-[14px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{title}</p>
          {subtitle && <p className="text-[12px] text-[#9E9690] mt-0.5">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-3">
          {badge}
          <ChevronDown
            size={18}
            className={`text-[#9E9690] transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </div>
      </button>
      {open && (
        <div className="border-t border-[#E5E0D9] dark:border-[#38312D] px-5 py-4 space-y-4">{children}</div>
      )}
    </Card>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-2 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:ring-2 focus:ring-[#FF6E86]/30";

// ── Main page ─────────────────────────────────────────────────────────

export default function PayrollPolicyPage() {
  const { addToast } = useToast();
  const { refresh: refreshPayrollSetup } = usePayrollSetup();
  const navigate = useNavigate();
  const [policy, setPolicy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState(0);
  const [showEnterpriseModal, setShowEnterpriseModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getActivePolicy();
      setPolicy(data);
      if (data?.calculationMode) localStorage.setItem("zoiko_payroll_calc_mode", data.calculationMode);
    } catch {
      addToast?.("Failed to load payroll policy.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSaveGeneral = async (patch) => {
    if (!policy) return;
    setSaving(true);
    try {
      const updated = await updatePolicy(policy.id, patch);
      // Merge into the existing policy object rather than replacing it
      // wholesale — keeps this a plain data update (tab/scroll/any other
      // page-local state untouched) instead of swapping in a brand new
      // object identity for the whole page on every save.
      setPolicy((prev) => ({ ...prev, ...updated }));
      if (updated?.calculationMode) localStorage.setItem("zoiko_payroll_calc_mode", updated.calculationMode);
      // Refresh the shared module-wide context so the onboarding gate (and
      // every other sub-module reading calc mode from it) picks up
      // "configured" immediately, without a reload.
      refreshPayrollSetup();
      addToast?.("Policy updated.", "success");
    } catch {
      addToast?.("Failed to update policy.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCalculationModeChange = (mode) => {
    if (mode === policy.calculationMode) return;
    if (mode === "enterprise") {
      setShowEnterpriseModal(true);
      return;
    }
    const label = CALCULATION_MODE_LABELS[mode];
    const ok = window.confirm(
      `Switch to ${label}? This only affects FUTURE payroll runs — already-approved or paid runs are never recalculated.`
    );
    if (!ok) return;
    handleSaveGeneral({ calculationMode: mode });
  };

  const handleConfigureCompliance = async () => {
    setShowEnterpriseModal(false);
    await handleSaveGeneral({ calculationMode: "enterprise" });
    navigate("/payroll/compliances", { state: { enterpriseOnboarding: true } });
  };

  const handleCategoryChange = (category, field, value) => {
    const next = policy.employeeCategories.map((c) =>
      c.category === category ? { ...c, [field]: value } : c
    );
    setPolicy({ ...policy, employeeCategories: next });
  };

  const handleSaveCategories = async () => {
    await handleSaveGeneral({ employeeCategories: policy.employeeCategories });
  };

  const handleToggleIntegration = async (category, providerKey, currentlyEnabled) => {
    // Optimistic update so the toggle feels instant, reverted on failure.
    const prevIntegrations = policy.integrations;
    const next = policy.integrations.map((i) =>
      i.category === category && i.providerKey === providerKey ? { ...i, enabled: !currentlyEnabled } : i
    );
    setPolicy({ ...policy, integrations: next });
    try {
      if (currentlyEnabled) {
        await disablePolicyIntegration(policy.id, category, providerKey);
      } else {
        await enablePolicyIntegration(policy.id, category, providerKey);
      }
      addToast?.(`${INTEGRATION_LABELS[providerKey] || providerKey} ${currentlyEnabled ? "disabled" : "enabled"}.`, "success");
    } catch {
      setPolicy((p) => ({ ...p, integrations: prevIntegrations }));
      addToast?.("Failed to update integration.", "error");
    }
  };

  if (loading) {
    return (
      <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8">
        <p className="text-[13px] text-[#9E9690]">Loading payroll policy…</p>
      </div>
    );
  }

  if (!policy) {
    return (
      <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8">
        <p className="text-[13px] text-[#9E9690]">Could not load payroll policy.</p>
      </div>
    );
  }

  return (
    <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[12px] bg-[#FF6E86] flex items-center justify-center shadow-[0_2px_8px_rgba(255,110,134,0.3)]">
            <Settings size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-[#1A1816] dark:text-[#F0EDE8]">
              Payroll Policy
            </h1>
            <p className="text-[13px] font-medium text-[#9E9690]">
              Central configuration for how payroll is calculated and processed
            </p>
          </div>
        </div>
        <span className="rounded-full bg-[#FF6E86]/10 border border-[#FF6E86]/20 px-3.5 py-1.5 text-[11px] font-bold text-[#FF6E86]">
          {policy.name} {policy.isDefault && "· Default"}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-[#F0EDE8] dark:bg-[#38312D] rounded-[14px] p-1 w-fit flex-wrap">
        {tabs.map((t, i) => (
          <button
            key={t}
            onClick={() => setActiveTab(i)}
            className={`px-4 py-2 rounded-[12px] text-[13px] font-semibold transition-all duration-200 ${
              activeTab === i
                ? "bg-white dark:bg-[#221D1A] text-[#FF6E86] shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                : "text-[#9E9690] hover:text-[#1A1816] dark:hover:text-[#F0EDE8]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* General */}
      {activeTab === 0 && (
        <Card className="space-y-5 max-w-2xl">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Policy Name">
              <input
                className={inputClass}
                defaultValue={policy.name}
                onBlur={(e) => e.target.value !== policy.name && handleSaveGeneral({ name: e.target.value })}
              />
            </Field>
            <Field label="Status">
              <select
                className={inputClass}
                value={policy.status}
                onChange={(e) => handleSaveGeneral({ status: e.target.value })}
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
                <option value="draft">Draft</option>
              </select>
            </Field>
          </div>
          <Field label="Description">
            <textarea
              className={inputClass}
              rows={2}
              defaultValue={policy.description || ""}
              onBlur={(e) =>
                e.target.value !== (policy.description || "") && handleSaveGeneral({ description: e.target.value })
              }
            />
          </Field>
          <Field label="Effective Date">
            <input
              type="date"
              className={inputClass}
              value={policy.effectiveDate}
              onChange={(e) => handleSaveGeneral({ effectiveDate: e.target.value })}
            />
          </Field>

          <div>
            <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-2">
              Payroll Calculation Mode
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {Object.entries(CALCULATION_MODE_LABELS).map(([mode, label]) => (
                <button
                  key={mode}
                  disabled={saving}
                  onClick={() => handleCalculationModeChange(mode)}
                  className={`rounded-[12px] border px-4 py-3 text-left transition-all ${
                    policy.calculationMode === mode
                      ? "border-[#FF6E86] bg-[#FF6E86]/5"
                      : "border-[#E5E0D9] dark:border-[#38312D] hover:border-[#FF6E86]/40"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{label}</p>
                    {mode === "enterprise" && (
                      <StatusBadge
                        label={ENTERPRISE_STATUS_LABELS[policy.enterpriseStatus] || "Not Configured"}
                        tone={
                          policy.enterpriseStatus === "active" ? "green"
                          : policy.enterpriseStatus === "configured" ? "blue"
                          : policy.enterpriseStatus === "in_progress" ? "amber"
                          : "gray"
                        }
                      />
                    )}
                  </div>
                  {mode === "simple" && (
                    <p className="text-[11px] text-[#9E9690] mt-1">Net = Gross − Unpaid Leave. No PF/ESI/PT/TDS.</p>
                  )}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-[#9E9690] mt-2">
              Switching modes only affects future payroll runs — never already-approved or paid ones.
            </p>
          </div>
        </Card>
      )}

      {/* Employee Categories */}
      {activeTab === 1 && (
        <div className="space-y-3 max-w-3xl">
          {policy.employeeCategories.map((cat) => {
            const isIntern = cat.category === "intern";
            return (
              <ExpandableCard
                key={cat.category}
                title={EMPLOYEE_CATEGORY_LABELS[cat.category] || cat.category}
                subtitle={`${cat.workingDays} working days · ${cat.expectedHours}h expected`}
                badge={
                  <Users size={16} className="text-[#9E9690]" />
                }
              >
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <Field label="Working Days">
                    <input
                      type="number"
                      className={inputClass}
                      value={cat.workingDays}
                      onChange={(e) => handleCategoryChange(cat.category, "workingDays", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Expected Hours">
                    <input
                      type="number"
                      className={inputClass}
                      value={cat.expectedHours}
                      onChange={(e) => handleCategoryChange(cat.category, "expectedHours", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Minimum Hours">
                    <input
                      type="number"
                      className={inputClass}
                      value={cat.minimumHours}
                      onChange={(e) => handleCategoryChange(cat.category, "minimumHours", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Grace Time (min)">
                    <input
                      type="number"
                      className={inputClass}
                      value={cat.graceTimeMinutes}
                      onChange={(e) => handleCategoryChange(cat.category, "graceTimeMinutes", Number(e.target.value))}
                    />
                  </Field>
                </div>
                <div className="flex items-center justify-between rounded-[10px] bg-[#F8F7F4] dark:bg-[#1A1816] px-4 py-3">
                  <div className="flex items-center gap-2">
                    {isIntern && <Lock size={14} className="text-[#9E9690]" />}
                    <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                      Paid Leave Eligible
                    </span>
                  </div>
                  <Toggle
                    checked={isIntern ? false : cat.paidLeaveEligible}
                    disabled={isIntern}
                    title={isIntern ? "Interns are never eligible for paid leave" : undefined}
                    onChange={(val) => handleCategoryChange(cat.category, "paidLeaveEligible", val)}
                  />
                </div>
                {isIntern && (
                  <p className="text-[11px] text-[#9E9690]">
                    Interns never receive paid leave — this is enforced by the backend regardless of this toggle.
                  </p>
                )}
              </ExpandableCard>
            );
          })}
          <div className="flex justify-end">
            <button
              onClick={handleSaveCategories}
              disabled={saving}
              className="rounded-[12px] bg-[#FF6E86] px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_2px_8px_rgba(255,110,134,0.3)] disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save Categories"}
            </button>
          </div>
        </div>
      )}

      {/* Leave & Overtime */}
      {activeTab === 2 && (
        <div className="space-y-4 max-w-2xl">
          <Card>
            <div className="flex items-center gap-2 mb-3">
              <CalendarClock size={16} className="text-[#9E9690]" />
              <p className="text-[14px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Overtime Rules</p>
            </div>
            {policy.overtimeRule ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">Enable Overtime</span>
                  <Toggle
                    checked={policy.overtimeRule.enabled}
                    onChange={(val) =>
                      handleSaveGeneral({ overtimeRule: { ...policy.overtimeRule, enabled: val } })
                    }
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                    Approval Required
                  </span>
                  <Toggle
                    checked={policy.overtimeRule.approvalRequired}
                    disabled={!policy.overtimeRule.enabled}
                    onChange={(val) =>
                      handleSaveGeneral({ overtimeRule: { ...policy.overtimeRule, approvalRequired: val } })
                    }
                  />
                </div>
                <Field label="Minimum Overtime (minutes)">
                  <input
                    type="number"
                    disabled={!policy.overtimeRule.enabled}
                    className={inputClass}
                    value={policy.overtimeRule.minimumOvertimeMinutes}
                    onChange={(e) =>
                      handleSaveGeneral({
                        overtimeRule: { ...policy.overtimeRule, minimumOvertimeMinutes: Number(e.target.value) },
                      })
                    }
                  />
                </Field>
              </div>
            ) : (
              <p className="text-[12px] text-[#9E9690]">No overtime rule configured yet.</p>
            )}
          </Card>

          <Card>
            <p className="text-[14px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-3">Leave Rules</p>
            <p className="text-[12px] text-[#9E9690]">
              Paid Leave, Unpaid Leave, Half Day, Absent, Holiday, Week Off, and Intern Leave rules are configured
              here per policy. Detailed per-rule editing UI ships alongside the Leave Rules backend endpoints
              (planned next).
            </p>
          </Card>
        </div>
      )}

      {/* Integrations */}
      {activeTab === 3 && (
        <div className="space-y-4 max-w-3xl">
          {INTEGRATION_CATEGORY_ORDER.map((cat) => {
            const items = policy.integrations.filter((i) => i.category === cat);
            if (!items.length) return null;
            return (
              <Card key={cat}>
                <div className="flex items-center gap-2 mb-3">
                  <Plug size={16} className="text-[#9E9690]" />
                  <p className="text-[14px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
                    {INTEGRATION_CATEGORY_LABELS[cat]}
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {items.map((i) => {
                    const lockInfo = INTEGRATION_STATUS[i.providerKey];
                    return (
                      <div
                        key={i.providerKey}
                        title={lockInfo?.tooltip}
                        className="flex items-center justify-between rounded-[10px] bg-[#F8F7F4] dark:bg-[#1A1816] px-4 py-3"
                      >
                        <span className="flex items-center gap-2 text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                          {INTEGRATION_LABELS[i.providerKey] || i.providerKey}
                          {lockInfo && <StatusBadge label={lockInfo.label} tone={lockInfo.tone} />}
                        </span>
                        <Toggle
                          checked={lockInfo?.forceOff ? false : i.enabled}
                          disabled={Boolean(lockInfo)}
                          title={lockInfo?.tooltip}
                          onChange={() => handleToggleIntegration(cat, i.providerKey, i.enabled)}
                        />
                      </div>
                    );
                  })}
                </div>
                {cat === "banking" && (
                  <div className="mt-4 border-t border-[#E5E0D9] dark:border-[#38312D] pt-4">
                    <Field label="Bank Transfer File Format">
                      <select
                        className={inputClass}
                        value={policy.bankExportFormat || "csv"}
                        onChange={(e) => handleSaveGeneral({ bankExportFormat: e.target.value })}
                      >
                        <option value="csv">CSV</option>
                        <option value="xlsx">Excel (.xlsx)</option>
                        <option value="txt">TXT</option>
                        <option value="pdf">PDF</option>
                      </select>
                    </Field>
                    <p className="text-[11px] text-[#9E9690] mt-2">
                      Used to generate the downloadable bank transfer file when a payroll run is approved.
                    </p>
                  </div>
                )}
                {cat === "notifications" && <PayrollEmailSettingsPanel />}
              </Card>
            );
          })}
        </div>
      )}

      {showEnterpriseModal && (
        <EnterpriseConfirmModal
          onCancel={() => setShowEnterpriseModal(false)}
          onEnableLater={() => setShowEnterpriseModal(false)}
          onConfigure={handleConfigureCompliance}
        />
      )}
    </div>
  );
}