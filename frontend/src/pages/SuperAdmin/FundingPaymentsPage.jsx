import { useState, useEffect, useCallback } from "react";
import { Wallet, Building2, RefreshCcw, TrendingUp, Clock, CheckCircle2, Coins, Info } from "lucide-react";
import Modal from "../../components/Modal";
import DateRangeFilter from "../../components/DateRangeFilter";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { Link } from "react-router-dom";
import { LoadError, LoadingBlocks } from "../../components/LoadState";
import { resolveDateRange } from "../../utils/dateRangePresets";
import { formatCurrency, getCurrencyForCountry, getCurrencySelectOptions } from "../../utils/currency";
import {
  getFinanceOverview, getFinanceSummary, getFinanceByOrganization, getComplianceJurisdictions,
  getOrganizationCurrencies, updateOrganizationCurrency,
  isSuppressed, SUPPRESSED, SUPPRESSED_EXPLANATION, aggregateRefusalMessage,
} from "../../service/superAdminService";

const RUN_STATUSES = ["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"];

// The org's explicit currency override always wins; otherwise it's derived
// from the jurisdiction country exactly as before — see Organization.currency
// in the backend model for why this is nullable/optional rather than required.
function resolveCurrencyCode(explicitCurrency, countryCode) {
  if (explicitCurrency) return explicitCurrency;
  return getCurrencyForCountry(countryCode)?.code || null;
}

// Muted chip for a k-suppressed cell (ZP-PRIV B.2).
function SuppressedChip() {
  return (
    <span
      title={SUPPRESSED_EXPLANATION}
      aria-label={SUPPRESSED_EXPLANATION}
      className="inline-flex cursor-help items-center whitespace-nowrap rounded-full border border-border bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-foreground-muted dark:bg-white/5"
    >
      {SUPPRESSED}
    </span>
  );
}

// Mexico: the shared employer total excludes Mexico's employer cost (IMSS,
// INFONAVIT and state ISN live in each Mexican payslip's frozen result), so
// show "—" rather than an understated figure.
function EmployerCost({ amount, countryCode, explicitCurrency }) {
  if ((countryCode || "").toUpperCase() === "MX") {
    return (
      <span title="Mexican employer cost (IMSS, INFONAVIT, state ISN) is not part of this shared total">—</span>
    );
  }
  return <Money amount={amount} countryCode={countryCode} explicitCurrency={explicitCurrency} />;
}

// Money cell: the hidden token renders as the chip, never as a number.
function Money({ amount, countryCode, explicitCurrency }) {
  if (isSuppressed(amount)) return <SuppressedChip />;
  if (amount === null || amount === undefined) return <span className="text-foreground-disabled">—</span>;
  const currency = resolveCurrencyCode(explicitCurrency, countryCode);
  if (!currency) return <>{`${Number(amount || 0).toLocaleString()} (currency unknown)`}</>;
  return <>{formatCurrency(amount, currency)}</>;
}

function Count({ value }) {
  if (isSuppressed(value)) return <SuppressedChip />;
  return <>{value ?? "—"}</>;
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

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

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
        Set an explicit currency for an organization when it differs from its jurisdiction&apos;s default. Leave as
        &quot;Auto (from jurisdiction)&quot; to keep using the derived currency.
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

// Same section-label scale established across the Command Center: uppercase,
// muted, small — distinct from a page title and from a data value.
const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";

export default function FundingPaymentsPage() {
  const [summary, setSummary] = useState(null);
  const [byOrganization, setByOrganization] = useState({ organizations: [], total: 0 });
  const [overview, setOverview] = useState({ items: [], total: 0 });
  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [country, setCountry] = useState("");
  const [status, setStatus] = useState("");
  const [dateRange, setDateRange] = useState({ preset: "thisMonth", ...resolveDateRange("thisMonth") });
  const [page, setPage] = useState(0);
  const [showCurrencyManager, setShowCurrencyManager] = useState(false);
  const pageSize = 20;

  useEffect(() => {
    getComplianceJurisdictions().then(setJurisdictions).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNotice("");
    // /finance/summary takes no status filter; the other two do.
    const range = {
      country: country || undefined,
      start_date: dateRange.startDate || undefined,
      end_date: dateRange.endDate || undefined,
    };
    const withStatus = { ...range, status: status || undefined };
    try {
      const [summaryRes, byOrgRes, overviewRes] = await Promise.all([
        getFinanceSummary(range),
        getFinanceByOrganization(withStatus),
        getFinanceOverview({ ...withStatus, skip: page * pageSize, limit: pageSize }),
      ]);
      setSummary(summaryRes);
      setByOrganization(byOrgRes);
      setOverview(overviewRes);
      setLoaded(true);
    } catch (err) {
      const friendly = aggregateRefusalMessage(err);
      if (friendly) setNotice(friendly);
      else setError(err?.message || "Funding totals could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [country, status, dateRange, page]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  // Any filter change goes back to the first page of cells.
  const onFilter = (setter) => (value) => { setter(value); setPage(0); };
  const changeCountry = onFilter(setCountry);
  const changeStatus = onFilter(setStatus);
  const changeDateRange = onFilter(setDateRange);

  const byCountry = summary?.byCountry || [];
  const filtered = Boolean(country || status || dateRange.preset !== "thisMonth");
  const clearFilters = () => {
    setCountry("");
    setStatus("");
    setPage(0);
    setDateRange({ preset: "thisMonth", ...resolveDateRange("thisMonth") });
  };
  const hasUnassigned = byCountry.some((r) => !r.country || r.country === "Unassigned");
  const activeOrgCount = byOrganization.organizations.filter((o) => o.payrollActive).length;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Wallet size={22} className="text-primary" /> Funding &amp; Payments
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Customer payroll money movement as platform totals — not Zoiko revenue
            (that lives in Zoiko Commercial → Revenue &amp; Collections, and the two are never merged).
            Does not replace an org&apos;s own Payroll module.
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

      <div className="mb-5 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
        <Info size={16} className="mt-0.5 shrink-0" />
        <span>
          Totals always span several organizations — no single organization&apos;s payroll or person&apos;s pay is shown.
          Money appears only for cells with at least 5 workers and 2 organizations; smaller cells show <SuppressedChip />.
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-5">
        <select value={country} onChange={(e) => changeCountry(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Jurisdictions</option>
          {jurisdictions.map((j) => <option key={j.code} value={j.code}>{j.name}</option>)}
        </select>
        <select
          value={status}
          onChange={(e) => changeStatus(e.target.value)}
          title="Applies to the monthly totals and the organization activity column"
          className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground"
        >
          <option value="">All Statuses</option>
          {RUN_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <DateRangeFilter value={dateRange} onChange={changeDateRange} />
        {filtered && (
          <button onClick={clearFilters} className="rounded-lg px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5">
            Clear filters
          </button>
        )}
      </div>

      {notice && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-light px-4 py-3 text-sm text-warning">
          <Clock size={16} className="mt-0.5 shrink-0" /> {notice}
        </p>
      )}
      <LoadError message={error} onRetry={load} />
      {!loaded && !error && !notice && <LoadingBlocks count={4} cols="sm:grid-cols-4" />}

      {loaded && <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-2">
        <SummaryCard icon={Building2} label="Organizations (with runs)" value={summary?.totalOrganizations ?? "—"} />
        <SummaryCard icon={TrendingUp} label="Payroll Runs" value={summary?.totalPayrollRuns ?? "—"} />
        <SummaryCard icon={Clock} label="Pending" value={summary?.payrollsPending ?? "—"} accent="text-warning" />
        <SummaryCard icon={CheckCircle2} label="Completed" value={summary?.payrollsCompleted ?? "—"} accent="text-success" />
      </div>
      <p className="mb-6 text-xs text-foreground-muted">
        These four counts follow the jurisdiction and date range; the status filter applies to the tables below.
      </p>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-3`}>Totals by Jurisdiction (currency-safe — never combined)</h2>
        {hasUnassigned && (
          <p className="mb-3 text-xs text-foreground-muted">
            &quot;Unassigned&quot; totals come from organizations with no compliance jurisdiction, so no currency can be derived.
            Set one in <Link to="/super-admin/organizations" className="text-primary underline">Organizations</Link> or
            choose a currency with Manage Currencies.
          </p>
        )}
        {byCountry.length === 0 ? (
          <p className="text-sm text-foreground-disabled">No payroll data for the selected filters.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {byCountry.map((row) => {
              const code = resolveCurrencyCode(row.currency, row.country);
              const countryCurrency = getCurrencyForCountry(row.country);
              const symbol = countryCurrency && countryCurrency.code === code ? `${countryCurrency.symbol} ` : "";
              const money = (key) => <Money amount={row[key]} countryCode={row.country} explicitCurrency={row.currency} />;
              return (
                // A distinct, self-contained section per jurisdiction/currency
                // — never a shared table with currency as just another column.
                <div key={`${row.country}-${row.currency || ""}`} className="bg-surface border border-border border-l-4 border-l-primary rounded-xl shadow-sm p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                    <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      {row.country}
                      {code && (
                        <span className="rounded-full bg-primary-light dark:bg-primary-active/30 px-2 py-0.5 text-[11px] font-semibold text-primary-hover">
                          {symbol}{code}
                        </span>
                      )}
                    </span>
                    <span className="flex flex-wrap items-center gap-1 text-xs text-foreground-disabled">
                      {row.organizations} org(s) · {row.payrollRuns} run(s) · <Count value={row.employeeCount} /> worker(s)
                    </span>
                  </div>
                  <div className="mb-3 grid grid-cols-2 gap-3">
                    <div>
                      <p className="text-xs text-foreground-muted">Gross Pay</p>
                      <p className="text-xl font-bold text-foreground">{money("grossPay")}</p>
                    </div>
                    <div>
                      <p className="text-xs text-foreground-muted">Net Pay</p>
                      <p className="text-xl font-bold text-foreground">{money("netPay")}</p>
                    </div>
                  </div>
                  <dl className="space-y-1.5 border-t border-border-light pt-2.5 text-sm">
                    <div className="flex justify-between gap-2"><dt className="text-foreground-muted">Deductions</dt><dd className="text-foreground-secondary">{money("totalDeductions")}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-foreground-muted">Taxes</dt><dd className="text-foreground-secondary">{money("totalTaxes")}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-foreground-muted">Employer Cost</dt><dd className="text-foreground-secondary"><EmployerCost amount={row.employerCost} countryCode={row.country} explicitCurrency={row.currency} /></dd></div>
                  </dl>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-1`}>
          Payroll totals by month ({overview.total} cell{overview.total === 1 ? "" : "s"})
        </h2>
        <p className="mb-3 text-xs text-foreground-muted">
          One row per jurisdiction × currency × month × run status, summed across organizations.
        </p>
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[1000px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Jurisdiction</th>
                <th className="px-4 py-3">Currency</th>
                <th className="px-4 py-3">Period</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Runs</th>
                <th className="px-4 py-3 text-right">Orgs</th>
                <th className="px-4 py-3 text-right">Workers</th>
                <th className="px-4 py-3 text-right">Gross Pay</th>
                <th className="px-4 py-3 text-right">Net Pay</th>
                <th className="px-4 py-3 text-right">Deductions</th>
                <th className="px-4 py-3 text-right">Taxes</th>
                <th className="px-4 py-3 text-right">Employer Cost</th>
              </tr>
            </thead>
            <tbody>
              {overview.items.map((row) => {
                const resolvedCurrency = resolveCurrencyCode(row.currency, row.jurisdictionCountry);
                const money = (key) => <Money amount={row[key]} countryCode={row.jurisdictionCountry} explicitCurrency={row.currency} />;
                return (
                  <tr key={`${row.jurisdictionCountry}-${row.currency || ""}-${row.period}-${row.status}`} className="border-t border-border-light">
                    <td className="px-4 py-3 font-medium text-foreground">{row.jurisdictionCountry || "—"}</td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-slate-100 dark:bg-white/10 px-2 py-0.5 text-xs font-semibold text-foreground-secondary">
                        {resolvedCurrency || "—"}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-foreground-secondary">{row.period}</td>
                    <td className="px-4 py-3"><StatusPill status={STATUS_PILL_MAP[row.status] || "pending"} label={row.status} /></td>
                    <td className="px-4 py-3 text-right text-foreground-secondary">{row.runCount}</td>
                    <td className="px-4 py-3 text-right text-foreground-secondary">{row.organizationCount}</td>
                    <td className="px-4 py-3 text-right text-foreground-secondary"><Count value={row.employeeCount} /></td>
                    <td className="px-4 py-3 text-right font-medium text-foreground">{money("grossPay")}</td>
                    <td className="px-4 py-3 text-right font-medium text-foreground">{money("netPay")}</td>
                    <td className="px-4 py-3 text-right text-foreground-muted">{money("totalDeductions")}</td>
                    <td className="px-4 py-3 text-right text-foreground-muted">{money("totalTaxes")}</td>
                    <td className="px-4 py-3 text-right text-foreground-muted"><EmployerCost amount={row.employerCost} countryCode={row.jurisdictionCountry} explicitCurrency={row.currency} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!loading && overview.items.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
              <Wallet size={28} className="text-border-strong" />
              <p className="text-sm text-foreground-disabled">No payroll activity matches these filters.</p>
            </div>
          )}
        </div>

        {overview.total > pageSize && (
          <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-sm text-foreground-muted">
            <span>Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, overview.total)} of {overview.total}</span>
            <div className="flex gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button>
              <button disabled={(page + 1) * pageSize >= overview.total} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-1`}>
          Organizations — {byOrganization.total} total, {activeOrgCount} with payroll in this window
        </h2>
        <p className="mb-3 text-xs text-foreground-muted">
          Registry and payroll activity only. An organization&apos;s own payroll totals stay inside that organization.
        </p>
        <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">Jurisdiction</th>
                <th className="px-4 py-3">Currency</th>
                <th className="px-4 py-3 text-right">Headcount</th>
                <th className="px-4 py-3">Payroll in window</th>
              </tr>
            </thead>
            <tbody>
              {byOrganization.organizations.map((org) => {
                const resolvedCurrency = resolveCurrencyCode(org.currency, org.jurisdictionCountry);
                return (
                  <tr key={org.organizationId} className="border-t border-border-light">
                    <td className="px-4 py-3 font-medium text-foreground">{org.organizationName}</td>
                    <td className="px-4 py-3 font-mono text-xs text-foreground-muted">{org.organizationCode || "—"}</td>
                    <td className="px-4 py-3 text-foreground-muted">{org.jurisdictionCountry || "—"}</td>
                    <td className="px-4 py-3 text-foreground-secondary">
                      {resolvedCurrency || "—"}
                      {org.currency && <span className="ml-1 text-[10px] text-primary" title="Explicit override">override</span>}
                    </td>
                    <td className="px-4 py-3 text-right text-foreground-secondary"><Count value={org.headcount} /></td>
                    <td className="px-4 py-3">
                      <StatusPill status={org.payrollActive ? "active" : "inactive"} label={org.payrollActive ? "Active" : "None"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {byOrganization.organizations.length === 0 && !loading && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-foreground-disabled">No organizations found.</p>
            </div>
          )}
        </div>
      </div>

      </>}

      {showCurrencyManager && (
        <CurrencyManagerModal onClose={() => { setShowCurrencyManager(false); load(); }} />
      )}
    </div>
  );
}
