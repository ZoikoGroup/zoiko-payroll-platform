import pdfMake from "pdfmake/build/pdfmake";
import pdfFonts from "pdfmake/build/vfs_fonts";
import { getCurrencyInfo } from "../../../utils/currency";
import { fetchTaxSlabs, getContributionColumns } from "../../../service/payrollService";

pdfMake.vfs = pdfFonts.pdfMake ? pdfFonts.pdfMake.vfs : pdfFonts.vfs;

const BRAND = "#19C58A";
const DARK = "#1A1816";
const MUTED = "#9E9690";
const BORDER = "#E5E0D9";
const WHITE = "#FFFFFF";

function currency(val, code = "INR") {
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

function num(val) {
  return Number(val) || 0;
}

function maskPan(pan) {
  if (!pan || pan.length < 8) return pan || "—";
  return "XXXXX" + pan.slice(5);
}

function headerBlock(title, subtitle, company) {
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

function footerBlock(company) {
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

function dataRow(cells, colWidths, isEven, aligns) {
  return cells.map((c, i) => ({
    text: c,
    fontSize: 8,
    color: DARK,
    alignment: (aligns && aligns[i]) || "center",
    fillColor: isEven ? "#F8F7F4" : WHITE,
    margin: [3, 3, 3, 3],
  }));
}

function generateAndDownload(docDefinition, filename) {
  pdfMake.createPdf(docDefinition).download(filename);
}

// Slab boundaries/rates come back from fetchTaxSlabs() as display strings
// (e.g. "₹4,00,000", "A$18,200", "37%", "Nil", "Above") — this strips
// formatting to get back to plain numbers, so the same progressive-tax
// math works for every jurisdiction's slabs, not just India's.
function parseSlabAmount(str) {
  if (!str || /above/i.test(str)) return Infinity;
  const digits = String(str).replace(/[^0-9.]/g, "");
  return digits ? Number(digits) : 0;
}

function parseSlabRate(str) {
  if (!str || /nil/i.test(str)) return 0;
  const digits = String(str).replace(/[^0-9.]/g, "");
  return digits ? Number(digits) / 100 : 0;
}

function computeProgressiveTax(taxableIncome, slabs) {
  let tax = 0;
  const sorted = [...(slabs || [])].sort((a, b) => parseSlabAmount(a.min) - parseSlabAmount(b.min));
  for (const s of sorted) {
    const lower = parseSlabAmount(s.min);
    const upper = parseSlabAmount(s.max);
    if (taxableIncome <= lower) continue;
    const taxableInBand = Math.min(taxableIncome, upper) - lower;
    if (taxableInBand > 0) tax += taxableInBand * parseSlabRate(s.rate);
  }
  return Math.round(tax);
}

// ═══════════════════════════════════════════════════════════════
// Report 1: Annual Tax Summary (Portrait A4)
// ═══════════════════════════════════════════════════════════════
export async function generateAnnualTaxSummary(employees, payslips, currencyCode = "INR", company = null, country = "IN") {
  // India's new-regime standard deduction is a fixed amount on top of its
  // slabs; other jurisdictions' slabs already start with their own 0%/
  // allowance band (UK personal allowance, AU tax-free threshold, etc.),
  // so applying an India-sized deduction to them would double-count.
  const STANDARD_DEDUCTION = country === "IN" ? 75000 : 0;
  const slabs = await fetchTaxSlabs(country);

  const employeeMap = {};
  (employees || []).forEach((e) => {
    employeeMap[String(e.id || e.portal_id || "")] = e;
  });

  const ytdData = {};
  (payslips || []).forEach((p) => {
    const eid = String(p.employeeId || p.employee_id || "");
    if (!eid) return;
    if (!ytdData[eid]) {
      ytdData[eid] = {
        gross: 0,
        hra: 0,
        specialAllowance: 0,
        lta: 0,
        medicalAllowance: 0,
        tds: 0,
        pf: 0,
        esi: 0,
        professionalTax: 0,
        basicPay: 0,
      };
    }
    const d = ytdData[eid];
    d.gross += num(p.basicPay) + num(p.hra) + num(p.specialAllowance) + num(p.overtime) + num(p.additionalCompensation);
    d.hra += num(p.hra);
    d.specialAllowance += num(p.specialAllowance);
    d.lta += num(p.lta);
    d.medicalAllowance += num(p.medicalAllowance);
    d.tds += num(p.tds);
    d.pf += num(p.pf);
    d.esi += num(p.esi);
    d.professionalTax += num(p.professionalTax);
    d.basicPay += num(p.basicPay);
  });

  const rows = Object.keys(ytdData).map((eid) => {
    const emp = employeeMap[eid] || {};
    const d = ytdData[eid];
    const exemptions = d.hra + d.lta + d.medicalAllowance;
    const netTaxable = Math.max(0, d.gross - exemptions - STANDARD_DEDUCTION);
    const projectedTax = computeProgressiveTax(netTaxable, slabs);
    const outstanding = projectedTax - d.tds;
    return {
      empId: emp.portal_id || emp.employeeCode || eid,
      name: emp.full_name || emp.name || "—",
      ytdGross: d.gross,
      exemptions,
      netTaxable,
      projectedTax,
      actualTds: d.tds,
      outstanding,
    };
  });

  const colWidths = [50, 80, 65, 60, 60, 60, 60, 60];
  const header = ["Employee ID", "Employee Name", "YTD Gross", country === "IN" ? "Exemptions\n(Sec 10)" : "Exemptions", "Std Deduction", "Net Taxable\nIncome", "Projected\nTax", "Outstanding\nTax"];

  const body = [
    ...headerBlock("Annual Tax Summary", "Financial Year 2026–27 | Income Tax Projection vs. Actual", company),
    {
      table: {
        headerRows: 1,
        widths: colWidths,
        body: [
          header.map((h) => ({
            text: h,
            bold: true,
            fontSize: 7.5,
            color: WHITE,
            fillColor: BRAND,
            alignment: "center",
            margin: [3, 4, 3, 4],
          })),
          ...rows.map((r, i) => dataRow(
            [
              r.empId,
              r.name,
              currency(r.ytdGross, currencyCode),
              currency(r.exemptions, currencyCode),
              currency(STANDARD_DEDUCTION, currencyCode),
              currency(r.netTaxable, currencyCode),
              currency(r.projectedTax, currencyCode),
              currency(r.outstanding, currencyCode),
            ],
            colWidths,
            i % 2 === 0,
            ["center", "left", "right", "right", "right", "right", "right", "right"],
          )),
        ],
      },
      layout: {
        hLineWidth: (i) => (i === 0 ? 0.5 : 0.25),
        vLineWidth: () => 0.25,
        hLineColor: () => BORDER,
        vLineColor: () => BORDER,
      },
    },
    footerBlock(company),
  ];

  generateAndDownload({ content: body, pageSize: "A4", pageOrientation: "portrait", defaultStyle: { fontSize: 8 } }, "Annual_Tax_Summary.pdf");
}

// ═══════════════════════════════════════════════════════════════
// Report 2: TDS Report (Landscape A4)
// ═══════════════════════════════════════════════════════════════
export function generateTDSReport(employees, payslips, currencyCode = "INR", company = null) {
  const employeeMap = {};
  (employees || []).forEach((e) => {
    employeeMap[String(e.id || e.portal_id || "")] = e;
  });

  const quarterlyData = {};
  (payslips || []).forEach((p) => {
    const eid = String(p.employeeId || p.employee_id || "");
    if (!eid) return;
    if (!quarterlyData[eid]) {
      quarterlyData[eid] = { gross: 0, taxableIncome: 0, tds: 0, count: 0 };
    }
    const q = quarterlyData[eid];
    const gross = num(p.basicPay) + num(p.hra) + num(p.specialAllowance) + num(p.overtime) + num(p.additionalCompensation);
    q.gross += gross;
    q.taxableIncome += Math.max(0, gross - num(p.pf) - num(p.esi) - 75000 / 12);
    q.tds += num(p.tds);
    q.count++;
  });

  const rows = Object.keys(quarterlyData).map((eid) => {
    const emp = employeeMap[eid] || {};
    const q = quarterlyData[eid];
    const cess = Math.round(q.tds * 0.04);
    return {
      name: emp.full_name || emp.name || "—",
      pan: emp.pan_card || emp.pan || emp.panNumber || "",
      grossPaid: q.gross,
      taxableIncome: q.taxableIncome,
      tds: q.tds,
      cess,
      totalDeposit: q.tds + cess,
    };
  });

  const colWidths = [25, 100, 65, 80, 80, 70, 60, 70];
  const header = ["Sl. No.", "Employee Name", "PAN", "Gross Paid\nAmount", "Taxable\nIncome", "TDS\nDeducted", "Cess\n(4%)", "Total Tax\nDeposited"];

  const body = [
    ...headerBlock("TDS Report — Quarterly", "Section 192 | Form 24Q (Annexure II) | Quarter ending Mar 2027", company),
    {
      text: "Statutory Authority: Income Tax Department of India",
      fontSize: 8,
      color: MUTED,
      margin: [0, 0, 0, 8],
    },
    {
      table: {
        headerRows: 1,
        widths: colWidths,
        body: [
          header.map((h) => ({
            text: h,
            bold: true,
            fontSize: 7.5,
            color: WHITE,
            fillColor: BRAND,
            alignment: "center",
            margin: [3, 4, 3, 4],
          })),
          ...rows.map((r, i) => dataRow(
            [
              String(i + 1),
              r.name,
              maskPan(r.pan),
              currency(r.grossPaid, currencyCode),
              currency(r.taxableIncome, currencyCode),
              currency(r.tds, currencyCode),
              currency(r.cess, currencyCode),
              currency(r.totalDeposit, currencyCode),
            ],
            colWidths,
            i % 2 === 0,
            ["center", "left", "center", "right", "right", "right", "right", "right"],
          )),
        ],
      },
      layout: {
        hLineWidth: (i) => (i === 0 ? 0.5 : 0.25),
        vLineWidth: () => 0.25,
        hLineColor: () => BORDER,
        vLineColor: () => BORDER,
      },
    },
    footerBlock(company),
  ];

  generateAndDownload({ content: body, pageSize: "A4", pageOrientation: "landscape", defaultStyle: { fontSize: 8 } }, "TDS_Report.pdf");
}

// ═══════════════════════════════════════════════════════════════
// Report 3: PF Statement (Landscape A4)
// ═══════════════════════════════════════════════════════════════
export function generatePFStatement(employees, payslips, currencyCode = "INR", company = null) {
  const PF_CAP = 15000;

  const employeeMap = {};
  (employees || []).forEach((e) => {
    employeeMap[String(e.id || e.portal_id || "")] = e;
  });

  const monthlyData = {};
  (payslips || []).forEach((p) => {
    const eid = String(p.employeeId || p.employee_id || "");
    if (!eid) return;
    if (!monthlyData[eid]) {
      monthlyData[eid] = {
        grossWages: 0,
        epfWages: 0,
        epsWages: 0,
        edliWages: 0,
        ncpDays: 0,
      };
    }
    const m = monthlyData[eid];
    const gross = num(p.basicPay) + num(p.hra) + num(p.specialAllowance);
    m.grossWages += gross;
    const capped = Math.min(num(p.basicPay) || gross, PF_CAP);
    m.epfWages += capped;
    m.epsWages += capped;
    m.edliWages += capped;
    m.ncpDays += num(p.ncpDays);
  });

  const rows = Object.keys(monthlyData).map((eid) => {
    const emp = employeeMap[eid] || {};
    const m = monthlyData[eid];
    const eePF = Math.round(m.epfWages * 0.12);
    const erPension = Math.round(m.epsWages * 0.0833);
    const erEPF = eePF - erPension;
    return {
      uan: emp.uan_number || emp.uan || "—",
      name: emp.full_name || emp.name || "—",
      grossWages: m.grossWages,
      epfWages: m.epfWages,
      epsWages: m.epsWages,
      edliWages: m.edliWages,
      eePF,
      erPension,
      erEPF,
      ncpDays: m.ncpDays,
    };
  });

  const colWidths = [60, 80, 58, 55, 55, 55, 55, 55, 55, 35];
  const header = ["UAN", "Member Name", "Gross\nWages", "EPF\nWages", "EPS\nWages", "EDLI\nWages", "EE PF\n(12%)", "ER Pension\n(8.33%)", "ER EPF\n(3.67%)", "NCP\nDays"];

  const body = [
    ...headerBlock("PF Statement (ECR Format)", "Electronic Challan-cum-Return | Monthly EPFO Upload", company),
    {
      table: {
        headerRows: 1,
        widths: colWidths,
        body: [
          header.map((h) => ({
            text: h,
            bold: true,
            fontSize: 7,
            color: WHITE,
            fillColor: BRAND,
            alignment: "center",
            margin: [2, 4, 2, 4],
          })),
          ...rows.map((r, i) => dataRow(
            [
              r.uan,
              r.name,
              currency(r.grossWages, currencyCode),
              currency(r.epfWages, currencyCode),
              currency(r.epsWages, currencyCode),
              currency(r.edliWages, currencyCode),
              currency(r.eePF, currencyCode),
              currency(r.erPension, currencyCode),
              currency(r.erEPF, currencyCode),
              String(r.ncpDays),
            ],
            colWidths,
            i % 2 === 0,
            ["center", "left", "right", "right", "right", "right", "right", "right", "right", "center"],
          )),
        ],
      },
      layout: {
        hLineWidth: (i) => (i === 0 ? 0.5 : 0.25),
        vLineWidth: () => 0.25,
        hLineColor: () => BORDER,
        vLineColor: () => BORDER,
      },
    },
    footerBlock(company),
  ];

  generateAndDownload({ content: body, pageSize: "A4", pageOrientation: "landscape", defaultStyle: { fontSize: 8 } }, "PF_Statement.pdf");
}

// ═══════════════════════════════════════════════════════════════
// Report 4: ESI Report (Portrait A4)
// ═══════════════════════════════════════════════════════════════
export function generateESIReport(employees, payslips, currencyCode = "INR", company = null) {
  const ESI_CAP = 21000;
  const EE_RATE = 0.0075;
  const ER_RATE = 0.0325;

  const employeeMap = {};
  (employees || []).forEach((e) => {
    employeeMap[String(e.id || e.portal_id || "")] = e;
  });

  const monthlyData = {};
  (payslips || []).forEach((p) => {
    const eid = String(p.employeeId || p.employee_id || "");
    if (!eid) return;
    const gross = num(p.basicPay) + num(p.hra) + num(p.specialAllowance);
    if (gross > ESI_CAP) return;

    if (!monthlyData[eid]) {
      monthlyData[eid] = { totalWages: 0, daysWorked: 0 };
    }
    monthlyData[eid].totalWages += gross;
    monthlyData[eid].daysWorked += num(p.payableDays) || 30;
  });

  const rows = Object.keys(monthlyData).map((eid) => {
    const emp = employeeMap[eid] || {};
    const m = monthlyData[eid];
    const eeContrib = Math.round(m.totalWages * EE_RATE);
    const erContrib = Math.round(m.totalWages * ER_RATE);
    return {
      ipNumber: emp.esi_number || emp.esiNumber || "—",
      name: emp.full_name || emp.name || "—",
      daysWorked: m.daysWorked,
      totalWages: m.totalWages,
      eeContrib,
      erContrib,
      totalContrib: eeContrib + erContrib,
    };
  });

  const colWidths = [70, 95, 55, 65, 70, 70, 70];
  const header = ["IP Number", "IP Name", "Days\nWorked", "Total\nWages", "Employee\n(0.75%)", "Employer\n(3.25%)", "Total ESI\n(4%)"];

  const body = [
    ...headerBlock("ESI Report", "Employee State Insurance | Monthly ESIC Contribution Statement", company),
    {
      text: "Applicable for employees with gross monthly wages under \u20B921,000",
      fontSize: 8,
      color: MUTED,
      margin: [0, 0, 0, 8],
    },
    {
      table: {
        headerRows: 1,
        widths: colWidths,
        body: [
          header.map((h) => ({
            text: h,
            bold: true,
            fontSize: 7.5,
            color: WHITE,
            fillColor: BRAND,
            alignment: "center",
            margin: [3, 4, 3, 4],
          })),
          ...rows.map((r, i) => dataRow(
            [
              r.ipNumber,
              r.name,
              String(r.daysWorked),
              currency(r.totalWages, currencyCode),
              currency(r.eeContrib, currencyCode),
              currency(r.erContrib, currencyCode),
              currency(r.totalContrib, currencyCode),
            ],
            colWidths,
            i % 2 === 0,
            ["center", "left", "center", "right", "right", "right", "right"],
          )),
        ],
      },
      layout: {
        hLineWidth: (i) => (i === 0 ? 0.5 : 0.25),
        vLineWidth: () => 0.25,
        hLineColor: () => BORDER,
        vLineColor: () => BORDER,
      },
    },
    footerBlock(company),
  ];

  generateAndDownload({ content: body, pageSize: "A4", pageOrientation: "portrait", defaultStyle: { fontSize: 8 } }, "ESI_Report.pdf");
}

// ═══════════════════════════════════════════════════════════════
// Report 5: Contribution Statement (Portrait A4) — jurisdiction-aware
// replacement for the PF/ESI/TDS reports outside India. Shows whichever
// statutory contributions actually apply to the active jurisdiction
// (Superannuation/Medicare Levy for AU, Social Security/Medicare for US,
// National Insurance for UK, Pension/Social Insurance for DE, CPP/EI for
// CA) instead of assuming India's PF/ESI.
// ═══════════════════════════════════════════════════════════════
export function generateContributionStatement(employees, payslips, currencyCode = "INR", company = null, country = "IN") {
  const columns = getContributionColumns(country);

  const employeeMap = {};
  (employees || []).forEach((e) => {
    employeeMap[String(e.id || e.portal_id || "")] = e;
  });

  const totalsByEmployee = {};
  (payslips || []).forEach((p) => {
    const eid = String(p.employeeId || p.employee_id || "");
    if (!eid) return;
    if (!totalsByEmployee[eid]) {
      totalsByEmployee[eid] = { gross: 0, byColumn: {} };
      columns.forEach((col) => { totalsByEmployee[eid].byColumn[col.id] = 0; });
    }
    const t = totalsByEmployee[eid];
    t.gross += num(p.basicPay) + num(p.hra) + num(p.specialAllowance) + num(p.overtime) + num(p.additionalCompensation);
    columns.forEach((col) => { t.byColumn[col.id] += num(p[col.payslipField]); });
  });

  const rows = Object.keys(totalsByEmployee).map((eid) => {
    const emp = employeeMap[eid] || {};
    const t = totalsByEmployee[eid];
    const totalContributions = columns.reduce((sum, col) => sum + t.byColumn[col.id], 0);
    return {
      name: emp.full_name || emp.name || "—",
      gross: t.gross,
      byColumn: t.byColumn,
      total: totalContributions,
    };
  });

  const colWidths = [30, 110, 70, ...columns.map(() => 65), 70];
  const header = ["Sl. No.", "Employee Name", "Gross Paid", ...columns.map((c) => c.label), "Total Contributions"];

  const body = [
    ...headerBlock("Contribution Statement", "Statutory contribution summary for the active payroll jurisdiction", company),
    {
      table: {
        headerRows: 1,
        widths: colWidths,
        body: [
          header.map((h) => ({
            text: h,
            bold: true,
            fontSize: 7.5,
            color: WHITE,
            fillColor: BRAND,
            alignment: "center",
            margin: [3, 4, 3, 4],
          })),
          ...rows.map((r, i) => dataRow(
            [
              String(i + 1),
              r.name,
              currency(r.gross, currencyCode),
              ...columns.map((c) => currency(r.byColumn[c.id], currencyCode)),
              currency(r.total, currencyCode),
            ],
            colWidths,
            i % 2 === 0,
            ["center", "left", "right", ...columns.map(() => "right"), "right"],
          )),
        ],
      },
      layout: {
        hLineWidth: (i) => (i === 0 ? 0.5 : 0.25),
        vLineWidth: () => 0.25,
        hLineColor: () => BORDER,
        vLineColor: () => BORDER,
      },
    },
    footerBlock(company),
  ];

  generateAndDownload({ content: body, pageSize: "A4", pageOrientation: rows.length && columns.length > 2 ? "landscape" : "portrait", defaultStyle: { fontSize: 8 } }, "Contribution_Statement.pdf");
}
