import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Loader2, RefreshCw, ShieldCheck, ShieldX } from "lucide-react";
import { getStoredUser } from "../../api/client";
import { Badge, Banner, NotAvailable, RESULT_BADGE, card, input, primary, subtle } from "../../components/SecurityUi";
import { isUnavailable, securityPlatform as svc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// Audit Explorer (ZP-PRIV E01/E02): the unified, hash-chained security event
// log. Metadata only - ids, types, results and reason codes; no personal data.
const READERS = ["super_admin", "platform_security"];
const PAGE_SIZE = 50;
const FILTERS = [
  ["organizationId", "Organization id", "number"],
  ["actorUserId", "Actor user id", "number"],
  ["grantId", "Grant id", "number"],
  ["correlationId", "Correlation id", "text"],
  ["eventType", "Event type", "text"],
  ["startDate", "From", "date"],
  ["endDate", "To", "date"],
];
const FILTER_KEYS = [...FILTERS.map(([k]) => k), "result"];

function readFilters(params) {
  return Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) || ""]));
}

function VerifyBanner({ result }) {
  if (!result) return null;
  if (result.ok) {
    return (
      <Banner tone="success">
        <span className="inline-flex items-center gap-2 font-medium"><ShieldCheck size={16} aria-hidden="true" /> Chain verified</span>
        {" "}— {result.checked} event(s) checked, no gaps or edits. Head: <code className="break-all">{result.head || "—"}</code>
      </Banner>
    );
  }
  return (
    <Banner tone="error">
      <span className="inline-flex items-center gap-2 font-medium"><ShieldX size={16} aria-hidden="true" /> Chain broken</span>
      {" "}at event #{result.broken_at} after {result.checked} event(s). Treat this as a security incident.
    </Banner>
  );
}

export default function AuditExplorerPage() {
  const role = getStoredUser()?.role;
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(() => readFilters(params));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [verify, setVerify] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const skip = Math.max(0, Number(params.get("skip")) || 0);
  const query = params.toString();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const filters = readFilters(new URLSearchParams(query));
      setData(await svc.events({ ...filters, skip, limit: PAGE_SIZE }));
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load security events.");
    } finally {
      setLoading(false);
    }
  }, [query, skip]);

  useEffect(() => {
    if (!READERS.includes(role)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, role]);

  function apply(next) {
    const p = new URLSearchParams();
    Object.entries(next).forEach(([k, v]) => { if (v) p.set(k, v); });
    setParams(p);
  }

  function filterByCorrelation(id) {
    const next = { ...readFilters(new URLSearchParams()), correlationId: id };
    setDraft(next);
    apply(next);
  }

  async function runVerify() {
    setVerifying(true);
    try {
      setVerify(await svc.verifyChain());
    } catch (err) {
      setVerify(null);
      setError(isUnavailable(err) ? "Chain verification is not available for your account." : err.message);
    } finally {
      setVerifying(false);
    }
  }

  if (!READERS.includes(role) || unavailable) {
    return <div className="p-4 sm:p-6"><NotAvailable what="The Audit Explorer" /></div>;
  }

  const items = data?.items || [];
  const total = data?.total ?? 0;
  const setPage = (nextSkip) => setParams((p) => { p.set("skip", String(nextSkip)); return p; });

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Audit Explorer</h1>
          <p className="text-sm text-foreground-secondary">
            Every privileged decision, allowed or refused, in one tamper-evident log. Metadata only — no worker data.
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" className={subtle} onClick={load} disabled={loading}>
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} aria-hidden="true" /> Refresh
          </button>
          <button type="button" className={primary} onClick={runVerify} disabled={verifying}>
            {verifying && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Verify chain
          </button>
        </div>
      </div>
      <VerifyBanner result={verify} />
      {error && <Banner tone="error">{error}</Banner>}

      <form
        className={`${card} grid gap-3 sm:grid-cols-2 lg:grid-cols-4`}
        onSubmit={(e) => { e.preventDefault(); apply(draft); }}
      >
        {FILTERS.map(([key, label, type]) => (
          <label key={key} className="space-y-1 text-sm">
            <span className="text-foreground-secondary">{label}</span>
            <input className={input} type={type} min={type === "number" ? 1 : undefined} value={draft[key]}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
          </label>
        ))}
        <label className="space-y-1 text-sm">
          <span className="text-foreground-secondary">Result</span>
          <select className={input} value={draft.result} onChange={(e) => setDraft({ ...draft, result: e.target.value })}>
            <option value="">Any</option>
            <option value="allow">allow</option>
            <option value="deny">deny</option>
            <option value="error">error</option>
          </select>
        </label>
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
          <button type="submit" className={primary}>Apply filters</button>
          <button type="button" className={subtle}
            onClick={() => { const empty = readFilters(new URLSearchParams()); setDraft(empty); apply(empty); }}>
            Clear
          </button>
        </div>
      </form>

      <div className={`${card} overflow-x-auto`}>
        {!data ? (
          <p className="text-sm text-foreground-secondary">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No events match these filters.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr>
                <th className="py-2 pr-3">When</th><th className="pr-3">Event</th><th className="pr-3">Result</th>
                <th className="pr-3">Actor</th><th className="pr-3">Org</th><th className="pr-3">Grant</th>
                <th className="pr-3">Target</th><th className="pr-3">Reason</th><th>Correlation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {items.map((e) => (
                <tr key={e.id}>
                  <td className="py-2 pr-3 whitespace-nowrap">{formatDateTime(e.occurredAt)}</td>
                  <td className="pr-3">{e.eventType}{e.action ? <span className="text-foreground-secondary"> · {e.action}</span> : null}</td>
                  <td className="pr-3"><Badge className={RESULT_BADGE[e.result] || "bg-slate-200 text-slate-700"}>{e.result}</Badge></td>
                  <td className="pr-3 whitespace-nowrap">
                    {e.actorUserId ? `#${e.actorUserId}` : "—"}{e.actorRole ? ` (${e.actorRole})` : ""}
                    {e.onBehalfOfUserId ? <span className="text-foreground-secondary"> for #{e.onBehalfOfUserId}</span> : null}
                  </td>
                  <td className="pr-3">{e.organizationId ?? "—"}</td>
                  <td className="pr-3">{e.grantId ? `#${e.grantId}` : "—"}</td>
                  <td className="pr-3">{e.targetType ? `${e.targetType}${e.targetId ? ` ${e.targetId}` : ""}` : "—"}</td>
                  <td className="pr-3">{e.reasonCode || "—"}</td>
                  <td>
                    {e.correlationId ? (
                      <button type="button" className="font-mono text-xs text-blue-600 hover:underline"
                        title="Show every event with this correlation id" onClick={() => filterByCorrelation(e.correlationId)}>
                        {e.correlationId.slice(0, 12)}
                      </button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && (
        <div className="flex items-center justify-between text-sm text-foreground-secondary">
          <span>{total === 0 ? "0 events" : `${skip + 1}–${Math.min(skip + PAGE_SIZE, total)} of ${total}`}</span>
          <span className="flex gap-2">
            <button type="button" className={subtle} disabled={skip === 0} onClick={() => setPage(Math.max(0, skip - PAGE_SIZE))}>Previous</button>
            <button type="button" className={subtle} disabled={skip + PAGE_SIZE >= total} onClick={() => setPage(skip + PAGE_SIZE)}>Next</button>
          </span>
        </div>
      )}
    </div>
  );
}
