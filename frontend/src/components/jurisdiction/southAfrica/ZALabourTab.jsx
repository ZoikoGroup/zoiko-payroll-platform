import { formatZarAuto } from "./zaComponentConfig";
import { PendingPill, Table } from "./zaShared";
import { byKeys, card } from "./zaFormat";

const LABOUR_KEYS = ["za_nmw_hourly", "za_bcea_earnings_threshold"];
const FILING_KEYS = [
  "za_emp201_due_day",
  "za_emp201_non_business_day_rule",
  "za_brs_version",
  "za_record_retention_years",
];

function labourValue(row) {
  if (row.flatAmount == null) return row.textValue ?? "—";
  return row.componentKey === "za_nmw_hourly"
    ? `${formatZarAuto(row.flatAmount)} per hour`
    : `${formatZarAuto(row.flatAmount)} per year`;
}

function filingValue(row) {
  if (row.textValue) return row.textValue;
  if (row.flatAmount == null) return "—";
  if (row.componentKey === "za_emp201_due_day") return `Day ${row.flatAmount} of the following month`;
  if (row.componentKey === "za_record_retention_years") return `${row.flatAmount} years minimum`;
  return row.flatAmount;
}

export default function ZALabourTab({ rates }) {
  const labour = byKeys(rates, LABOUR_KEYS);
  const filing = byKeys(rates, FILING_KEYS);

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Labour baselines</h3>
        <p className="mb-3 text-[12px] text-foreground-muted">
          The BCEA threshold changes inside a tax year; its legal effective date comes from the row, not the tax-year
          window.
        </p>
        <Table
          rows={labour}
          columns={[
            { label: "Baseline", render: (row) => row.label },
            { label: "Value", render: (row) => labourValue(row) },
            { label: "Effective from", render: (row) => row.effectiveFrom || "Pack window" },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>

      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Filing, BRS and records</h3>
        <Table
          rows={filing}
          columns={[
            { label: "Requirement", render: (row) => row.label },
            { label: "Value", render: (row) => filingValue(row) },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>
    </div>
  );
}
