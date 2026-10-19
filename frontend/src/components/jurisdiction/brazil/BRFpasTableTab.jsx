import { Messages, Table, card, useLoad, cell } from "./brShared";
import { getBrFpasTable } from "../../../service/superAdminService";

// FPAS classification (Tabela 04) — READ-ONLY global reference. Each FPAS code
// carries the third-party (terceiros) rate alongside the establishment's own
// RAT/FAP adjustments; the table is authority content, never edited here.
export default function BRFpasTableTab() {
  const [data, error] = useLoad(() => getBrFpasTable(), []);
  return (
    <div className="flex flex-col gap-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">FPAS / Tabela 04</h3>
        <p className="mb-3 text-[12px] text-foreground-muted">
          Read-only classification table. The FPAS code an establishment declares drives its third-party (terceiros)
          contribution rates — shown here for reference, changed only via the governed pack editor.
        </p>
        <Messages error={error} />
        {data?.note && <p className="mb-3 text-[12px] text-foreground-muted">{data.note}</p>}
        <Table rows={data} empty="No FPAS rows loaded." columns={[
          { key: "fpas_code", label: "FPAS", render: cell("fpas_code", "fpasCode", "code") },
          { key: "description", label: "Description", render: cell("description", "title", "label") },
          { key: "third_party_code", label: "Terceiros code", render: cell("third_party_code", "thirdPartyCode") },
          { key: "third_party_pct", label: "Terceiros %", render: cell("third_party_pct", "thirdPartyPct") },
          { key: "rat_pct", label: "RAT %", render: cell("rat_pct", "ratPct") },
          { key: "fap_factor", label: "FAP", render: cell("fap_factor", "fapFactor") },
          { key: "effective_from", label: "From", render: cell("effective_from", "effectiveFrom") },
          { key: "status", label: "Status", render: cell("status") },
        ]} />
      </div>
    </div>
  );
}
