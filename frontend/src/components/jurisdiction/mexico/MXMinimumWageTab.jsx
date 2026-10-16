import { useState } from "react";
import { getMxUmaMinWage } from "../../../service/superAdminService";
import { AwaitingTranscription, Messages, OnDateBar, SlabRows, Table, card, useLoad } from "./mxShared";

// Minimum wages by zone and profession, and the ZLFN municipality list
// (spec §2, S9 with S8 as cross-check). Read-only.
export default function MXMinimumWageTab() {
  const [on, setOn] = useState(null);
  const [data, error] = useLoad(() => getMxUmaMinWage(on), [on]);
  const view = data?.minimumWages;
  const zlfn = view?.contentOnly?.zlfnMunicipalities || [];
  return (
    <div className="flex flex-col gap-4">
      <OnDateBar on={on} onChange={setOn} view={view} />
      <Messages error={error} />
      {view && view.awaitingTranscription && <AwaitingTranscription what="minimum-wage content" />}
      {view && !view.awaitingTranscription && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">Daily minimum wages</h3>
          <SlabRows rows={view.slabs} empty="No minimum wage in force on this date." columns={[
            { key: "key", label: "Code" }, { key: "formula", label: "Description" },
            { key: "amount", label: "MXN / day" },
          ]} />
        </div>
      )}
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Northern border zone (ZLFN) municipalities</h3>
        <Table rows={zlfn} rowKey={(m) => `${m.state}-${m.municipality}`}
               empty="No ZLFN municipality list transcribed yet (S9)."
               columns={[{ key: "state", label: "State" }, { key: "municipality", label: "Municipality" },
                         { key: "source", label: "Source" }]} />
      </div>
    </div>
  );
}
