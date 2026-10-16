import { useState } from "react";
import { getMxIsrTariffs } from "../../../service/superAdminService";
import { ContentFamily, SlabRows, card } from "./mxShared";

// Art. 96 ISR withholding tariffs (spec §4, S2) — one table per payment
// period, read-only. MX-008: the period's own table, never the monthly one
// scaled by a divisor.
const PERIODS = [["DAILY", "Daily"], ["WEEKLY_7", "7 days"], ["DECENAL_10", "10 days"], ["QUINCENAL_15", "15 days"], ["MONTHLY", "Monthly"]];

export default function MXIsrTariffsTab() {
  const [on, setOn] = useState(null);
  return (
    <ContentFamily load={(d) => getMxIsrTariffs(d)} on={on} setOn={setOn} what="Art. 96 ISR tariff">
      {(view) => PERIODS.map(([code, label]) => (
        <div key={code} className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">{label} tariff</h3>
          <SlabRows
            rows={view.slabs.filter((s) => s.key === code)}
            empty={`No ${label.toLowerCase()} tariff transcribed.`}
            columns={[
              { key: "min", label: "Lower limit" }, { key: "max", label: "Upper limit", render: (r) => r.max ?? "and above" },
              { key: "amount", label: "Fixed quota" }, { key: "ratePct", label: "% on excess", render: (r) => `${r.ratePct}%` },
            ]}
          />
        </div>
      ))}
    </ContentFamily>
  );
}
