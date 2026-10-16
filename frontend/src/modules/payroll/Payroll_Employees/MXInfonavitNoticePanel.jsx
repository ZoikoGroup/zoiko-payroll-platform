import { recordMxInfonavitNotice } from "../../../service/payrollService";
import { Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";
import { blankToNull } from "../../../components/jurisdiction/mexico/employer/employerUtils";

// INFONAVIT credit notices (ZP-MX-ENG-001 §10, MX-031/MX-032): a housing-credit
// deduction exists ONLY from the authority's notice, recorded with that notice
// as evidence — method and value are copied from it, never chosen here. A
// MODIFICACION supersedes the open notice; a SUSPENSION closes it. No notice =
// no credit withholding. Nothing is deducted before the engine (Phase 5).
export default function MXInfonavitNoticePanel({ employeeId, notices, onChange }) {
  const { run, error, notice, busy } = useAction(onChange);
  return (
    <Panel title="INFONAVIT credit notices" testId="mx-infonavit-notices"
      hint="Record only what the INFONAVIT notice says, with the notice uploaded as a compliance document. The employer's 5% housing contribution is separate and computed by the engine.">
      <Table rows={notices} empty="No INFONAVIT notice — no credit withholding." columns={[
        { key: "creditNumber", label: "Credit" }, { key: "noticeType", label: "Notice" },
        { key: "discountMethod", label: "Method" }, { key: "discountValue", label: "Value" },
        { key: "effectiveFrom", label: "From" }, { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
        { key: "authorityReference", label: "Authority ref" }, { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
      ]} />
      <MiniForm
        testId="mx-new-notice" submitLabel="Record notice" busy={busy} error={error} notice={notice}
        fields={[
          { key: "creditNumber", label: "Credit number", required: true },
          { key: "noticeType", label: "Notice type", type: "select", options: ["RETENCION", "MODIFICACION", "SUSPENSION"], required: true },
          { key: "discountMethod", label: "Discount method (from the notice)", type: "select", options: ["FIXED_AMOUNT", "PERCENTAGE", "VSM", "UMA_FACTOR"] },
          { key: "discountValue", label: "Discount value (from the notice)" },
          { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
          { key: "authorityReference", label: "Authority reference", required: true },
          { key: "evidenceDocumentId", label: "Evidence document id (uploaded notice)" },
        ]}
        onSubmit={(s) => run(() => recordMxInfonavitNotice(employeeId, blankToNull({
          ...s, evidenceDocumentId: s.evidenceDocumentId ? Number(s.evidenceDocumentId) : null,
        })), "Notice recorded.")}
      />
    </Panel>
  );
}
