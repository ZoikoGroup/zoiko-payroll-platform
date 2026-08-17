import { useState, useEffect, useCallback } from "react";
import { Mail } from "lucide-react";
import { useToast } from "../ToastContext";
import { getEmailSettings, updateEmailSettings } from "../../../service/payrollService";

const inputClass =
  "w-full rounded-[10px] border border-border bg-background px-3 py-2 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-error/30";

function Toggle({ checked, onChange, disabled = false }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200 ${
        checked ? "bg-error" : "bg-border"
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

// Sits inside the Integrations tab, directly under the Notifications card.
// Outbound "From" identity override — sent through the platform's existing
// shared SMTP connection, no new credentials required.
export default function PayrollEmailSettingsPanel() {
  const { addToast } = useToast();
  const [settings, setSettings] = useState(null);
  const [fromEmail, setFromEmail] = useState("");
  const [fromDisplayName, setFromDisplayName] = useState("");
  const [savingIdentity, setSavingIdentity] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getEmailSettings();
      setSettings(data);
      setFromEmail(data?.fromEmail || "");
      setFromDisplayName(data?.fromDisplayName || "");
    } catch {
      addToast?.("Failed to load payroll email settings.", "error");
    }
  }, [addToast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSaveIdentity = async () => {
    setSavingIdentity(true);
    try {
      const updated = await updateEmailSettings({
        fromEmail: fromEmail.trim() || null,
        fromDisplayName: fromDisplayName.trim() || null,
      });
      setSettings(updated);
      addToast?.("Payroll email sender identity updated.", "success");
    } catch {
      addToast?.("Failed to update payroll email settings.", "error");
    } finally {
      setSavingIdentity(false);
    }
  };

  const handleToggle = async (field, value) => {
    const prev = settings;
    setSettings((s) => ({ ...s, [field]: value }));
    try {
      const updated = await updateEmailSettings({ [field]: value });
      setSettings(updated);
    } catch {
      setSettings(prev);
      addToast?.("Failed to update setting.", "error");
    }
  };

  if (!settings) return null;

  return (
    <div className="mt-4 border-t border-border pt-4 space-y-6">
      {/* ── Outbound sender identity ── */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Mail size={15} className="text-foreground-muted" />
          <p className="text-[13px] font-bold text-foreground">
            Payroll Email Sender Identity
          </p>
        </div>
        <p className="text-[11px] text-foreground-muted">
          Optional — payslip and payroll emails still send through the platform's shared mail
          server. Set these so employees see your organization as the sender instead of the
          platform default. Leave blank to keep the platform default.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="block text-[12px] font-semibold text-foreground-muted mb-1.5">
              From Email
            </span>
            <input
              type="email"
              className={inputClass}
              placeholder="payroll@yourcompany.com"
              value={fromEmail}
              onChange={(e) => setFromEmail(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="block text-[12px] font-semibold text-foreground-muted mb-1.5">
              From Display Name
            </span>
            <input
              className={inputClass}
              placeholder="Your Company Payroll"
              value={fromDisplayName}
              onChange={(e) => setFromDisplayName(e.target.value)}
            />
          </label>
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSaveIdentity}
            disabled={savingIdentity}
            className="rounded-[10px] bg-error px-4 py-2 text-[12px] font-bold text-white shadow-[0_2px_8px_rgba(255,110,134,0.3)] disabled:opacity-50"
          >
            {savingIdentity ? "Saving…" : "Save Sender Identity"}
          </button>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between rounded-[10px] bg-background px-4 py-3">
            <span className="text-[13px] font-semibold text-foreground">
              Notify on Payslip Ready
            </span>
            <Toggle
              checked={settings.notifyPayslipReady}
              onChange={(val) => handleToggle("notifyPayslipReady", val)}
            />
          </div>
          <div className="flex items-center justify-between rounded-[10px] bg-background px-4 py-3">
            <span className="text-[13px] font-semibold text-foreground">
              Notify on Payroll Run Approved
            </span>
            <Toggle
              checked={settings.notifyRunApproved}
              onChange={(val) => handleToggle("notifyRunApproved", val)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
