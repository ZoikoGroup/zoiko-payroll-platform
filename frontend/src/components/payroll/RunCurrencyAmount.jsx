import { createCurrencyFormatterForCode, getCountryNameFromCode } from "../../utils/currency";

// Most countries listed inline for a multi-country run; the rest are
// summarised as "+N more" with every country in the tooltip.
const MAX_INLINE_COUNTRIES = 3;

// One run's gross / deductions / net in a runs list (GET /payroll/runs). A
// run that pays more than one country has a meaningless cross-currency sum in
// run.gross etc., so each country's own figure (run.totalsByCountry) is
// listed in its own currency instead — never added together. A
// single-country run shows its usual figure, formatted in that country's
// currency when the backend reports it, else with `fallbackFormat`.
export default function RunCurrencyAmount({ run, runField, countryField, fallbackFormat, hideZero = false }) {
  const byCountry = Array.isArray(run?.totalsByCountry) ? run.totalsByCountry : [];
  if (byCountry.length > 1) {
    const lines = byCountry.map((row) => ({
      country: row.country,
      text: createCurrencyFormatterForCode(row.currency)(row[countryField]),
    }));
    const tooltip = lines
      .map((l) => `${getCountryNameFromCode(l.country) || l.country || "Unassigned"}: ${l.text}`)
      .join("\n");
    const shown = lines.slice(0, MAX_INLINE_COUNTRIES);
    const hidden = lines.length - shown.length;
    return (
      <span className="inline-flex flex-col items-end gap-0.5" title={tooltip}>
        {shown.map((l) => (
          <span key={l.country || "unassigned"} className="whitespace-nowrap">
            {l.text}
            <span className="ml-1 text-[9px] font-bold text-foreground-muted">{l.country || "—"}</span>
          </span>
        ))}
        {hidden > 0 && <span className="text-[10px] font-semibold text-foreground-muted">+{hidden} more</span>}
      </span>
    );
  }
  const value = run?.[runField];
  if (hideZero && !value) return "—";
  const currency = byCountry[0]?.currency;
  return currency ? createCurrencyFormatterForCode(currency)(value) : fallbackFormat(value);
}
