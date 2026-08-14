import { useState, useEffect, useCallback } from "react";
import { Wallet, Building2, RefreshCcw, TrendingUp, Clock, CheckCircle2, Coins } from "lucide-react";
import Modal from "../components/Modal";
import DateRangeFilter from "../components/DateRangeFilter";
import StatusPill from "../components/StatusPill";
import { useToast } from "../context/ToastContext";
import { resolveDateRange } from "../utils/dateRangePresets";
import { formatCurrency, getCurrencyForCountry, getCurrencySelectOptions } from "../utils/currency";
import {
  getFinanceOverview, getFinanceSummary, listAllOrganizationsBrief, getComplianceJurisdictions,
  getOrganizationCurrencies, updateOrganizationCurrency,
} from "../service/superAdminService";

const RUN_STATUSES = ["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"];

// The org's explicit currency override always wins; otherwise it's derived
// from the jurisdiction country exactly as before — see Organization.currency
// in the backend model for why this is nullable/optional rather than required.
function resolveCurrencyCode(explicitCurrency, countryCode) {
  if (explicitCurrency) return explicitCurrency;
  return getCurrencyForCountry(countryCode)?.code || null;
}

function money(amount, countryCode, explicitCurrency) {
  const currency = resolveCurrencyCode(explicitCurrency, countryCode);
  if (!currency) return `${Number(amount || 0).toLocaleString()} (currency unknown)`;
  return formatCurrency(amount, currency);
}

function CurrencyManagerModal({ onClose }) {
  const { addToast } = useToast() || {};
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);
  const currencyOptions = getCurrencySelectOptions();

  const load = () => {
    setLoading(true);
    getOrganizationCurrencies()
      .then(setOrgs)
      .catch((err) => addToast?.(err.message, "error"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleChange(org, currency) {
    setSavingId(org.id);
    try {
      await updateOrganizationCurrency(org.id, currency || null);
      setOrgs((prev) => prev.map((o) => (o.id === org.id ? { ...o, currency: currency || null } : o)));
      addToast?.(`Currency updated for ${org.organizationName}.`, "success");
    } catch (err) {
      addToast?.(err.message || "Failed to update currency.", "error");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <Modal title="Manage Organization Currencies" onClose={onClose} maxWidth="max-w-2xl">
      <p className="text-sm text-foreground-muted mb-4">
        Set an explicit currency for an organization when it differs from its jurisdiction's default. Leave as
        "Auto (from jurisdiction)" to keep using the derived currency.
      </p>
      {loading ? (
        <p className="py-8 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : (
        <div className="max-h-96 overflow-y-auto rounded-lg border border-border">
          {orgs.map((org) => {
            const derived = getCurrencyForCountry(org.jurisdictionCountry);
            return (
              <div key={org.id} className="flex items-center justify-between gap-3 border-b border-border-light px-3.5 py-3 last:border-b-0">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">{org.organizationName}</p>
                  <p className="truncate text-xs text-foreground-disabled">
                    {org.jurisdictionCountry || "No jurisdiction set"}
                    {derived ? ` · default ${derived.code}` : ""}
                  </p>
                </div>
                <select
                  value={org.currency || ""}
                  disabled={savingId === org.id}
                  onChange={(e) => handleChange(org, e.target.value)}
                  className="w-56 shrink-0 rounded-lg border border-border bg-background py-1.5 px-2.5 text-sm text-foreground disabled:opacity-50"
                >
                  <option value="">Auto (from jurisdiction)</option>
                  {currencyOptions.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
            );
          })}
          {orgs.length === 0 && (
            <p className="py-8 text-center text-sm text-foreground-disabled">No organizations found.</p>
          )}
        </div>
      )}
    </Modal>
  );
}

function SummaryCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xl font-bold text-foreground">{value}</div>
          <div className="text-xs text-foreground-muted mt-1">{label}</div>
        </div>
        <Icon size={20} className={accent || "text-primary"} />
      </div>
    </div>
  );
}

const STATUS_PILL_MAP = { Paid: "active", Closed: "active", Approved: "approved", Authorized: "approved", Review: "pending", Draft: "inactive" };

export default function FinancePage() {
  const [summary, setSummary] = useState(null);
  const [overview, setOverview] = useState({ items: [], total: 0 });
  const [organizations, setOrganizations] = useState([]);
  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [organizationId, setOrganizationId] = useState("");
  const [country, setCountry] = useState("");
  const [status, setStatus] = useState("");
  const [dateRange, setDateRange] = useState({ preset: "thisMonth", ...resolveDateRange("thisMonth") });
  const [page, setPage] = useState(0);
  const [showCurrencyManager, setShowCurrencyManager] = useState(false);
  const pageSize = 20;

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
    const params = {
      organization_id: organizationId || undefined,
      country: country || undefined,
      status: status || undefined,
      start_date: dateRange.startDate || undefined,
      end_date: dateRange.endDate || undefined,
    };
    try {
      const [summaryRes, overviewRes] = await Promise.all([
        getFinanceSummary(params),
        getFinanceOverview({ ...params, skip: page * pageSize, limit: pageSize }),
      ]);
      setSummary(summaryRes);
      setOverview(overviewRes);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [organizationId, country, status, dateRange, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); }, [organizationId, country, status, dateRange]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Wallet size={22} className="text-primary" /> Finance
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Cross-organization payroll financial overview. Does not replace an org's own Payroll module.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCurrencyManager(true)}
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5"
          >
            <Coins size={15} /> Manage Currencies
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <SummaryCard icon={Building2} label="Organizations (with runs)" value={summary?.totalOrganizations ?? "—"} />
        <SummaryCard icon={TrendingUp} label="Payroll Runs" value={summary?.totalPayrollRuns ?? "—"} />
        <SummaryCard icon={Clock} label="Pending" value={summary?.payrollsPending ?? "—"} accent="text-amber-500" />
        <SummaryCard icon={CheckCircle2} label="Completed" value={summary?.payrollsCompleted ?? "—"} accent="text-green-500" />
      </div>

      <div className="mb-6">
        <h2 className="text-sm font-semibold text-foreground-secondary mb-3">Totals by Jurisdiction (currency-safe — never combined)</h2>
        {!summary || summary.byCountry.length === 0 ? (
          <p className="text-sm text-foreground-disabled">No payroll data for the selected filters.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {summary.byCountry.map((row) => {
              const currencyInfo = getCurrencyForCountry(row.country);
              return (
              <div key={row.country} className="bg-surface border border-border rounded-xl shadow-sm p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    {row.country}
                    {currencyInfo && (
                      <span className="rounded-full bg-primary-light dark:bg-primary-active/30 px-2 py-0.5 text-[11px] font-semibold text-primary-hover">
                        {currencyInfo.symbol} {currencyInfo.code}
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-foreground-disabled">{row.organizations} org(s) · {row.payrollRuns} run(s)</span>
                </div>
                <dl className="space-y-1.5 text-sm">
                  <div className="flex justify-between"><dt className="text-foreground-muted">Gross Pay</dt><dd className="font-medium text-foreground">{money(row.grossPay, row.country)}</dd></div>
                  <div className="flex justify-between"><dt className="text-foreground-muted">Net Pay</dt><dd className="font-medium text-foreground">{money(row.netPay, row.country)}</dd></div>
                  <div className="flex justify-between"><dt className="text-foreground-muted">Deductions</dt><dd className="text-foreground-secondary">{money(row.totalDeductions, row.country)}</dd></div>
                  <div className="flex justify-between"><dt className="text-foreground-muted">Employer Cost</dt><dd className="text-foreground-secondary">{money(row.employerCost, row.country)}</dd></div>
                </dl>
              </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Organizations</option>
          {organizations.map((o) => <option key={o.id} value={o.id}>{o.organization_name}</option>)}
        </select>
        <select value={country} onChange={(e) => setCountry(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Jurisdictions</option>
          {jurisdictions.map((j) => <option key={j.code} value={j.code}>{j.name}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Statuses</option>
          {RUN_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <DateRangeFilter value={dateRange} onChange={setDateRange} />
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Jurisdiction</th>
              <th className="px-4 py-3">Currency</th>
              <th className="px-4 py-3">Period</th>
              <th className="px-4 py-3">Pay Date</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Gross Pay</th>
              <th className="px-4 py-3 text-right">Net Pay</th>
              <th className="px-4 py-3 text-right">Employer Cost</th>
            </tr>
          </thead>
          <tbody>
            {overview.items.map((row) => {
              const resolvedCurrency = resolveCurrencyCode(row.currency, row.jurisdictionCountry);
              return (
              <tr key={row.id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">{row.organizationName}</td>
                <td className="px-4 py-3 text-foreground-muted">{row.jurisdictionCountry || "—"}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full bg-slate-100 dark:bg-white/10 px-2 py-0.5 text-xs font-semibold text-foreground-secondary">
                    {resolvedCurrency || "—"}
                  </span>
                  {row.currency && <span className="ml-1 text-[10px] text-primary" title="Explicit override">override</span>}
                </td>
                <td className="px-4 py-3 text-foreground-secondary">{row.periodLabel}</td>
                <td className="px-4 py-3 text-foreground-muted">{row.payDate}</td>
                <td className="px-4 py-3"><StatusPill status={STATUS_PILL_MAP[row.status] || "pending"} label={row.status} /></td>
                <td className="px-4 py-3 text-right font-medium text-foreground">{money(row.grossPay, row.jurisdictionCountry, row.currency)}</td>
                <td className="px-4 py-3 text-right font-medium text-foreground">{money(row.netPay, row.jurisdictionCountry, row.currency)}</td>
                <td className="px-4 py-3 text-right text-foreground-muted">{money(row.employerCost, row.jurisdictionCountry, row.currency)}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
        {!loading && overview.items.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Wallet size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No payroll runs match these filters.</p>
          </div>
        )}
      </div>

      {overview.total > pageSize && (
        <div className="flex items-center justify-between mt-3 text-sm text-foreground-muted">
          <span>Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, overview.total)} of {overview.total}</span>
          <div className="flex gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button>
            <button disabled={(page + 1) * pageSize >= overview.total} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}

      {showCurrencyManager && <CurrencyManagerModal onClose={() => setShowCurrencyManager(false)} />}
    </div>
  );
}
