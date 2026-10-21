import { useState, useEffect, useCallback } from "react";
import {
  FileBarChart, Building2, Users, Wallet, ShieldCheck, Download, FileSpreadsheet, FileText, RefreshCcw, Info, Clock,
} from "lucide-react";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";
import DateRangeFilter from "../components/DateRangeFilter";
import WorkerDataLocked from "../components/WorkerDataLocked";
import { resolveDateRange } from "../utils/dateRangePresets";
import { exportToExcel, exportToPdf } from "../utils/exportTable";
import { formatCurrency, getCurrencyForCountry } from "../utils/currency";
import {
  getReportsOrganizations, getReportsEmployees, getFinanceOverview, getCompliancePolicies,
  listAllOrganizationsBrief, getComplianceJurisdictions, downloadReportCsv,
  isSuppressed, SUPPRESSED, SUPPRESSED_EXPLANATION, aggregateRefusalMessage,
} from "../service/superAdminService";

// Muted chip for a k-suppressed cell — the explanation lives in the tooltip
// and in the banner above the table.
function SuppressedChip() {
  return (
    <span
      title={SUPPRESSED_EXPLANATION}
      aria-label={SUPPRESSED_EXPLANATION}
      className="inline-flex cursor-help items-center rounded-full border border-border bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-foreground-muted dark:bg-white/5"
    >
      {SUPPRESSED}
    </span>
  );
}

function currencyCodeFor(row) {
  return row.currency || getCurrencyForCountry(row.jurisdictionCountry)?.code || null;
}

// Text form (used by Excel/PDF export and as the on-screen value when not hidden).
function moneyText(amount, row) {
  if (isSuppressed(amount)) return SUPPRESSED;
  if (amount === null || amount === undefined) return "—";
  const code = currencyCodeFor(row);
  return code ? formatCurrency(amount, code) : Number(amount || 0).toLocaleString();
}

const moneyColumn = (key, label) => ({
  key, label, align: "right", accessor: (r) => moneyText(r[key], r),
});
const countColumn = (key, label) => ({ key, label, align: "right" });

const CATEGORIES = [
  {
    id: "organizations", label: "Organizations", icon: Building2, searchable: true,
    columns: [
      { key: "organizationName", label: "Organization" },
      { key: "organizationCode", label: "Code" },
      { key: "country", label: "Country" },
      { key: "jurisdictionCountry", label: "Jurisdiction" },
      countColumn("employeeCount", "Employees"),
      countColumn("payrollRunCount", "Payroll Runs"),
      { key: "isActive", label: "Active", accessor: (r) => (r.isActive ? "Yes" : "No") },
    ],
  },
  {
    // ZP-PRIV B.1/B.2: counts only — no worker names, codes or roles.
    id: "employees", label: "Workforce totals", icon: Users, aggregate: true, orgFilter: true,
    columns: [
      { key: "organizationName", label: "Organization" },
      { key: "organizationCode", label: "Code" },
      { key: "jurisdictionCountry", label: "Jurisdiction" },
      { key: "status", label: "Status" },
      { key: "employmentType", label: "Employment Type" },
      countColumn("employeeCount", "Workers"),
    ],
  },
  {
    // Aggregate cells: jurisdiction x currency x month x status.
    id: "payroll", label: "Payroll", icon: Wallet, aggregate: true, dated: true,
    columns: [
      { key: "jurisdictionCountry", label: "Jurisdiction" },
      { key: "currency", label: "Currency", accessor: (r) => currencyCodeFor(r) || "—" },
      { key: "period", label: "Period" },
      { key: "status", label: "Status" },
      countColumn("runCount", "Runs"),
      countColumn("organizationCount", "Organizations"),
      countColumn("employeeCount", "Workers"),
      moneyColumn("grossPay", "Gross Pay"),
      moneyColumn("netPay", "Net Pay"),
      moneyColumn("totalDeductions", "Deductions"),
      moneyColumn("employerCost", "Employer Cost"),
    ],
  },
  {
    id: "compliance", label: "Compliance", icon: ShieldCheck, searchable: true,
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

function cellText(row, column) {
  const value = column.accessor ? column.accessor(row) : row[column.key];
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

export default function ReportsPage() {
  const [activeCategory, setActiveCategory] = useState("organizations");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [country, setCountry] = useState("");
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

  const handleFailure = useCallback((err) => {
    const friendly = aggregateRefusalMessage(err);
    if (friendly) setNotice(friendly);
    else setError(err.message);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      if (activeCategory === "organizations") {
        const res = await getReportsOrganizations({ search: search || undefined, country: country || undefined, limit: 100 });
        setRows(res.items); setTotal(res.total);
      } else if (activeCategory === "employees") {
        const res = await getReportsEmployees({ organization_id: organizationId || undefined, country: country || undefined, limit: 100 });
        setRows(res.items); setTotal(res.total);
      } else if (activeCategory === "payroll") {
        const res = await getFinanceOverview({
          country: country || undefined,
          start_date: dateRange.startDate || undefined, end_date: dateRange.endDate || undefined, limit: 100,
        });
        setRows(res.items); setTotal(res.total);
      } else {
        const res = await getCompliancePolicies({ country: country || undefined, search: search || undefined });
        setRows(res); setTotal(res.length);
      }
    } catch (err) {
      handleFailure(err);
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [activeCategory, search, organizationId, country, dateRange, handleFailure]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  function exportParams() {
    return {
      organization_id: category.orgFilter ? organizationId || undefined : undefined,
      country: country || undefined,
      search: category.searchable ? search || undefined : undefined,
      start_date: category.dated ? dateRange.startDate || undefined : undefined,
      end_date: category.dated ? dateRange.endDate || undefined : undefined,
    };
  }

  function handleExportExcel() {
    exportToExcel(category.columns, rows, `${category.id}-report.xlsx`, category.label);
  }
  function handleExportPdf() {
    exportToPdf(`${category.label} Report`, category.columns, rows, `${category.id}-report.pdf`);
  }
  async function handleExportCsv() {
    setError("");
    setNotice("");
    try {
      await downloadReportCsv(activeCategory, exportParams());
    } catch (err) {
      handleFailure(err);
    }
  }

  function renderCell(row, column) {
    const raw = row[column.key];
    if (isSuppressed(raw)) return <SuppressedChip />;
    if (column.key === "status") {
      return row.status ? <StatusPill status={String(row.status).toLowerCase()} label={row.status} /> : "—";
    }
    return cellText(row, column);
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FileBarChart size={22} className="text-primary" /> Reports
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Cross-organization reporting across organizations, workforce totals, payroll aggregates, and compliance.
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

      <div className="mb-5 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
        <Info size={16} className="mt-0.5 shrink-0" />
        <span>
          Reports show platform totals only, never individual workers. Cells marked <SuppressedChip /> cover fewer than
          5 workers (money: or fewer than 2 organizations) and are hidden to protect individuals.
        </span>
      </div>

      <div className="flex flex-wrap gap-2 mb-5">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => { setActiveCategory(c.id); setSearch(""); }}
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
        {category.searchable && (
          <SearchInput value={search} onChange={setSearch} placeholder="Search…" className="w-56" />
        )}
        {category.orgFilter && (
          <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
            <option value="">All Organizations</option>
            {organizations.map((o) => <option key={o.id} value={o.id}>{o.organization_name}</option>)}
          </select>
        )}
        <select value={country} onChange={(e) => setCountry(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Jurisdictions</option>
          {jurisdictions.map((j) => <option key={j.code} value={j.code}>{j.name}</option>)}
        </select>
        {category.dated && <DateRangeFilter value={dateRange} onChange={setDateRange} />}

        <div className="ml-auto flex items-center gap-1.5">
          <button onClick={handleExportCsv} title="Export CSV" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5">
            <Download size={14} /> CSV
          </button>
          <button onClick={handleExportExcel} disabled={rows.length === 0} title="Export Excel" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50">
            <FileSpreadsheet size={14} /> Excel
          </button>
          <button onClick={handleExportPdf} disabled={rows.length === 0} title="Export PDF" className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50">
            <FileText size={14} /> PDF
          </button>
        </div>
      </div>

      {notice && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-light px-4 py-3 text-sm text-warning">
          <Clock size={16} className="mt-0.5 shrink-0" /> {notice}
        </p>
      )}
      {error && (
        <p className="mb-4 rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">{error}</p>
      )}

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              {category.columns.map((c) => (
                <th key={c.key} className={`px-4 py-3 ${c.align === "right" ? "text-right" : ""}`}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.id ?? i} className="border-t border-border-light">
                {category.columns.map((c) => (
                  <td key={c.key} className={`px-4 py-3 text-foreground-secondary ${c.align === "right" ? "text-right" : ""}`}>
                    {renderCell(row, c)}
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

      {activeCategory === "employees" && (
        <div className="mt-6">
          <WorkerDataLocked variant="support" title="Looking for individual workers?">
            <p className="leading-relaxed">
              Workforce totals replace the old employee listing. Names, employee codes, departments and roles are
              never shown here.
            </p>
          </WorkerDataLocked>
        </div>
      )}
    </div>
  );
}
