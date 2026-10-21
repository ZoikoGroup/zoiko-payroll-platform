import { Fragment, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight, RefreshCcw, ShieldAlert, X } from "lucide-react";
import { getSecurityAuditLog } from "../../service/commandCenterService";
import { formatDateTime } from "../../utils/time";

const FALLBACK_SOURCES = [
  { key: "compliance", label: "Compliance configuration" },
  { key: "billing", label: "Billing" },
  { key: "support_access", label: "Support access" },
  { key: "assist", label: "Assist" },
  { key: "assisted_access", label: "Assisted access (retired)" },
];

const SOURCE_TONE = {
  compliance: "bg-primary/10 text-primary",
  billing: "bg-success-light text-success",
  support_access: "bg-warning-light text-warning",
  assist: "bg-slate-100 text-foreground-secondary dark:bg-white/10",
  assisted_access: "bg-surface-muted text-foreground-muted",
};

const PAGE_SIZE = 50;
const field = "rounded-lg border border-border bg-surface px-3 py-2 text-sm text-foreground";

function humanize(action) {
  return String(action || "").replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function DetailView({ detail }) {
  const entries = Object.entries(detail || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!entries.length) return <p className="text-xs text-foreground-muted">No further detail is recorded for this event.</p>;
  return (
    <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
      {entries.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-foreground-muted">{humanize(k)}</dt>
          <dd className="break-words font-mono text-foreground">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function SecurityAuditPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

  const [source, setSource] = useState(searchParams.get("source") || "");
  const [actorId, setActorId] = useState(searchParams.get("actor_id") || "");
  const [startDate, setStartDate] = useState(searchParams.get("start_date") || "");
  const [endDate, setEndDate] = useState(searchParams.get("end_date") || "");
  const [page, setPage] = useState(1);

  const setFilter = (key, value, setter) => {
    setter(value);
    setPage(1);
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value); else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  const clearFilters = () => {
    setSource(""); setActorId(""); setStartDate(""); setEndDate(""); setPage(1);
    setSearchParams(new URLSearchParams(), { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getSecurityAuditLog({
        source: source || undefined,
        actor_id: /^\d+$/.test(actorId) ? actorId : undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        page,
        page_size: PAGE_SIZE,
      }));
    } catch (err) {
      setError(err?.message || "The audit trail could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [source, actorId, startDate, endDate, page]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react-hooks/set-state-in-effect

  const sources = data?.sources?.length ? data.sources : FALLBACK_SOURCES;
  const labelOf = (key) => sources.find((s) => s.key === key)?.label || key;
  const entries = data?.entries || [];
  const total = data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = source || actorId || startDate || endDate;
  const badDates = startDate && endDate && startDate > endDate;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <ShieldAlert size={22} className="text-primary" /> Security & Audit
          </h1>
          <p className="mt-0.5 text-sm text-foreground-muted">
            Append-only audit trail across compliance configuration, billing, support access and Assist. Metadata only; no employee data.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-white/5"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {data?.totals_by_source && (
        <div className="mb-4 flex flex-wrap gap-2">
          {sources.map((s) => (
            <button
              key={s.key}
              onClick={() => setFilter("source", source === s.key ? "" : s.key, setSource)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                source === s.key ? "border-primary bg-primary/10 text-primary" : "border-border bg-surface text-foreground-secondary hover:bg-slate-50 dark:hover:bg-white/5"}`}
            >
              {s.label} <span className="text-foreground-muted">{data.totals_by_source[s.key] ?? 0}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-xs text-foreground-muted">
          <span className="block">Source</span>
          <select value={source} onChange={(e) => setFilter("source", e.target.value, setSource)} className={field}>
            <option value="">All sources</option>
            {sources.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-xs text-foreground-muted">
          <span className="block">Actor user ID</span>
          <input
            inputMode="numeric"
            placeholder="e.g. 12"
            value={actorId}
            onChange={(e) => setFilter("actor_id", e.target.value.replace(/\D/g, ""), setActorId)}
            className={`${field} w-32`}
          />
        </label>
        <label className="space-y-1 text-xs text-foreground-muted">
          <span className="block">From</span>
          <input type="date" value={startDate} max={endDate || undefined}
            onChange={(e) => setFilter("start_date", e.target.value, setStartDate)} className={field} />
        </label>
        <label className="space-y-1 text-xs text-foreground-muted">
          <span className="block">To</span>
          <input type="date" value={endDate} min={startDate || undefined}
            onChange={(e) => setFilter("end_date", e.target.value, setEndDate)} className={field} />
        </label>
        {filtered && (
          <button onClick={clearFilters} className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5">
            <X size={14} /> Clear filters
          </button>
        )}
      </div>

      {badDates && <p className="mb-3 text-sm text-warning">The start date is after the end date: no events can match.</p>}
      {error && <div className="mb-4 rounded-xl border border-error/40 bg-error-light px-4 py-3 text-sm text-error">{error}</div>}

      <div className="overflow-hidden overflow-x-auto rounded-xl border border-border bg-surface shadow-sm">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="w-8 px-2 py-3" />
              <th className="px-4 py-3">Time</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Entity</th>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Actor</th>
            </tr>
          </thead>
          <tbody className={loading ? "opacity-60" : ""}>
            {entries.map((e, i) => {
              const key = `${page}-${i}`;
              const isOpen = open === key;
              return (
                <Fragment key={key}>
                  <tr
                    className="cursor-pointer border-t border-border-light align-top hover:bg-slate-50 dark:hover:bg-white/5"
                    onClick={() => setOpen(isOpen ? null : key)}
                  >
                    <td className="px-2 py-3 text-foreground-muted">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-foreground-muted">{formatDateTime(e.timestamp)}</td>
                    <td className="px-4 py-3">
                      <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${SOURCE_TONE[e.source] || SOURCE_TONE.assist}`}>
                        {labelOf(e.source)}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-foreground">{humanize(e.action)}</td>
                    <td className="px-4 py-3 text-foreground-secondary">{humanize(e.entity_type)}{e.entity_id != null ? ` #${e.entity_id}` : ""}</td>
                    <td className="px-4 py-3 text-foreground-secondary">{e.organization_id != null ? `#${e.organization_id}` : "Platform"}</td>
                    <td className="px-4 py-3 text-foreground-muted">
                      {e.actor_id != null ? (
                        <button
                          className="underline-offset-2 hover:underline"
                          onClick={(ev) => { ev.stopPropagation(); setFilter("actor_id", String(e.actor_id), setActorId); }}
                          title="Show only this actor"
                        >
                          User #{e.actor_id}
                        </button>
                      ) : "System"}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-t border-border-light bg-background">
                      <td />
                      <td colSpan={6} className="px-4 py-3"><DetailView detail={e.detail} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {!loading && entries.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <ShieldAlert size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">
              {filtered ? "No audit events match these filters." : "No audit events recorded yet."}
            </p>
          </div>
        )}
        {loading && !data && (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-8 animate-pulse rounded bg-background" />)}
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-foreground-muted">
        <span>
          {total ? `Showing ${(page - 1) * PAGE_SIZE + 1}–${(page - 1) * PAGE_SIZE + entries.length} of ${total}` : "0 events"}
          {pages > 1 ? ` · page ${page} of ${pages}` : ""}
        </span>
        <div className="flex gap-2">
          <button disabled={page === 1 || loading} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button>
          <button disabled={page >= pages || loading} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button>
        </div>
      </div>
    </div>
  );
}
