import { useState, useEffect, useCallback } from "react";
import {
  FileBarChart, Building2, Users, Wallet, ShieldCheck, Download, FileSpreadsheet, FileText, RefreshCcw,
} from "lucide-react";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";
import DateRangeFilter from "../components/DateRangeFilter";
import { resolveDateRange } from "../utils/dateRangePresets";
import { exportToCsv, exportToExcel, exportToPdf } from "../utils/exportTable";
import { formatCurrency, getCurrencyForCountry } from "../utils/currency";
import {
  getReportsOrganizations, getReportsEmployees, getFinanceOverview, getCompliancePolicies,
  listAllOrganizationsBrief, getComplianceJurisdictions, downloadReportCsv,
} from "../service/superAdminService";

const CATEGORIES = [
  {
    id: "organizations", label: "Organizations", icon: Building2,
    columns: [
      { key: "organizationName", label: "Organization" },
      { key: "organizationCode", label: "Code" },
      { key: "country", label: "Country" },
      { key: "jurisdictionCountry", label: "Jurisdiction" },
      { key: "employeeCount", label: "Employees" },
      { key: "payrollRunCount", label: "Payroll Runs" },
      { key: "isActive", label: "Active", accessor: (r) => (r.isActive ? "Yes" : "No") },
    ],
  },
  {
    id: "employees", label: "Employees", icon: Users,
    columns: [
      { key: "employeeCode", label: "Employee Code" },
      { key: "name", label: "Name" },
      { key: "organizationName", label: "Organization" },
      { key: "jurisdictionCountry", label: "Jurisdiction" },
      { key: "department", label: "Department" },
      { key: "designation", label: "Designation" },
      { key: "status", label: "Status" },
    ],
  },
  {
    id: "payroll", label: "Payroll", icon: Wallet,
    columns: [
      { key: "organizationName", label: "Organization" },
      { key: "jurisdictionCountry", label: "Jurisdiction" },
      { key: "periodLabel", label: "Period" },
      { key: "payDate", label: "Pay Date" },
      { key: "status", label: "Status" },
      { key: "grossPay", label: "Gross Pay", accessor: (r) => moneyFor(r.grossPay, r.jurisdictionCountry) },
      { key: "netPay", label: "Net Pay", accessor: (r) => moneyFor(r.netPay, r.jurisdictionCountry) },
    ],
  },
  {
    id: "compliance", label: "Compliance", icon: ShieldCheck,
    columns: [
      { key: "packId", label: "Policy" },
      { key: "jurisdictionCountry", label: "Country" },
      { key: "jurisdictionState", label: "State" },
      { key: "version", label: "Version" },
      { key: "status", label: "Status" },
      { key: "complianceCategory", label: "Category" },
      { key: "effectiveFrom", label: "Effective From" },
      { key: "effectiveTo", label: "Effective To" },
    ],
  },
];

function moneyFor(amount, country) {
  const info = getCurrencyForCountry(country);
  return info ? formatCurrency(amount, info.code) : Number(amount || 0).toLocaleString();
}

export default function ReportsPage() {
  const [activeCategory, setActiveCategory] = useState("organizations");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [country, setCountry] = useState("");
  const [status, setStatus] = useState("");
  const [dateRange, setDateRange] = useState({ preset: "thisMonth", ...resolveDateRange("thisMonth") });
  const [organizations, setOrganizations] = useState([]);
  const [jurisdictions, setJurisdictions] = useState([]);

  const category = CATEGORIES.find((c) => c.id === activeCategory);

  useEffect(() => {
    Promise.all([listAllOrganizationsBrief(), getComplianceJurisdictions()])
      .then(([orgRes, jRes]) => {
        setOrganizations(orgRes.organizations || []);
        setJurisdictions(jRes);
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (activeCategory === "organizations") {
        const res = await getReportsOrganizations({ search: search || undefined, country: country || undefined, status: status || undefined, limit: 100 });
        setRows(res.items); setTotal(res.total);
      } else if (activeCategory === "employees") {
        const res = await getReportsEmployees({ organization_id: organizationId || undefined, country: country || undefined, status: status || undefined, search: search || undefined, limit: 100 });
        setRows(res.items); setTotal(res.total);
      } else if (activeCategory === "payroll") {
        const res = await getFinanceOverview({
          organization_id: organizationId || undefined, country: country || undefined, status: status || undefined,
          start_date: dateRange.startDate || undefined, end_date: dateRange.endDate || undefined, limit: 100,
        });
        setRows(res.items); setTotal(res.total);
      } else {
        const res = await getCompliancePolicies({ country: country || undefined, status: status || undefined, search: search || undefined });
        setRows(res); setTotal(res.length);
      }
    } catch (err) {
      setError(err.message);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [activeCategory, search, organizationId, country, status, dateRange]);

  useEffect(() => { load(); }, [load]);

  function handleExportExcel() {
    exportToExcel(category.columns, rows, `${category.id}-report.xlsx`, category.label);
  }
  function handleExportPdf() {
    exportToPdf(`${category.label} Report`, category.columns, rows, `${category.id}-report.pdf`);
  }
  async function handleExportCsv() {
    try {
      await downloadReportCsv(activeCategory, {
        organization_id: organizationId || undefined, country: country || undefined,
        status: status || undefined, search: search || undefined,
        start_date: dateRange.startDate || undefined, end_date: dateRange.endDate || undefined,
      });
    } catch {
      // Backend export failed (e.g. offline) — fall back to exporting what's already on screen.
      exportToCsv(category.columns, rows, `${category.id}-report.csv`);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FileBarChart size={22} className="text-primary" /> Reports
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Cross-organization reporting across payroll, employees, and compliance.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-5">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => { setActiveCategory(c.id); setSearch(""); setStatus(""); }}
            className={`flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${
              activeCategory === c.id
                ? "bg-primary text-white"
                : "bg-surface border border-border text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5"
            }`}
          >
            <c.icon size={15} /> {c.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <SearchInput value={search} onChange={setSearch} placeholder="Search…" className="w-56" />
        {(activeCategory === "employees" || activeCategory === "payroll") && (
          <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
            <option value="">All Organizations</option>
            {organizations.map((o) => <option key={o.id} value={o.id}>{o.organization_name}</option>)}
          </select>
        )}
        <select value={country} onChange={(e) => setCountry(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Jurisdictions</option>
          {jurisdictions.map((j) => <option key={j.code} value={j.code}>{j.name}</option>)}
        </select>
        {activeCategory === "payroll" && <DateRangeFilter value={dateRange} onChange={setDateRange} />}

        <div className="ml-auto flex items-center gap-1.5">
          <button onClick={handleExportCsv} title="Export CSV" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5">
            <Download size={14} /> CSV
          </button>
          <button onClick={handleExportExcel} title="Export Excel" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5">
            <FileSpreadsheet size={14} /> Excel
          </button>
          <button onClick={handleExportPdf} title="Export PDF" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5">
            <FileText size={14} /> PDF
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              {category.columns.map((c) => <th key={c.key} className="px-4 py-3">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.id ?? i} className="border-t border-border-light">
                {category.columns.map((c) => (
                  <td key={c.key} className="px-4 py-3 text-foreground-secondary">
                    {c.key === "status" ? (
                      <StatusPill status={String(row.status || "").toLowerCase()} label={row.status} />
                    ) : (
                      String((c.accessor ? c.accessor(row) : row[c.key]) ?? "—")
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <category.icon size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No {category.label.toLowerCase()} match these filters.</p>
          </div>
        )}
      </div>
      {total > rows.length && (
        <p className="mt-2 text-xs text-foreground-disabled">Showing {rows.length} of {total}. Refine filters to narrow results.</p>
      )}
    </div>
  );
}
