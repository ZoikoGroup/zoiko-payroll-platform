import { AlertTriangle, Lock } from "lucide-react";

// "Map fields" step of the Exact-layout PDF import: every piece of text found
// in the PDF, the field it shows (or a column heading, or plain text), whether
// it is shown, and the label printed. The server re-checks everything.

const COLUMN_OPTIONS = [
  ["col_particulars", "Column heading: Particulars"],
  ["col_entitled", "Column heading: Entitled (full month)"],
  ["col_earnings", "Column heading: Earnings (paid)"],
  ["col_deductions", "Column heading: Deductions"],
];
const GROUP_NAMES = {
  header: "Header", employee: "Employee details", earnings: "Earnings", deductions: "Deductions",
  totals: "Totals", footer: "Footer",
};
const field =
  "w-full rounded-[8px] border border-border bg-surface px-2 py-1 text-[12px] text-foreground focus:outline-none focus:border-primary disabled:opacity-50";

export default function PayslipTemplateExactMapping({ analysis, form, setForm, catalogue = [] }) {
  const byKey = Object.fromEntries(catalogue.map((f) => [f.key, f]));
  const groups = Object.keys(GROUP_NAMES).map((g) => [g, catalogue.filter((f) => f.group === g)]);
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const setRow = (i, patch) =>
    setForm((f) => ({ ...f, fields: f.fields.map((row, j) => (j === i ? { ...row, ...patch } : row)) }));

  const changeKey = (i, row, key) => {
    const next = key || null;
    const isColumn = next && next.startsWith("col_");
    setRow(i, {
      key: next,
      role: isColumn ? "column" : next ? "field" : "text",
      include: true,
      label: next && !isColumn ? row.label || row.pdfLabel : row.pdfLabel,
      code: next && byKey[next]?.side ? byKey[next].code : undefined,
    });
  };

  const unmatched = form.fields.filter((r) => !r.key).length;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <label className="block col-span-2">
          <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Template name</span>
          <input value={form.name} onChange={(e) => set("name", e.target.value)} className={field} />
        </label>
        <label className="block">
          <span className="block text-[11px] font-semibold text-foreground-muted mb-1">Main colour (filled cells)</span>
          <div className="flex items-center gap-2">
            <input type="color" value={form.primaryColor} onChange={(e) => set("primaryColor", e.target.value.toUpperCase())}
              className="w-8 h-8 rounded border border-border p-0.5 bg-transparent cursor-pointer" />
            <input value={form.primaryColor} onChange={(e) => set("primaryColor", e.target.value)} className={`${field} font-mono`} />
          </div>
          {analysis.colors?.length > 1 && (
            <div className="flex gap-1 mt-1">
              {analysis.colors.map((c) => (
                <button key={c} type="button" title={c} onClick={() => set("primaryColor", c)}
                  className="w-5 h-5 rounded border border-border cursor-pointer" style={{ backgroundColor: c }} />
              ))}
            </div>
          )}
        </label>
        <div className="flex items-center gap-3 self-end">
          {analysis.logoDataUri ? (
            <>
              <img src={analysis.logoDataUri} alt="Logo found in the PDF" className="h-10 rounded border border-border bg-white" />
              <label className="flex items-center gap-1.5 text-[12px] text-foreground cursor-pointer">
                <input type="checkbox" checked={form.includeLogo} onChange={(e) => set("includeLogo", e.target.checked)} />
                Use this logo
              </label>
            </>
          ) : (
            <span className="text-[12px] text-foreground-muted">No logo found above the table.</span>
          )}
        </div>
        <p className="col-span-2 text-[11px] text-foreground-muted">
          Grid found: {analysis.table.colWidths.length} columns × {analysis.table.rowHeights.length} rows
          ({analysis.table.colWidths.map((w) => `${Math.round(w)}%`).join(" / ")}).
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[12px] font-bold text-foreground">Map fields</p>
          {unmatched > 0 && (
            <span className="flex items-center gap-1 text-[11px] text-warning">
              <AlertTriangle size={12} /> {unmatched} label{unmatched === 1 ? "" : "s"} not matched — kept as plain text
            </span>
          )}
        </div>
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-foreground-muted">
              <th className="py-1 w-8">Show</th>
              <th className="py-1 pr-2">In your PDF</th>
              <th className="py-1 pr-2">Shows</th>
              <th className="py-1 pr-2">Label on payslip</th>
              <th className="py-1">Line code</th>
            </tr>
          </thead>
          <tbody>
            {form.fields.map((row, i) => {
              const f = row.key ? byKey[row.key] : null;
              const isField = !!f;
              return (
                <tr key={row.ref} className={`border-t border-border align-top ${!row.key ? "bg-warning/5" : ""}`}>
                  <td className="py-1.5">
                    {f?.required ? (
                      <span title="Always shown" className="text-foreground-muted"><Lock size={12} /></span>
                    ) : (
                      <input type="checkbox" checked={row.include} disabled={!isField}
                        aria-label={`Show ${row.pdfLabel}`} onChange={(e) => setRow(i, { include: e.target.checked })} />
                    )}
                  </td>
                  <td className="py-1.5 pr-2 max-w-[220px]">
                    <span className="block truncate text-foreground" title={row.pdfLabel}>{row.pdfLabel}</span>
                    {row.match === "fuzzy" && <span className="text-[10px] text-warning">Close match — please check</span>}
                    {!row.key && <span className="text-[10px] text-warning">Not matched</span>}
                  </td>
                  <td className="py-1.5 pr-2">
                    <select value={row.key || ""} onChange={(e) => changeKey(i, row, e.target.value)} className={field}
                      aria-label={`Field for ${row.pdfLabel}`}>
                      <option value="">Plain text (not a field)</option>
                      <optgroup label="Column headings">
                        {COLUMN_OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      </optgroup>
                      {groups.map(([g, items]) => items.length > 0 && (
                        <optgroup key={g} label={GROUP_NAMES[g]}>
                          {items.map((it) => <option key={it.key} value={it.key}>{it.label}</option>)}
                        </optgroup>
                      ))}
                    </select>
                    {f?.hint && <span className="block text-[10px] text-foreground-muted mt-0.5">{f.hint}</span>}
                  </td>
                  <td className="py-1.5 pr-2">
                    <input value={isField ? row.label || "" : row.pdfLabel} disabled={!isField}
                      maxLength={row.key === "note" ? 200 : 80} aria-label={`Label for ${row.pdfLabel}`}
                      onChange={(e) => setRow(i, { label: e.target.value })} className={field} />
                  </td>
                  <td className="py-1.5 w-40">
                    {f?.side ? (
                      <input value={row.code ?? f.code ?? ""} maxLength={80} aria-label={`Line code for ${row.pdfLabel}`}
                        title="Which payslip line this row shows (e.g. allowance_transport)"
                        onChange={(e) => setRow(i, { code: e.target.value.toLowerCase() })}
                        className={`${field} font-mono text-[11px]`} />
                    ) : (
                      <span className="text-[11px] text-foreground-muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="text-[11px] text-foreground-muted mt-2">
          Values always come from each employee&apos;s payslip. Earnings and deduction lines without a row of their own
          are added to &quot;Any other&quot; (and an &quot;Other Earnings&quot; row that only appears when needed), so
          the totals always match.
        </p>
      </div>
    </div>
  );
}
