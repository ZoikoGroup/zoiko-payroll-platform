import { Banknote, BarChart3, Check, FileText, Globe2 } from "lucide-react";
import CountryFlag from "../../../components/jurisdiction/CountryFlag";

// Interactive country cards for /payroll/reports. Click selects a country
// (aria-pressed, highlighted card); hover or keyboard focus shows a preview of
// that country's statutory forms and standard reports. A responsive grid that
// stays tidy from one country up to the Business plan's ten (2 → 5 columns).
export default function ReportCountrySelector({
  countries,           // [{ code, name, currency, employeeCount, isPrimary, forms: [{ name }] }]
  selected,
  onSelect,
  loadingForms = false,
}) {
  return (
    <div className="bg-surface border border-border rounded-[18px] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)]" data-testid="report-countries">
      <p className="mb-3 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
        <Globe2 size={13} /> Reporting for {countries.length} {countries.length === 1 ? "country" : "countries"}
        <span className="font-medium normal-case tracking-normal">· select a country to see its forms</span>
      </p>
      <div className="grid grid-cols-1 min-[420px]:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3" role="group" aria-label="Reporting country">
        {countries.map((c) => {
          const active = c.code === selected;
          const formCount = c.forms.length;
          return (
            <div key={c.code} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.code)}
                aria-pressed={active}
                aria-describedby={`report-country-preview-${c.code}`}
                data-testid={`report-country-${c.code}`}
                className={`w-full text-left rounded-[14px] border px-4 py-3 transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
                  active
                    ? "border-primary bg-primary/5 shadow-[0_0_0_1px_var(--color-primary)]"
                    : "border-border bg-background hover:border-primary/50 hover:bg-surface-muted"
                }`}
              >
                <div className="flex items-center gap-2">
                  <CountryFlag code={c.code} name={c.name} size="md" decorative />
                  <p className="min-w-0 flex-1 truncate text-[15px] font-bold text-foreground" title={c.name}>{c.name}</p>
                  <div className="flex shrink-0 items-center gap-1">
                    {c.isPrimary && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-primary">Primary</span>
                    )}
                    {active && <Check size={14} className="text-primary" aria-hidden="true" />}
                  </div>
                </div>
                <p className="mt-0.5 text-[12px] text-foreground-muted">
                  {c.code}{c.currency ? ` · ${c.currency}` : ""}
                  {c.employeeCount != null && ` · ${c.employeeCount} employee${c.employeeCount === 1 ? "" : "s"}`}
                </p>
                <p className="mt-1.5 text-[11px] font-semibold text-foreground-secondary">
                  {loadingForms ? "Loading forms…" : formCount > 0
                    ? `${formCount} statutory form${formCount === 1 ? "" : "s"}`
                    : "No statutory forms yet"}
                </p>
              </button>

              {/* Hover / focus preview */}
              <div
                id={`report-country-preview-${c.code}`}
                role="tooltip"
                className="pointer-events-none invisible absolute left-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-[14px] border border-border bg-surface p-3 opacity-0 shadow-[0_12px_32px_rgba(0,0,0,0.14)] transition-opacity duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
              >
                <p className="mb-1.5 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{c.name} · available reports</p>
                <ul className="space-y-1 text-[12px] text-foreground">
                  {c.forms.map((f) => (
                    <li key={f.key || f.name} className="flex items-start gap-1.5">
                      <FileText size={12} className="mt-0.5 shrink-0 text-primary" /> {f.name}
                    </li>
                  ))}
                  {formCount === 0 && !loadingForms && (
                    <li className="text-foreground-muted">No statutory forms configured for this country yet.</li>
                  )}
                  <li className="flex items-start gap-1.5 text-foreground-secondary">
                    <BarChart3 size={12} className="mt-0.5 shrink-0" /> Payroll register
                  </li>
                  <li className="flex items-start gap-1.5 text-foreground-secondary">
                    <Banknote size={12} className="mt-0.5 shrink-0" /> Bank transfer file
                  </li>
                </ul>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
