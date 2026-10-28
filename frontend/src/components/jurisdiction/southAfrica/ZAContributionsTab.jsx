import { formatZarAuto } from "./zaComponentConfig";
import { PendingPill, Table } from "./zaShared";
import { byKeys, card, rateValue } from "./zaFormat";

const RATE_KEYS = ["za_uif", "za_sdl", "za_retirement_deduction_pct"];
const AMOUNT_KEYS = [
  "za_uif_monthly_ceiling",
  "za_sdl_exemption_threshold",
  "za_retirement_annual_cap",
];

export default function ZAContributionsTab({ rates }) {
  const rateRows = byKeys(rates, RATE_KEYS);
  const amountRows = byKeys(rates, AMOUNT_KEYS);

  return (
    <div className="space-y-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">UIF, SDL and retirement contributions</h3>
        <p className="mb-3 rounded-lg bg-surface-muted p-2 text-[12px] text-foreground-secondary">
          UIF and SDL use their own remuneration bases. No shared &quot;taxable gross&quot; is assumed.
        </p>
        <Table
          rows={rateRows}
          columns={[
            { label: "Contribution", render: (row) => row.label },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Rate", render: (row) => rateValue(row) },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>

      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">Ceilings and thresholds</h3>
        <Table
          rows={amountRows}
          columns={[
            { label: "Threshold", render: (row) => row.label },
            { label: "Key", render: (row) => <span className="font-mono text-[11px] text-foreground-muted">{row.componentKey}</span> },
            { label: "Amount", render: (row) => (row.flatAmount == null ? "—" : formatZarAuto(row.flatAmount)) },
            { label: "Effective from", render: (row) => row.effectiveFrom || "Pack window" },
            { label: "Status", render: (row) => <PendingPill row={row} /> },
          ]}
        />
      </div>
    </div>
  );
}
