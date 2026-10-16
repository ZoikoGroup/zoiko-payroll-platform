import { Messages, Table, card, useLoad, cell, yesNoCell } from "./brShared";
import { listBrRubricCatalogue } from "../../../service/superAdminService";

// eSocial Table 03 rubric catalogue (ZP-BR-ENG-001) — READ-ONLY here. A rubric
// maps a payment/deduction code to its nature and its INSS/IRRF/FGTS incidence
// codes. The canonical catalogue is served without an organisation; choosing
// one above appends that organisation's own rows (Source column).
export default function BRRubricCatalogueTab({ orgId }) {
  const [data, error] = useLoad(() => listBrRubricCatalogue(orgId), [orgId]);
  return (
    <div className="flex flex-col gap-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">eSocial rubric catalogue (Table 03)</h3>
        <p className="mb-3 text-[12px] text-foreground-muted">
          Read-only. Canonical rubrics{orgId ? " plus the selected organisation's own rows" : " — select an organisation above to add its own rows"}.
          Catalogue rows change only via the governed pack editor.
        </p>
        <Messages error={error} />
        {data?.note && (
          <p role="note" className="mb-3 rounded-lg border border-warning bg-warning/10 px-3 py-2 text-[12px] text-foreground">
            {data.note}
          </p>
        )}
        <Table rows={data} rowKey={(r) => `${r.source}:${r.rubric_code}:${r.valid_from}`}
          empty="No rubrics in the catalogue." columns={[
          { key: "rubric_code", label: "Rubric", render: cell("rubric_code", "rubricCode") },
          { key: "rubric_name", label: "Name", render: cell("rubric_name", "rubricName", "description") },
          { key: "nature_code", label: "Nature", render: cell("nature_code", "natureCode") },
          { key: "rubric_type", label: "Type", render: cell("rubric_type", "rubricType") },
          { key: "cod_inc_cp", label: "INSS inc.", render: cell("cod_inc_cp", "codIncCp") },
          { key: "cod_inc_irrf", label: "IRRF inc.", render: cell("cod_inc_irrf", "codIncIrrf") },
          { key: "cod_inc_fgts", label: "FGTS inc.", render: cell("cod_inc_fgts", "codIncFgts") },
          { key: "is_system_standard", label: "Standard", render: yesNoCell("is_system_standard", "isSystemStandard") },
          { key: "source", label: "Source", render: cell("source") },
          { key: "valid_from", label: "From", render: cell("valid_from", "validFrom") },
          { key: "valid_to", label: "To", render: cell("valid_to", "validTo") },
        ]} />
      </div>
    </div>
  );
}
