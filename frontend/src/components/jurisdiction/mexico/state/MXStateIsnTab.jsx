import { useState } from "react";
import { getMxIsnContent } from "../../../../service/superAdminService";
import { ContentFamily, RateRows } from "../mxShared";

// One state ISN pack's rows, read-only, as legally in force on the chosen
// date, each with its source and [PENDING G1] marker (completion W5-1).
// Mexico statutory content changes only through the governed pack lifecycle
// (seeded from mexico_content and re-proven at activation), never by a
// direct row edit here.
export default function MXStateIsnTab({ packId }) {
  const [on, setOn] = useState(null);
  return (
    <div className="flex flex-col gap-3">
      <ContentFamily load={(date) => getMxIsnContent(packId, date)} on={on} setOn={setOn} what="ISN rate for this state">
        {(view) => <RateRows rows={view.rates} empty="No ISN row in force on this date." />}
      </ContentFamily>
      <p className="text-[11px] text-foreground-muted">
        The state ISN base is independent of federal ISR and IMSS SBC (§15); unsupported states are hard-blocked.
        Which special payments count toward the base is on the Statutory rules tab.
      </p>
    </div>
  );
}
