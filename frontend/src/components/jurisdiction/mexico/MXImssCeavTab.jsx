import { useState } from "react";
import { getMxCeavSchedule, getMxImssBranches } from "../../../service/superAdminService";
import { AwaitingTranscription, Messages, OnDateBar, RateRows, SlabRows, Table, card, useLoad } from "./mxShared";

// IMSS branches and the SBC ceiling (spec §7–§8, S10) and Cesantía y Vejez
// (spec §9, S11). Each branch and side is its own row (MX-023). Only the
// 2026 CEAV bands are in the 2026 pack; the 2023–2030 schedule is content
// only, selected by date (MX-029).
export default function MXImssCeavTab() {
  const [on, setOn] = useState(null);
  const [imss, imssError] = useLoad(() => getMxImssBranches(on), [on]);
  const [ceav, ceavError] = useLoad(() => getMxCeavSchedule(on), [on]);
  const schedule = ceav?.contentOnly?.schedule || [];
  return (
    <div className="flex flex-col gap-4">
      <OnDateBar on={on} onChange={setOn} view={imss} />
      <Messages error={imssError || ceavError} />
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">IMSS branches and SBC ceiling</h3>
        {imss && (imss.awaitingTranscription
          ? <AwaitingTranscription what="IMSS branch content" />
          : <RateRows rows={imss.rates} empty="No IMSS row in force on this date." />)}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">Cesantía y Vejez — seeded bands</h3>
        {ceav && (ceav.awaitingTranscription
          ? <AwaitingTranscription what="CEAV content" />
          : (
            <>
              <SlabRows rows={ceav.slabs} empty="No CEAV band in force on this date." columns={[
                { key: "table", label: "Year" }, { key: "formula", label: "SBC band" },
                { key: "ratePct", label: "Employer %", render: (r) => `${r.ratePct}%` },
              ]} />
              <RateRows rows={ceav.rates} empty="No CEAV parameter in force on this date." />
            </>
          ))}
      </div>
      <div className={card}>
        <h3 className="mb-2 text-[14px] font-semibold text-foreground">CEAV 2023–2030 schedule (content only, not seeded)</h3>
        <Table rows={schedule} rowKey={(b) => `${b.year}-${b.lower}${b.lowerUnit}`}
               empty="The 2023–2030 schedule is not transcribed yet (S11)."
               columns={[{ key: "year", label: "Year" },
                         { key: "band", label: "Band", render: (b) => `${b.lower} ${b.lowerUnit} – ${b.upper ?? "∞"} ${b.upperUnit || ""}` },
                         { key: "employerPct", label: "Employer %" },
                         { key: "seeded", label: "In 2026 pack", render: (b) => (b.seeded ? "Yes" : "No") },
                         { key: "source", label: "Source", render: (b) => <span className="text-[11px]">{b.source}</span> }]} />
      </div>
    </div>
  );
}
