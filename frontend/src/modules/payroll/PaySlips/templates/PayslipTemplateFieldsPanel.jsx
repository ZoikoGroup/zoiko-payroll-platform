import { Lock } from "lucide-react";

// Field settings of a field-aware template (an "Exact layout" PDF import):
// which key / value pairs appear and what they are called. Stored in
// configurationJson.fields; the server is the source of truth for the rules
// (required fields stay on, labels are cleaned, codes are checked).

const GROUPS = [
  ["header", "Header"],
  ["employee", "Employee details"],
  ["earnings", "Earnings"],
  ["deductions", "Deductions"],
  ["totals", "Totals"],
  ["footer", "Footer"],
];

const FLAG_NAMES = {
  showEmployeeBank: "Bank details",
  showCompanyLogo: "Company logo",
  showNetInWords: "Net pay in words",
};

const input =
  "rounded-[8px] border border-border bg-surface px-2 py-1 text-[12px] text-foreground focus:outline-none focus:border-primary";

export default function PayslipTemplateFieldsPanel({ catalogue = [], config, onChange }) {
  const fields = config?.fields;
  if (!fields || catalogue.length === 0) {
    return (
      <p className="text-[11px] text-foreground-muted rounded-[12px] border border-dashed border-border p-3">
        This layout doesn&apos;t use field settings. Import a PDF with &quot;Exact layout&quot; to choose which fields
        appear and rename them.
      </p>
    );
  }

  const entry = (f) => ({ include: f.defaultIncluded, label: f.label, ...(f.code ? { code: f.code } : {}), ...(fields[f.key] || {}) });
  const set = (f, patch) => onChange({ ...fields, [f.key]: { ...entry(f), ...patch } });

  return (
    <div className="rounded-[12px] border border-border">
      <div className="px-4 py-2.5 border-b border-border">
        <p className="text-[12px] font-semibold text-foreground">Fields</p>
        <p className="text-[11px] text-foreground-muted">
          Untick a field to leave its cells empty; a row whose fields are all unticked is removed. Lines without a row
          of their own are added to the &quot;other&quot; rows, so the totals always match the payslip.
        </p>
      </div>
      {GROUPS.map(([group, title]) => {
        const items = catalogue.filter((f) => f.group === group);
        if (items.length === 0) return null;
        return (
          <div key={group} className="px-4 py-3 border-b border-border last:border-b-0">
            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted mb-2">{title}</p>
            <div className="space-y-1.5">
              {items.map((f) => {
                const e = entry(f);
                const flagOff = f.flag && config[f.flag] === false;
                return (
                  <div key={f.key} className="flex items-center gap-2" title={f.hint || undefined}>
                    {f.required ? (
                      <span className="w-4 flex justify-center text-foreground-muted" title="Always shown">
                        <Lock size={12} />
                      </span>
                    ) : (
                      <input type="checkbox" className="w-4" checked={!!e.include} aria-label={`Show ${f.label}`}
                        onChange={(ev) => set(f, { include: ev.target.checked })} />
                    )}
                    <input value={e.label} maxLength={80} aria-label={`${f.label} label`} placeholder={f.label}
                      onChange={(ev) => set(f, { label: ev.target.value })}
                      className={`${input} flex-1 min-w-0 ${!e.include && !f.required ? "opacity-50" : ""}`} />
                    {f.side && (
                      <input value={e.code || ""} maxLength={80} aria-label={`${f.label} line code`}
                        title="Line code shown in this row (e.g. allowance_transport)"
                        onChange={(ev) => set(f, { code: ev.target.value.toLowerCase() })}
                        className={`${input} w-40 font-mono text-[11px]`} />
                    )}
                    {flagOff && (
                      <span className="text-[10px] text-warning whitespace-nowrap">{FLAG_NAMES[f.flag]} is off</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
