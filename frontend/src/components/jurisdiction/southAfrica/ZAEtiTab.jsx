import { formatZarAuto } from "./zaComponentConfig";
import { PendingPill, Table } from "./zaShared";
import { byKeys, card } from "./zaFormat";

const ETI_PARAMETER_KEYS = [
  "za_eti_hours_normaliser",
  "za_eti_qualifying_months_max",
  "za_eti_min_age",
  "za_eti_max_age",
];

function units(key) {
  if (key === "za_eti_hours_normaliser") return "hours";
  if (key === "za_eti_qualifying_months_max") return "months";
  return "years";
}

export default function ZAEtiTab({ rates, slabs }) {
  const parameters = byKeys(rates, ETI_PARAMETER_KEYS);
  const bands = (slabs || [])
    .filter((row) => row.ruleType === "ZA_ETI_BAND")
    .sort((a, b) => (
      String(a.filingStatus).localeCompare(String(b.filingStatus))
      || Number(a.minAmount) - Number(b.minAmount)
    ));

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Employment Tax Incentive</h3>
        <p className="mb-3 rounded-lg bg-warning/10 p-2 text-[12px] text-foreground-secondary">
          Every ETI value in this pack is marked PENDING G1. The incentive remains disabled for live calculations until
          the qualification months, hours normalisation and band rules are signed off.
        </p>
        <Table
          rows={parameters}
          columns={[
            { label: "Parameter", render: (row) => row.label },
            { label: "Value", render: (row) => `${row.flatAmount ?? "—"} ${units(row.componentKey)}` },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>

      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">ETI bands (monthly remuneration)</h3>
        <Table
          rows={bands}
          columns={[
            { label: "Qualifying period", render: (row) => (row.filingStatus === "SECOND_12" ? "Second 12 months" : "First 12 months") },
            { label: "Formula", render: (row) => row.taxRegime || "—" },
            { label: "From", render: (row) => (row.minAmount == null ? "—" : formatZarAuto(row.minAmount)) },
            { label: "Below", render: (row) => (row.maxAmount == null ? "and above" : formatZarAuto(row.maxAmount)) },
            { label: "Rate", render: (row) => (row.ratePct == null ? "—" : `${Number(row.ratePct)}%`) },
            { label: "Flat amount", render: (row) => (row.flatAmount == null ? "—" : formatZarAuto(row.flatAmount)) },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>
    </div>
  );
}
