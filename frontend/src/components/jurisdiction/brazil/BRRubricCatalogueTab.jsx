import { NeedOrg, Messages, Table, card, useLoad, cell, yesNoCell } from "./brShared";
import { listBrRubricCatalogue } from "../../../service/superAdminService";

// eSocial Table 03 rubric catalogue (ZP-BR-ENG-001) — READ-ONLY here. A rubric
// maps a payment/deduction code to its nature and its INSS/IRRF/FGTS incidence
// codes; catalogue rows change only through the governed pack editor.
export default function BRRubricCatalogueTab({ orgId }) {
  const [rows, error] = useLoad(() => (orgId ? listBrRubricCatalogue(orgId) : Promise.resolve(null)), [orgId]);
  if (!orgId) return <NeedOrg />;
  return (
    <div className="flex flex-col gap-4">
      <div className={card}>
        <h3 className="mb-1 text-[14px] font-semibold text-foreground">eSocial rubric catalogue (Table 03)</h3>
        <p className="mb-3 text-[12px] text-foreground-muted">
          Read-only. Each rubric&apos;s nature code and incidence codes come from the governed pack — changes only via
          the governed pack editor.
        </p>
        <Messages error={error} />
        <Table rows={rows} empty="No rubrics recorded for this organisation yet." columns={[
          { key: "rubric_code", label: "Rubric", render: cell("rubric_code", "rubricCode") },
          { key: "rubric_name", label: "Name", render: cell("rubric_name", "rubricName", "description") },
          { key: "nature_code", label: "Nature", render: cell("nature_code", "natureCode") },
          { key: "rubric_type", label: "Type", render: cell("rubric_type", "rubricType") },
          { key: "cod_inc_cp", label: "INSS inc.", render: cell("cod_inc_cp", "codIncCp") },
          { key: "cod_inc_irrf", label: "IRRF inc.", render: cell("cod_inc_irrf", "codIncIrrf") },
          { key: "cod_inc_fgts", label: "FGTS inc.", render: cell("cod_inc_fgts", "codIncFgts") },
          { key: "is_system_standard", label: "Standard", render: yesNoCell("is_system_standard", "isSystemStandard") },
          { key: "valid_from", label: "From", render: cell("valid_from", "validFrom") },
          { key: "valid_to", label: "To", render: cell("valid_to", "validTo") },
        ]} />
      </div>
    </div>
  );
}
