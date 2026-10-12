import pdfMake from "pdfmake/build/pdfmake";
import pdfFonts from "pdfmake/build/vfs_fonts";
import { getCurrencyInfo } from "../../../utils/currency";

pdfMake.vfs = pdfFonts.pdfMake ? pdfFonts.pdfMake.vfs : pdfFonts.vfs;

// Shared pdfMake building blocks, kept from the retired per-report
// generators below (removed: generateAnnualTaxSummary/generateTDSReport/
// generatePFStatement/generateESIReport/generateContributionStatement, and
// their client-side tax-recompute helpers parseSlabAmount/parseSlabRate/
// computeProgressiveTax). Reports are now generated server-side against a
// published Report Template + real payroll-run data (see
// service.generateReport / templateReportRenderer.js) instead of being
// re-derived from raw payslip fields in the browser — the exact numbers a
// report shows must always match what payroll actually calculated.
export const BRAND = "#19C58A";
export const DARK = "#1A1816";
export const MUTED = "#9E9690";
export const BORDER = "#E5E0D9";
export const WHITE = "#FFFFFF";

export function currency(val, code = "INR") {
  const n = Number(val) || 0;
  // Locale drives digit grouping (e.g. 1,00,000 vs 100,000) — was hardcoded
  // to en-IN regardless of the actual currency code passed in.
  const locale = getCurrencyInfo(code)?.locale || "en-IN";
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency: code, maximumFractionDigits: 0 }).format(n);
  } catch {
    return `${code} ${n.toLocaleString()}`;
  }
}

export function num(val) {
  return Number(val) || 0;
}

export function maskPan(pan) {
  if (!pan || pan.length < 8) return pan || "—";
  return "XXXXX" + pan.slice(5);
}

export function headerBlock(title, subtitle, company) {
  const companyName = company?.name?.trim() || "Company Name Not Set";
  const companyAddress = company?.address?.trim() || "";
  return [
    {
      columns: [
        {
          stack: [
            { text: companyName, fontSize: 14, bold: true, color: BRAND },
            companyAddress ? { text: companyAddress, fontSize: 8, color: MUTED, margin: [0, 2, 0, 0] } : null,
            { text: "Payroll Management System", fontSize: 9, color: MUTED, margin: [0, 2, 0, 0] },
          ].filter(Boolean),
          width: "*",
        },
        {
          text: new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }),
          fontSize: 9,
          color: MUTED,
          alignment: "right",
          width: "auto",
        },
      ],
      margin: [0, 0, 0, 10],
    },
    {
      text: title,
      fontSize: 16,
      bold: true,
      color: DARK,
      margin: [0, 0, 0, 2],
    },
    {
      text: subtitle,
      fontSize: 10,
      color: MUTED,
      margin: [0, 0, 0, 12],
    },
    {
      canvas: [{ type: "line", x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 1, lineColor: BRAND }],
      margin: [0, 0, 0, 12],
    },
  ];
}

export function footerBlock(company) {
  const companyName = company?.name?.trim() || "Company";
  return {
    margin: [0, 20, 0, 0],
    canvas: [{ type: "line", x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, lineColor: BORDER }],
    stack: [
      { text: "This is a system-generated report. No signature required.", fontSize: 8, color: MUTED, margin: [0, 6, 0, 0], alignment: "center" },
      { text: `${companyName} | Confidential`, fontSize: 8, color: MUTED, margin: [0, 2, 0, 0], alignment: "center" },
    ],
  };
}

export function dataRow(cells, colWidths, isEven, aligns) {
  return cells.map((c, i) => ({
    text: c,
    fontSize: 8,
    color: DARK,
    alignment: (aligns && aligns[i]) || "center",
    fillColor: isEven ? "#F8F7F4" : WHITE,
    margin: [3, 3, 3, 3],
  }));
}

export function generateAndDownload(docDefinition, filename) {
  pdfMake.createPdf(docDefinition).download(filename);
}
