import { formatZarAuto } from "./zaComponentConfig";
import { PendingPill, Table } from "./zaShared";
import { byKeys, card } from "./zaFormat";

const PAYE_PARAMETER_KEYS = [
  "za_rebate_primary",
  "za_rebate_secondary",
  "za_rebate_tertiary",
  "za_rebate_secondary_age",
  "za_rebate_tertiary_age",
  "za_mtc_main_member",
  "za_mtc_first_dependant",
  "za_mtc_additional_dependant",
  "za_retirement_deduction_pct",
  "za_retirement_annual_cap",
  "za_travel_inclusion_default_pct",
  "za_travel_inclusion_business_pct",
  "za_travel_business_use_min_pct",
];

function amount(value) {
  return value == null ? "—" : formatZarAuto(value);
}

function parameterValue(row) {
  if (row.employeeRatePct != null) return `${Number(row.employeeRatePct).toFixed(2)}%`;
  if (row.employerRatePct != null) return `${Number(row.employerRatePct).toFixed(2)}%`;
  if (row.flatAmount != null) return formatZarAuto(row.flatAmount);
  return row.textValue ?? "—";
}

export default function ZAPayeTab({ rates, slabs }) {
  const bands = (slabs || [])
    .filter((row) => row.ruleType === "ZA_PAYE_BAND")
    .sort((a, b) => Number(a.minAmount) - Number(b.minAmount));
  const parameters = byKeys(rates, PAYE_PARAMETER_KEYS);

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">PAYE bands (annual taxable income)</h3>
        <p className="mb-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          These bands are validation anchors for the certified SARS periodic deduction algorithm, not a simple
          annual-tax-divided-by-twelve calculation. Live South Africa payroll remains disabled until the release gates
          are evidenced.
        </p>
        <Table
          rows={bands}
          columns={[
            { label: "From", render: (row) => amount(row.minAmount) },
            { label: "To", render: (row) => (row.maxAmount == null ? "and above" : amount(row.maxAmount)) },
            { label: "Marginal rate", render: (row) => `${Number(row.ratePct)}%` },
            { label: "Base tax", render: (row) => amount(row.flatAmount) },
            { label: "Rule", render: (row) => row.taxFormula || row.rateLabel || "—" },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>

      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Rebates, medical credits and retirement limits</h3>
        <p className="mb-3 text-[12px] text-foreground-muted">
          Values are read from this pack&apos;s canonical rows. Any row marked PENDING G1 must be signed before activation.
        </p>
        <Table
          rows={parameters}
          columns={[
            { label: "Parameter", render: (row) => row.label },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Value", render: (row) => parameterValue(row) },
            { label: "Effective from", render: (row) => row.effectiveFrom || "Pack window" },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>
    </div>
  );
}
