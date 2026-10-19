import { useState } from "react";
import { getMxUmaMinWage } from "../../../service/superAdminService";
import { AwaitingTranscription, Messages, OnDateBar, RateRows, card, useLoad } from "./mxShared";

// UMA and the employment subsidy (spec §2, §5; S3/S6/S7). The 1 February
// UMA change is a true effective-date boundary (MX-004): pick 31 Jan and
// 1 Feb to see each month's rows.
export default function MXSubsidyUmaTab() {
  const [on, setOn] = useState(null);
  const [data, error] = useLoad(() => getMxUmaMinWage(on), [on]);
  const view = data?.uma;
  return (
    <div className="flex flex-col gap-4">
      <OnDateBar on={on} onChange={setOn} view={view} />
      <Messages error={error} />
      {view && view.awaitingTranscription && <AwaitingTranscription what="UMA or employment-subsidy content" />}
      {view && !view.awaitingTranscription && (
        <>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">UMA</h3>
            <RateRows rows={view.rates.filter((r) => r.key.startsWith("mx_uma_"))} empty="No UMA row in force on this date." />
          </div>
          <div className={card}>
            <h3 className="mb-2 text-[14px] font-semibold text-foreground">Employment subsidy</h3>
            <RateRows rows={view.rates.filter((r) => r.key.startsWith("mx_subsidy_"))} empty="No subsidy row in force on this date." />
          </div>
        </>
      )}
    </div>
  );
}
