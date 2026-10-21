import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getStoredUser } from "../../service/api";
import { Badge, Banner, NotAvailable, RESULT_BADGE, card, input, primary, subtle } from "../../components/SecurityUi";
import { isUnavailable, securityTenant as svc } from "../../service/securityService";
import { formatDateTime } from "../../utils/time";

// Security Activity (ZP-PRIV E02): your organization's own security events -
// sign-ins, refusals, support access, API clients. Scoped to your organization
// by the server; metadata only.
const PAGE_SIZE = 50;
const EMPTY = { actorUserId: "", result: "", eventType: "", startDate: "", endDate: "" };

export default function SecurityActivityPage() {
  const role = getStoredUser()?.role;
  const [draft, setDraft] = useState(EMPTY);
  const [filters, setFilters] = useState(EMPTY);
  const [skip, setSkip] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await svc.events({ ...filters, skip, limit: PAGE_SIZE }));
      setError(null);
    } catch (err) {
      if (isUnavailable(err)) setUnavailable(true);
      else setError(err.message || "Could not load security activity.");
    }
  }, [filters, skip]);

  useEffect(() => {
    if (role !== "org_admin") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load, role]);

  if (role !== "org_admin" || unavailable) {
    return <div className="p-4 sm:p-6"><NotAvailable what="Security activity" /></div>;
  }

  const items = data?.items || [];
  const total = data?.total ?? 0;
  const byResult = data?.byResult || {};

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Security Activity</h1>
          <p className="text-sm text-foreground-secondary">
            Sign-ins, refused actions, support access and API client activity in your organization.
          </p>
        </div>
        <button type="button" className={subtle} onClick={load}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
      </div>
      {error && <Banner tone="error">{error}</Banner>}
      <div className="flex flex-wrap gap-3">
        {["allow", "deny", "error"].map((r) => (
          <div key={r} className={`${card} min-w-[130px]`}>
            <p className="text-2xl font-bold leading-none text-foreground">{byResult[r] ?? 0}</p>
            <p className="mt-1 text-xs text-foreground-secondary">{r === "allow" ? "Allowed" : r === "deny" ? "Refused" : "Errors"}</p>
          </div>
        ))}
      </div>
      <form className={`${card} grid gap-3 sm:grid-cols-2 lg:grid-cols-5`}
        onSubmit={(e) => { e.preventDefault(); setSkip(0); setFilters(draft); }}>
        <label className="space-y-1 text-sm">
          <span className="text-foreground-secondary">User id</span>
          <input className={input} type="number" min={1} value={draft.actorUserId} onChange={(e) => setDraft({ ...draft, actorUserId: e.target.value })} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-foreground-secondary">Event type</span>
          <input className={input} value={draft.eventType} onChange={(e) => setDraft({ ...draft, eventType: e.target.value })} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-foreground-secondary">Result</span>
          <select className={input} value={draft.result} onChange={(e) => setDraft({ ...draft, result: e.target.value })}>
            <option value="">Any</option><option value="allow">allow</option><option value="deny">deny</option><option value="error">error</option>
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-foreground-secondary">From</span>
          <input className={input} type="date" value={draft.startDate} onChange={(e) => setDraft({ ...draft, startDate: e.target.value })} />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-foreground-secondary">To</span>
          <input className={input} type="date" value={draft.endDate} onChange={(e) => setDraft({ ...draft, endDate: e.target.value })} />
        </label>
        <div className="flex gap-2 sm:col-span-2 lg:col-span-5">
          <button type="submit" className={primary}>Apply filters</button>
          <button type="button" className={subtle} onClick={() => { setDraft(EMPTY); setFilters(EMPTY); setSkip(0); }}>Clear</button>
        </div>
      </form>
      <div className={`${card} overflow-x-auto`}>
        {!data ? <p className="text-sm text-foreground-secondary">Loading…</p> : items.length === 0 ? (
          <p className="text-sm text-foreground-secondary">No security activity matches these filters.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-foreground-secondary">
              <tr><th className="py-2 pr-3">When</th><th className="pr-3">Event</th><th className="pr-3">Result</th>
                <th className="pr-3">Who</th><th className="pr-3">Target</th><th className="pr-3">Reason</th><th>Support access</th></tr>
            </thead>
            <tbody className="divide-y divide-border-light text-foreground">
              {items.map((e) => (
                <tr key={e.id}>
                  <td className="py-2 pr-3 whitespace-nowrap">{formatDateTime(e.occurredAt)}</td>
                  <td className="pr-3">{e.eventType}{e.action ? <span className="text-foreground-secondary"> · {e.action}</span> : null}</td>
                  <td className="pr-3"><Badge className={RESULT_BADGE[e.result] || "bg-slate-200 text-slate-700"}>{e.result}</Badge></td>
                  <td className="pr-3 whitespace-nowrap">{e.actorUserId ? `#${e.actorUserId}` : "—"}{e.actorRole ? ` (${e.actorRole})` : ""}</td>
                  <td className="pr-3">{e.targetType ? `${e.targetType}${e.targetId ? ` ${e.targetId}` : ""}` : "—"}</td>
                  <td className="pr-3">{e.reasonCode || "—"}</td>
                  <td>{e.grantId ? `#${e.grantId}${e.ticketReference ? ` · ${e.ticketReference}` : ""}` : "—"}</td>
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
            <button type="button" className={subtle} disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}>Previous</button>
            <button type="button" className={subtle} disabled={skip + PAGE_SIZE >= total} onClick={() => setSkip(skip + PAGE_SIZE)}>Next</button>
          </span>
        </div>
      )}
    </div>
  );
}
