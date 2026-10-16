import { useState } from "react";
import { getMxBenefitsWorkweek } from "../../../service/superAdminService";
import { ContentFamily, RateRows, SlabRows, card } from "./mxShared";

// Benefit floors, the vacation schedule and the workweek (spec §16–§17;
// S26, S18, S19/S20 cross-checks). The 2026 → 2030 workweek steps are dated
// rows — pick a 2027 date to see the next step (MX-048).
export default function MXBenefitsWorkweekTab() {
  const [on, setOn] = useState(null);
  return (
    <ContentFamily load={(d) => getMxBenefitsWorkweek(d)} on={on} setOn={setOn} what="benefit-floor or workweek content">
      {(view) => (
        <>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Statutory benefit floors</h3>
            <RateRows rows={view.rates} empty="No benefit floor in force on this date." />
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Workweek</h3>
            <SlabRows rows={view.slabs.filter((s) => s.ruleType === "MX_WORKWEEK")} empty="No workweek row in force on this date."
                      columns={[{ key: "amount", label: "Ordinary hours / week" }, { key: "formula", label: "Overtime rules" }]} />
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Vacation days by years of service</h3>
            <SlabRows rows={view.slabs.filter((s) => s.ruleType === "MX_VACATION_DAYS")} empty="No vacation schedule in force on this date."
                      columns={[{ key: "min", label: "From year" }, { key: "max", label: "To year", render: (r) => r.max ?? "onward" },
                                { key: "amount", label: "Days" }]} />
          </div>
        </>
      )}
    </ContentFamily>
  );
}
