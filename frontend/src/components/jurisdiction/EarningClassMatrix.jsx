const DEFAULT_COMPONENTS = [
  "SALARY",
  "OVERTIME",
  "BONUS",
  "COMMISSION",
  "LEAVE_PAYOUT",
  "TRAVEL_FIXED",
  "TRAVEL_REIMBURSIVE",
  "FRINGE_BENEFIT",
  "OTHER_EARNINGS",
];

const TREATMENT_CLASS = {
  INCLUDED: "border-success/40 bg-success/10 text-success",
  EXCLUDED: "border-border bg-surface-muted text-foreground-muted",
  TRAVEL_RULE: "border-info/40 bg-info/10 text-info",
  REVIEW: "border-warning/40 bg-warning/10 text-warning",
};

function Treatment({ value, title }) {
  if (!value) return <span className="text-foreground-muted">—</span>;
  return (
    <span
      title={title || value}
      className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${TREATMENT_CLASS[value] || TREATMENT_CLASS.REVIEW}`}
    >
      {value.replaceAll("_", " ")}
    </span>
  );
}

export default function EarningClassMatrix({
  slabs,
  ruleType,
  title,
  description,
  obligations = [],
  componentOrder = DEFAULT_COMPONENTS,
}) {
  const rows = (slabs || []).filter((row) => row.ruleType === ruleType);
  const obligationSet = new Set(rows.map((row) => row.taxRegime).filter(Boolean));
  const componentSet = new Set(rows.map((row) => row.filingStatus).filter(Boolean));

  const visibleObligations = [
    ...obligations.filter((value) => obligationSet.has(value)),
    ...[...obligationSet].filter((value) => !obligations.includes(value)).sort(),
  ];
  const visibleComponents = [
    ...componentOrder.filter((value) => componentSet.has(value)),
    ...[...componentSet].filter((value) => !componentOrder.includes(value)).sort(),
  ];

  const cells = new Map();
  for (const row of rows) {
    cells.set(`${row.taxRegime}|${row.filingStatus}`, row);
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">{title}</h3>
      {description && <p className="mb-3 text-[12px] text-foreground-muted">{description}</p>}
      {rows.length === 0 ? (
        <p className="py-4 text-[12px] text-foreground-muted">
          No earning classification rows are configured for this pack.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full" aria-label={title}>
              <thead>
                <tr>
                  <th className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted">
                    Pay component
                  </th>
                  {visibleObligations.map((obligation) => (
                    <th
                      key={obligation}
                      className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground-muted"
                    >
                      {obligation}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleComponents.map((component) => (
                  <tr key={component} className="border-t border-border">
                    <td className="px-2 py-1.5 font-mono text-[11px] text-foreground">{component}</td>
                    {visibleObligations.map((obligation) => {
                      const row = cells.get(`${obligation}|${component}`);
                      return (
                        <td key={obligation} className="px-2 py-1.5">
                          <Treatment value={row?.assessmentBasis} title={row?.rateLabel} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-foreground-muted">
            <Treatment value="INCLUDED" /> <span>included in the base</span>
            <Treatment value="TRAVEL_RULE" /> <span>travel inclusion rule</span>
            <Treatment value="REVIEW" /> <span>blocks until classified</span>
            <Treatment value="EXCLUDED" /> <span>outside the base</span>
          </div>
          <p className="mt-2 text-[11px] text-foreground-muted">
            IRP5 source codes are intentionally absent until the BRS source-code catalogue is archived and reviewed.
          </p>
        </>
      )}
    </div>
  );
}
