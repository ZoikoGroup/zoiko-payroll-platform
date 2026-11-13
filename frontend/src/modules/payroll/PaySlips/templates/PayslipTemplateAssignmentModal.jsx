import { useState } from "react";
import { X } from "lucide-react";
import { assignPayslipTemplate } from "../../../../service/payrollService";
import { useToast } from "../../ToastContext";
import { countryLabel } from "./templateCountries";

/** Assign a published template to this organisation's payslips — all of them,
 * or (for an organisation that runs payroll in several countries) one of its
 * own countries. `request` is null (closed) or { templateId? }; `countries`
 * are the organisation's own payroll countries from the API. */
export default function PayslipTemplateAssignmentModal({
  request, templates = [], countries = [], singleCountry = true, onClose, onAssigned,
}) {
  const { addToast } = useToast();
  // Remounted per request (key in the dashboard), so props seed the state.
  const [templateId, setTemplateId] = useState(String(request?.templateId || templates[0]?.id || ""));
  const [country, setCountry] = useState("ALL");
  const [saving, setSaving] = useState(false);

  if (!request) return null;
  const chosen = templates.find((t) => String(t.id) === templateId);
  const target = singleCountry ? "all payslips" : countryLabel(country, countries);

  const submit = async (e) => {
    e.preventDefault();
    if (!chosen) return;
    setSaving(true);
    try {
      const res = await assignPayslipTemplate(chosen.id, singleCountry ? "ALL" : country);
      addToast?.(`"${chosen.name}" is now used for ${target}.`, "success");
      onAssigned?.(res);
      onClose();
    } catch (err) {
      addToast?.(err.message || "Could not assign the template.", "error");
    } finally {
      setSaving(false);
    }
  };

  const field = "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-primary";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface border border-border rounded-[18px] shadow-2xl w-full max-w-md overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h3 className="text-[15px] font-bold text-foreground">Use a payslip template</h3>
          <button type="button" onClick={onClose} aria-label="Close"
            className="p-1.5 rounded-[10px] text-foreground-muted hover:bg-surface-muted hover:text-foreground cursor-pointer">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-4">
          <label className="block">
            <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Template (published)</span>
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} className={field}>
              {templates.map((t) => (
                <option key={t.id} value={String(t.id)}>{t.name} — v{t.activeVersion?.versionNumber}</option>
              ))}
            </select>
          </label>
          {singleCountry ? (
            <p className="text-[12px] text-foreground">
              This template will be used for <strong>all of your organisation&apos;s payslips</strong>.
            </p>
          ) : (
            <label className="block">
              <span className="block text-[11px] font-semibold text-foreground-muted mb-1">
                Use for (your organisation&apos;s payroll countries)
              </span>
              <select value={country} onChange={(e) => setCountry(e.target.value)} className={field}>
                <option value="ALL">All countries (unless a country has its own)</option>
                {countries.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name} ({c.code}){c.status === "OVER_LIMIT" ? " — paused on current plan" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <p className="text-[11px] text-foreground-muted">
            Only your own organisation&apos;s payslips are affected. Applies to payslips not yet approved; approved
            payslips keep the layout they were issued with.{!singleCountry && " A country's own template takes priority over \"All countries\"."}
            {" "}Payslips whose breakdown a template can&apos;t show stay in the standard format.
          </p>
          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-[10px] text-[13px] font-semibold text-foreground-muted hover:bg-surface-muted cursor-pointer">Cancel</button>
            <button type="submit" disabled={saving || !chosen}
              className="px-4 py-2 rounded-[10px] bg-primary text-white text-[13px] font-semibold hover:bg-primary/90 disabled:opacity-50 cursor-pointer">
              {saving ? "Saving…" : "Use template"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
