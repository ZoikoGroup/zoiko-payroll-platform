import { useMemo } from "react";

// USA-only compact summary cards shown above the Tax Components tab. All
// counts are computed on the fly from the already-loaded `rates`/`slabs`
// arrays JurisdictionLayout passes down — never hardcoded, no extra fetch.
export default function USComponentSummaryCards({ rates, slabs }) {
  const totals = useMemo(() => {
    const arr = rates || [];
    return {
      total: arr.length,
      employee: arr.filter((r) => r.employeeRatePct != null && r.employeeRatePct !== "").length,
      employer: arr.filter((r) => r.employerRatePct != null && r.employerRatePct !== "").length,
      brackets: (slabs || []).length,
    };
  }, [rates, slabs]);

  const cards = [
    { label: "Total Components", value: totals.total, hint: "configured rates" },
    { label: "Employee Components", value: totals.employee, hint: "with employee rate" },
    { label: "Employer Components", value: totals.employer, hint: "with employer rate" },
    { label: "Income Tax Brackets", value: totals.brackets, hint: "across filing statuses" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-xl border border-border bg-surface px-4 py-3"
        >
          <p className="truncate text-[11px] font-semibold uppercase tracking-wider text-foreground-muted">
            {c.label}
          </p>
          <p className="mt-1 text-2xl font-bold text-foreground tabular-nums">{c.value}</p>
          <p className="mt-0.5 truncate text-[11px] text-foreground-disabled">{c.hint}</p>
        </div>
      ))}
    </div>
  );
}
