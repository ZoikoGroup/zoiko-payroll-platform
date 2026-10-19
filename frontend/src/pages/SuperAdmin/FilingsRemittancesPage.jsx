import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, RefreshCcw, Info, AlertTriangle, Building2 } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import WorkerDataLocked from "../../components/WorkerDataLocked";
import { LoadError, LoadingBlocks } from "../../components/LoadState";
import { listFilingsRemittances } from "../../service/commandCenterService";

// ZP-PRIV B.1 / decision 3: the platform plane sees statutory filing
// COVERAGE as counts per jurisdiction. Individual filings, periods and
// organization names stay inside each tenant, and recording / editing /
// deleting a filing is tenant-run (the Super Admin PUT/DELETE are retired).

const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted";
const TABLE_WRAP_CLS = "bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto";

const EMPTY_DATA = { jurisdictions: {}, unconfigured_count: 0, known_gaps: [], privacy_note: "" };

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export default function FilingsRemittancesPage() {
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await listFilingsRemittances();
      setData({ ...EMPTY_DATA, ...res });
      setLoaded(true);
    } catch (err) {
      setError(err?.message || "Filing coverage could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const entries = Object.entries(data.jurisdictions || {}).sort(([, a], [, b]) =>
    (b.blocked_count || 0) - (a.blocked_count || 0) || String(a.label).localeCompare(String(b.label)),
  );
  const totals = entries.reduce(
    (acc, [, s]) => ({
      filings: acc.filings + (s.total || 0),
      blocked: acc.blocked + (s.blocked_count || 0),
      blockedOrgs: acc.blockedOrgs + (s.orgs_with_blocked_filings || 0),
      orgs: acc.orgs + (s.total_orgs || 0),
    }),
    { filings: 0, blocked: 0, blockedOrgs: 0, orgs: 0 },
  );
  const unconfigured = data.unconfigured_count || 0;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <FileText size={22} className="text-primary" /> Filings &amp; Remittances
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Cross-organization statutory filing coverage, by jurisdiction — counts only, read-only.
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

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-info/30 bg-info-light px-4 py-3 text-sm text-info">
        <Info size={16} className="mt-0.5 shrink-0" />
        <span>
          {data.privacy_note || "Individual filings are tenant data and are recorded by each organization."}{" "}
          Filing records are created and updated by each organization in its own workspace; they can&apos;t be edited here.
        </span>
      </div>

      {data.known_gaps?.length > 0 && (
        <div className="mb-6 flex items-start gap-2 rounded-lg border border-border bg-surface-muted px-4 py-3 text-sm text-foreground-secondary">
          <Info size={16} className="mt-0.5 shrink-0 text-foreground-muted" />
          <ul className="list-disc pl-4 space-y-1">
            {data.known_gaps.map((gap, i) => <li key={i}>{gap}</li>)}
          </ul>
        </div>
      )}

      <LoadError message={error} onRetry={load} />
      {!loaded && !error && <LoadingBlocks count={4} cols="sm:grid-cols-4" />}
      {loaded && <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
          <div className="text-2xl font-bold text-foreground">{totals.filings}</div>
          <div className="text-xs text-foreground-muted mt-1">Filing records</div>
        </div>
        <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
          <div className={`text-2xl font-bold ${totals.blocked > 0 ? "text-error" : "text-foreground"}`}>{totals.blocked}</div>
          <div className="text-xs text-foreground-muted mt-1">Blocked / rejected</div>
        </div>
        <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
          <div className="text-2xl font-bold text-foreground">{totals.blockedOrgs}</div>
          <div className="text-xs text-foreground-muted mt-1">Orgs with a blocked filing</div>
        </div>
        <div className="bg-surface border border-border rounded-xl shadow-sm p-5">
          <div className="text-2xl font-bold text-foreground">{totals.orgs}</div>
          <div className="text-xs text-foreground-muted mt-1">Orgs with a jurisdiction</div>
        </div>
      </div>

      <div className="mb-6">
        <h2 className={`${SECTION_LABEL_CLS} mb-3`}>By Jurisdiction ({entries.length})</h2>
        <div className={TABLE_WRAP_CLS}>
          <table className="w-full text-sm min-w-[760px]">
            <thead className="bg-background text-left text-xs text-foreground-muted">
              <tr>
                <th className="px-4 py-3">Jurisdiction</th>
                <th className="px-4 py-3 text-right">Organizations</th>
                <th className="px-4 py-3 text-right">Filing records</th>
                <th className="px-4 py-3 text-right">Blocked</th>
                <th className="px-4 py-3 text-right">Orgs blocked</th>
                <th className="px-4 py-3 text-right">Orgs with no records</th>
                <th className="px-4 py-3">State</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([code, s]) => {
                const blocked = s.blocked_count || 0;
                return (
                  <tr
                    key={code}
                    className={`border-t border-border-light ${blocked > 0 ? "border-l-4 border-l-error bg-error-light/30" : ""}`}
                  >
                    <td className="px-4 py-3 font-medium text-foreground">
                      {s.label || code}
                      {s.label && s.label !== code && <span className="ml-1.5 text-xs text-foreground-muted">{code}</span>}
                    </td>
                    <td className="px-4 py-3 text-right text-foreground-secondary">{s.total_orgs ?? 0}</td>
                    <td className="px-4 py-3 text-right text-foreground-secondary">{s.total ?? 0}</td>
                    <td className={`px-4 py-3 text-right ${blocked > 0 ? "font-semibold text-error" : "text-foreground-muted"}`}>{blocked}</td>
                    <td className="px-4 py-3 text-right text-foreground-muted">{s.orgs_with_blocked_filings ?? 0}</td>
                    <td className="px-4 py-3 text-right text-foreground-muted">{s.orgs_without_filing_records ?? 0}</td>
                    <td className="px-4 py-3">
                      {blocked > 0 ? (
                        <span className="inline-flex items-center gap-1.5">
                          <AlertTriangle size={13} className="shrink-0 text-error" />
                          <StatusPill status="rejected" label={`${plural(blocked, "filing")} need attention`} />
                        </span>
                      ) : (s.total ?? 0) === 0 ? (
                        <span className="text-xs italic text-foreground-muted">No filing records yet</span>
                      ) : (
                        <StatusPill status="active" label="No blocks" />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!loading && entries.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <p className="text-sm text-foreground-disabled">No organizations have a compliance jurisdiction yet.</p>
            </div>
          )}
        </div>
      </div>

      {unconfigured > 0 && (
        <div className="mb-6 flex flex-wrap items-start gap-3 rounded-xl border border-border bg-surface p-4 shadow-sm">
          <Building2 size={18} className="mt-0.5 shrink-0 text-foreground-muted" />
          <p className="min-w-0 flex-1 text-sm text-foreground-secondary">
            {plural(unconfigured, "organization")} {unconfigured === 1 ? "has" : "have"} no compliance jurisdiction set, so no
            filing records can exist for {unconfigured === 1 ? "it" : "them"}. Assign one in{" "}
            <Link to="/super-admin/organizations" className="text-primary underline hover:text-primary/80">Organizations</Link>.
          </p>
        </div>
      )}

      </>}

      <WorkerDataLocked variant="tenant" title="Filing records are recorded by each organization">
        <p className="leading-relaxed">
          To investigate a blocked filing, contact the organization; it records and resolves its own statutory filings.
        </p>
      </WorkerDataLocked>
    </div>
  );
}
