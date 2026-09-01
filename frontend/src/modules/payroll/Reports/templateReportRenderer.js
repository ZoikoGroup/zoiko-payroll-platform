import { exportToCsv, exportToExcel, exportToPdf } from "../../../utils/exportTable";

// Renders a GeneratedReport API response (backend's frozen rendered_data
// snapshot — see service.generate_report_from_template) into the
// {columns, rows} shape exportTable.js already knows how to export as
// CSV/Excel/PDF. Never recomputes a single value — every number here is
// exactly what the backend resolved from real PayslipItem/PayrollRun data
// and stored at generation time, which is also why this file never calls
// fetchTaxSlabs/getContributionColumns or does arithmetic on payslip
// fields the way the retired pdfGenerators.js report functions did.
export function buildReportTable(generatedReport) {
  const rendered = generatedReport?.renderedData || {};
  const templateSnapshot = rendered.templateSnapshot || { components: [] };
  // AGGREGATE reports (e.g. Form 138, an EPS/FPS-style employer summary)
  // have no per-employee dimension at all — every one of their fields is
  // resolved once at the employer/run level (see generate_report_from_template:
  // any field with dataSourceKind PAYROLL_RUN/EMPLOYER_PROFILE, or a
  // PAYSLIP_ITEM field with aggregation SUM_RUN, is written to
  // rendered_data.employer, never to rendered_data.employees). Treating
  // rendered_data.employees ([] in that case) as "the table" produced a
  // real bug: the export showed column headers with zero rows, even
  // though the actual employer name / aggregated totals were sitting
  // right there in rendered_data.employer the whole time.
  const isAggregate = generatedReport?.documentScope !== "PER_EMPLOYEE";

  const columns = [];
  if (!isAggregate) {
    columns.push({ key: "employeeName", label: "Employee", fieldType: "text", accessor: (row) => row.employeeName });
  }
  templateSnapshot.components.forEach((component) => {
    (component.fields || []).forEach((field) => {
      columns.push({
        key: field.fieldKey,
        label: field.label,
        fieldType: field.type || "text",
        // PER_EMPLOYEE rows nest resolved values under `.values`; the
        // single synthetic AGGREGATE row (rendered_data.employer) is flat.
        accessor: isAggregate ? (row) => row[field.fieldKey] : (row) => row.values?.[field.fieldKey],
      });
    });
  });

  const rows = isAggregate ? [rendered.employer || {}] : (rendered.employees || []);

  return {
    columns,
    rows,
    employer: rendered.employer || {},
    period: rendered.period || {},
    totals: rendered.totals || {},
  };
}

function reportFilenameBase(generatedReport) {
  const name = (generatedReport?.reportType || "report").replace(/[^a-z0-9]+/gi, "_");
  const period = (generatedReport?.reportingPeriod || "").replace(/[^a-z0-9]+/gi, "_");
  return [name, period].filter(Boolean).join("_") || `report_${generatedReport?.id || ""}`;
}

export function downloadGeneratedReportAs(generatedReport, format = "pdf") {
  const { columns, rows } = buildReportTable(generatedReport);
  const filenameBase = reportFilenameBase(generatedReport);
  if (format === "csv") return exportToCsv(columns, rows, `${filenameBase}.csv`);
  if (format === "xlsx") return exportToExcel(columns, rows, `${filenameBase}.xlsx`);
  return exportToPdf(generatedReport?.reportType || "Report", columns, rows, `${filenameBase}.pdf`);
}
