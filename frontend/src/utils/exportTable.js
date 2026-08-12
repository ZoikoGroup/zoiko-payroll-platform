// Shared table export utility — CSV / Excel / PDF from the same
// {columns, rows} shape. Every existing export in the app (EmployeeListPage,
// AttendancePage, pdfGenerators.js) rebuilds this logic inline per page;
// this is the one reusable implementation for the new Super Admin Reports
// module rather than a fourth copy.

import * as XLSX from "xlsx";
import pdfMake from "pdfmake/build/pdfmake";
import pdfFonts from "pdfmake/build/vfs_fonts";

pdfMake.vfs = pdfFonts.pdfMake ? pdfFonts.pdfMake.vfs : pdfFonts.vfs;

function cellValue(row, col) {
  const raw = typeof col.accessor === "function" ? col.accessor(row) : row[col.key];
  return raw === null || raw === undefined ? "" : raw;
}

/**
 * columns: [{ key, label, accessor? }]
 * rows: array of plain objects
 */
export function exportToCsv(columns, rows, filename = "export.csv") {
  const header = columns.map((c) => c.label);
  const lines = [header, ...rows.map((row) => columns.map((c) => cellValue(row, c)))];
  const csv = lines
    .map((line) => line.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
    .join("\r\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function exportToExcel(columns, rows, filename = "export.xlsx", sheetName = "Report") {
  const data = rows.map((row) => {
    const record = {};
    columns.forEach((c) => { record[c.label] = cellValue(row, c); });
    return record;
  });
  const worksheet = XLSX.utils.json_to_sheet(data);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, sheetName);
  XLSX.writeFile(workbook, filename);
}

export function exportToPdf(title, columns, rows, filename = "export.pdf") {
  const body = [
    columns.map((c) => ({ text: c.label, style: "tableHeader" })),
    ...rows.map((row) => columns.map((c) => String(cellValue(row, c)))),
  ];
  const docDefinition = {
    pageOrientation: columns.length > 5 ? "landscape" : "portrait",
    content: [
      { text: title, style: "title" },
      { text: `Generated ${new Date().toLocaleString()}`, style: "subtitle" },
      {
        table: { headerRows: 1, widths: columns.map(() => "*"), body },
        layout: "lightHorizontalLines",
        margin: [0, 12, 0, 0],
      },
    ],
    styles: {
      title: { fontSize: 16, bold: true },
      subtitle: { fontSize: 9, color: "#666", margin: [0, 2, 0, 0] },
      tableHeader: { bold: true, fontSize: 9, color: "#444" },
    },
    defaultStyle: { fontSize: 8 },
  };
  pdfMake.createPdf(docDefinition).download(filename);
}
