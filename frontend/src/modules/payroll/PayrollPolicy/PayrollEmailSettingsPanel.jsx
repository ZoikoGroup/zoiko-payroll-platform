import { useState, useEffect, useCallback } from "react";
import { Mail, Inbox, ShieldCheck, Loader2 } from "lucide-react";
import { useToast } from "../ToastContext";
import { getEmailSettings, updateEmailSettings } from "../../../service/payrollService";

const inputClass =
  "w-full rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-2 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:ring-2 focus:ring-[#FF6E86]/30";

function Toggle({ checked, onChange, disabled = false }) {
  return (
    <button
      type="button"
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

// Sits inside the Integrations tab, directly under the Notifications card.
// Two independent things live here:
//   1. Outbound "From" identity override — sent through the platform's
//      existing shared SMTP connection, no new credentials required.
//   2. Inbound IMAP mailbox — the real address that receives leave-request
//      emails. Its password is write-only: never returned by the API,
//      encrypted at rest (see backend app/core/crypto.py), and this form
//      never pre-fills it — leaving it blank on save keeps whatever is
//      already stored untouched.
export default function PayrollEmailSettingsPanel() {
  const { addToast } = useToast();
  const [settings, setSettings] = useState(null);
  const [fromEmail, setFromEmail] = useState("");
  const [fromDisplayName, setFromDisplayName] = useState("");
  const [savingIdentity, setSavingIdentity] = useState(false);

  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState("993");
  const [imapUsername, setImapUsername] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [imapUseSsl, setImapUseSsl] = useState(true);
  const [savingImap, setSavingImap] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getEmailSettings();
      setSettings(data);
      setFromEmail(data?.fromEmail || "");
      setFromDisplayName(data?.fromDisplayName || "");
      setImapHost(data?.imapHost || "");
      setImapPort(data?.imapPort || "993");
      setImapUsername(data?.imapUsername || "");
      setImapUseSsl(data?.imapUseSsl !== false);
      setImapPassword(""); // write-only — never pre-filled from the server
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

  const handleSaveImap = async () => {
    if (!imapHost.trim() || !imapUsername.trim()) {
      addToast?.("Mailbox host and address are required.", "error");
      return;
    }
    setSavingImap(true);
    try {
      const payload = {
        imapHost: imapHost.trim(),
        imapPort: imapPort.trim() || "993",
        imapUsername: imapUsername.trim(),
        imapUseSsl,
      };
      // Only send the password if the admin actually typed a new one —
      // an empty field here means "leave the stored password alone".
      if (imapPassword.trim()) payload.imapPassword = imapPassword.trim();

      const updated = await updateEmailSettings(payload);
      setSettings(updated);
      setImapPassword("");
      addToast?.("IMAP mailbox settings saved.", "success");
    } catch (err) {
      addToast?.(err?.message || "Failed to save IMAP mailbox settings.", "error");
    } finally {
      setSavingImap(false);
    }
  };

  if (!settings) return null;

  return (
    <div className="mt-4 border-t border-[#E5E0D9] dark:border-[#38312D] pt-4 space-y-6">
      {/* ── Outbound sender identity ── */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Mail size={15} className="text-[#9E9690]" />
          <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
            Payroll Email Sender Identity
          </p>
        </div>
        <p className="text-[11px] text-[#9E9690]">
          Optional — payslip and payroll emails still send through the platform's shared mail
          server. Set these so employees see your organization as the sender instead of the
          platform default. Leave blank to keep the platform default.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">
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
            <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">
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
            className="rounded-[10px] bg-[#FF6E86] px-4 py-2 text-[12px] font-bold text-white shadow-[0_2px_8px_rgba(255,110,134,0.3)] disabled:opacity-50"
          >
            {savingIdentity ? "Saving…" : "Save Sender Identity"}
          </button>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between rounded-[10px] bg-[#F8F7F4] dark:bg-[#1A1816] px-4 py-3">
            <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
              Notify on Payslip Ready
            </span>
            <Toggle
              checked={settings.notifyPayslipReady}
              onChange={(val) => handleToggle("notifyPayslipReady", val)}
            />
          </div>
          <div className="flex items-center justify-between rounded-[10px] bg-[#F8F7F4] dark:bg-[#1A1816] px-4 py-3">
            <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
              Notify on Payroll Run Approved
            </span>
            <Toggle
              checked={settings.notifyRunApproved}
              onChange={(val) => handleToggle("notifyRunApproved", val)}
            />
          </div>
        </div>
      </div>

      {/* ── Inbound IMAP mailbox (leave-request inbox) ── */}
      <div className="space-y-4 border-t border-[#E5E0D9] dark:border-[#38312D] pt-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Inbox size={15} className="text-[#9E9690]" />
            <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
              Leave-Request Receiving Mailbox (IMAP)
            </p>
          </div>
          <Toggle checked={settings.imapEnabled} onChange={(val) => handleToggle("imapEnabled", val)} />
        </div>
        <p className="text-[11px] text-[#9E9690]">
          The real mailbox employees email to submit leave requests. Requires a mailbox you
          control with IMAP access enabled (e.g. an app password from your email provider).
          The password is encrypted before storage and is never shown again once saved.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">
              IMAP Host
            </span>
            <input
              className={inputClass}
              placeholder="imap.yourprovider.com"
              value={imapHost}
              onChange={(e) => setImapHost(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">
              Port
            </span>
            <input
              className={inputClass}
              placeholder="993"
              value={imapPort}
              onChange={(e) => setImapPort(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="block text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">
              Mailbox Address
            </span>
            <input
              type="email"
              className={inputClass}
              placeholder="leave@yourcompany.com"
              value={imapUsername}
              onChange={(e) => setImapUsername(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="flex items-center gap-1.5 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] mb-1.5">
              Password
              {settings.imapConfigured && (
                <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-[#19C58A]">
                  <ShieldCheck size={11} /> configured
                </span>
              )}
            </span>
            <input
              type="password"
              className={inputClass}
              placeholder={settings.imapConfigured ? "Leave blank to keep existing" : "Enter mailbox password"}
              value={imapPassword}
              onChange={(e) => setImapPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
        </div>

        <div className="flex items-center justify-between rounded-[10px] bg-[#F8F7F4] dark:bg-[#1A1816] px-4 py-3">
          <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">Use SSL</span>
          <Toggle checked={imapUseSsl} onChange={setImapUseSsl} />
        </div>

        <div className="flex justify-end">
          <button
            onClick={handleSaveImap}
            disabled={savingImap}
            className="flex items-center gap-2 rounded-[10px] bg-[#35B6F5] px-4 py-2 text-[12px] font-bold text-white shadow-[0_2px_8px_rgba(53,182,245,0.3)] disabled:opacity-50"
          >
            {savingImap && <Loader2 size={13} className="animate-spin" />}
            {savingImap ? "Saving…" : "Save Mailbox Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}
