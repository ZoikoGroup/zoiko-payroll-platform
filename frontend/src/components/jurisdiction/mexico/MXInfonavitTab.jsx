import { useState } from "react";
import { getMxInfonavit } from "../../../service/superAdminService";
import { ContentFamily, RateRows, card } from "./mxShared";

// INFONAVIT employer housing contribution (spec §10; S27, S15 cross-check).
// Employee credit withholding is authority-notice-driven (MX-031) and is
// recorded per employee from Phase 4 — never a rate configured here.
export default function MXInfonavitTab() {
  const [on, setOn] = useState(null);
  return (
    <ContentFamily load={(d) => getMxInfonavit(d)} on={on} setOn={setOn} what="INFONAVIT content">
      {(view) => (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Employer housing contribution</h3>
          <RateRows rows={view.rates} empty="No INFONAVIT row in force on this date." />
        </div>
      )}
    </ContentFamily>
  );
}
