import { createCurrencyFormatterForCode, getCountryNameFromCode } from "../../utils/currency";

// Per-country payroll totals for a run or period that pays employees in more
// than one country. Every amount is formatted in its own row's currency —
// the backend never sums currencies, and neither does this table (there is
// deliberately no grand-total row).
//
// `rows` is the backend's per-country shape ({ country, currency, ... });
// `columns` picks which of its fields to show, e.g.
// [{ key: "totalGross", label: "Gross", money: true }, { key: "employeeCount", label: "Employees" }].

function countryLabel(code) {
  return getCountryNameFromCode(code) || code || "Unassigned";
}

export default function CountryTotalsTable({ rows = [], columns = [], dense = false }) {
  const cell = dense ? "px-3 py-2" : "px-4 py-2.5";
  return (
    <div className="rounded-[14px] border border-border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-muted border-b border-border">
              <th className={`${cell} text-left text-[10px] font-bold uppercase tracking-widest text-foreground-muted whitespace-nowrap`}>
                Country
              </th>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`${cell} text-right text-[10px] font-bold uppercase tracking-widest text-foreground-muted whitespace-nowrap`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {rows.map((row) => {
              const fmt = createCurrencyFormatterForCode(row.currency);
              return (
                <tr key={row.country || "unassigned"}>
                  <td className={`${cell} text-xs font-semibold text-foreground whitespace-nowrap`}>
                    {countryLabel(row.country)}
                    {row.currency && <span className="ml-1.5 text-[10px] font-bold text-foreground-muted">{row.currency}</span>}
                  </td>
                  {columns.map((col) => (
                    <td key={col.key} className={`${cell} text-xs font-semibold text-right whitespace-nowrap ${col.accent || "text-foreground"}`}>
                      {col.money ? fmt(row[col.key]) : (row[col.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
