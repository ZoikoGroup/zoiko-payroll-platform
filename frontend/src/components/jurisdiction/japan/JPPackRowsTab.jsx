import { byKeys, card, rateValue } from "./jpFormat";
import { PendingPill, Table } from "./jpShared";
import { describeBand } from "./jpComponentConfig";

// Read-only view of one group of the Japan pack's canonical rows: scalar
// parameters (ContributionRate) and authority tables (TaxSlab rule types).
// An empty table is shown as empty with its signing gate — never filled from
// an assumed value. Values are edited only through the generic pack editor.

export default function JPPackRowsTab({ title, description, rates, slabs, keys = [], tables = [] }) {
  const scalarRows = byKeys(rates, keys);
  const missing = keys.filter((key) => !scalarRows.some((row) => row.componentKey === key));
  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">{title}</h3>
        {description && <p className="mb-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">{description}</p>}
        <Table rows={scalarRows} empty="No rows for this group in the selected pack."
          columns={[
            { label: "Parameter", render: (row) => row.label },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Value", render: (row) => (rateValue(row) === "—" ? <span className="text-warning">Not configured</span> : rateValue(row)) },
            { label: "In force", render: (row) => (row.effectiveFrom ? `${row.effectiveFrom} → ${row.effectiveTo || "open"}` : "Pack window") },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]} />
        {missing.length > 0 && (
          <p className="mt-2 text-[11px] text-error">Missing from this pack: {missing.join(", ")}</p>
        )}
      </div>
      {tables.map(({ ruleType, label, gate }) => {
        const rows = (slabs || []).filter((row) => row.ruleType === ruleType);
        return (
          <div key={ruleType} className={card} data-testid={`jp-table-${ruleType}`}>
            <h3 className="mb-1 text-[14px] font-semibold text-foreground">{label}</h3>
            <p className="mb-2 text-[11px] text-foreground-muted">
              <span className="font-mono">{ruleType}</span> · {rows.length} row{rows.length === 1 ? "" : "s"} · signed at {gate}
            </p>
            {rows.length === 0 ? (
              <p className="rounded-lg border border-warning/40 bg-warning/10 p-2 text-[12px] text-foreground-secondary">
                Empty — needs the official table, archived and signed at {gate}. Every calculation that needs it is blocked.
              </p>
            ) : (
              <Table rows={rows.slice(0, 200)}
                columns={[
                  { label: "Column / state", render: (row) => [row.taxColumn, row.taxRegime, row.jurisdictionState, row.filingStatus].filter(Boolean).join(" · ") || "—" },
                  { label: "No.", render: (row) => row.taxTableNumber ?? "—" },
                  { label: "Band", render: (row) => describeBand(row) },
                  { label: "Value", render: (row) => (row.ratePct != null && Number(row.ratePct) !== 0 ? `${row.ratePct}%` : row.flatAmount ?? row.taxFormula ?? "—") },
                  { label: "Status", render: (row) => <PendingPill row={row} /> },
                ]} />
            )}
          </div>
        );
      })}
    </div>
  );
}
