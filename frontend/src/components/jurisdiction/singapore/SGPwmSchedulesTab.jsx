import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { getSingaporePwmSchedules } from "../../../service/superAdminService";
import { formatDate, formatSgd } from "./sgComponentConfig";
import useSgStatutorySummary from "./useSgStatutorySummary";

// Singapore PWM overtime gross schedule viewer (Phase 5.6) — read-only,
// server-paginated (GET /super-admin/compliance/singapore/pwm-schedules);
// only one page is ever held in memory. Same Previous/Next pagination as
// the Super Admin FundingPaymentsPage. Sector options come from the backend
// summary, not a frontend list.
const PAGE_SIZE = 50;
const EMPTY = { sector: "", occupation_group: "", job_level: "", role_label: "", effective_on: "", overtime_hours: "", status: "", search: "" };

export default function SGPwmSchedulesTab() {
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(0);
  // `loaded.key` records which request the stored page belongs to, so
  // loading is derived rather than set synchronously inside the effect.
  const [loaded, setLoaded] = useState({ key: null, items: [], total: 0, error: null });
  const summary = useSgStatutorySummary(undefined);
  const pwm = (summary.data?.sections || []).find((s) => s.key === "pwm")?.values?.overtimeSchedule;
  const requestKey = JSON.stringify({ ...filters, page });
  const loading = loaded.key !== requestKey;
  const result = loaded;
  const error = loading ? null : loaded.error;

  useEffect(() => {
    let live = true;
    getSingaporePwmSchedules({ ...filters, skip: page * PAGE_SIZE, limit: PAGE_SIZE })
      .then((r) => { if (live) setLoaded({ key: requestKey, items: r.items, total: r.total, error: null }); })
      .catch((e) => { if (live) setLoaded({ key: requestKey, items: [], total: 0, error: e?.message || "Failed to load" }); });
    return () => { live = false; };
  }, [filters, page, requestKey]);

  const set = (key) => (e) => { setPage(0); setFilters((f) => ({ ...f, [key]: e.target.value })); };
  const input = "mt-1 block w-full rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground";

  return (
    <div className="space-y-3">
      <p className="flex items-center gap-1.5 rounded-lg border border-border bg-surface-muted/50 p-2 text-xs font-semibold text-foreground">
        <Lock size={13} aria-hidden="true" /> Statutory Reference Data — Read Only
        <span className="font-normal text-foreground-muted">
          · MOM &ldquo;Total PWM Gross Wage Requirement&rdquo; for overtime hours{pwm ? ` — ${pwm.totalRows} rows, ${pwm.schedules} schedules, ${pwm.overtimeHoursMin}–${pwm.overtimeHoursMax} OT hours` : ""}
        </span>
      </p>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
        <label className="text-xs text-foreground-muted">Search
          <input className={input} value={filters.search} onChange={set("search")} placeholder="Role or level" maxLength={100} />
        </label>
        <label className="text-xs text-foreground-muted">Sector
          <select className={input} value={filters.sector} onChange={set("sector")}>
            <option value="">All</option>
            {(pwm?.sectors || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="text-xs text-foreground-muted">Occupation group
          <input className={input} value={filters.occupation_group} onChange={set("occupation_group")} placeholder="e.g. ALL" />
        </label>
        <label className="text-xs text-foreground-muted">Job level
          <input className={input} value={filters.job_level} onChange={set("job_level")} />
        </label>
        <label className="text-xs text-foreground-muted">Exact role (MOM heading)
          <input className={input} value={filters.role_label} onChange={set("role_label")} maxLength={120} />
        </label>
        <label className="text-xs text-foreground-muted">In force on
          <input type="date" className={input} value={filters.effective_on} onChange={set("effective_on")} />
        </label>
        <label className="text-xs text-foreground-muted">Overtime hours
          <input type="number" min={0} max={72} className={input} value={filters.overtime_hours} onChange={set("overtime_hours")} />
        </label>
        <label className="text-xs text-foreground-muted">Status
          <select className={input} value={filters.status} onChange={set("status")}>
            <option value="">All</option>
            <option value="Active">Active</option>
            <option value="Superseded">Superseded</option>
          </select>
        </label>
      </div>

      {error && <p className="text-sm text-error" role="alert">{error}</p>}

      <div className="overflow-x-auto rounded-xl border border-border" aria-busy={loading}>
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-muted text-foreground-muted">
            <tr>
              {["Sector", "Group", "Job level", "Role", "Effective", "OT hours", "Required gross", "Source", "Status"].map((h) => (
                <th key={h} scope="col" className="px-3 py-2 font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={9} className="px-3 py-4 text-center text-foreground-muted">Loading…</td></tr>
            )}
            {!loading && result.items.map((r) => (
              <tr key={r.id} className="border-t border-border">
                <td className="px-3 py-1.5">{r.sector}</td>
                <td className="px-3 py-1.5">{r.occupationGroup}</td>
                <td className="px-3 py-1.5">{r.jobLevel}</td>
                <td className="px-3 py-1.5 text-foreground-secondary">{r.roleLabel}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{formatDate(r.effectiveFrom)} – {r.effectiveTo ? formatDate(r.effectiveTo) : "open"}</td>
                <td className="px-3 py-1.5 text-right">{r.overtimeHours}</td>
                <td className="px-3 py-1.5 text-right font-medium">{formatSgd(r.requiredGross)}</td>
                <td className="px-3 py-1.5 text-foreground-muted" title={`sha256 ${r.sourceSha256}`}>
                  {r.sourceUrl ? <a href={r.sourceUrl} target="_blank" rel="noreferrer" className="underline">{r.sourceTitle || `Source #${r.sourceDocumentId}`}</a> : (r.sourceTitle || `Source #${r.sourceDocumentId}`)}
                </td>
                <td className="px-3 py-1.5">{r.status}</td>
              </tr>
            ))}
            {!loading && result.items.length === 0 && (
              <tr><td colSpan={9} className="px-3 py-4 text-center text-foreground-disabled">No PWM schedule rows match.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-foreground-muted">
        <span>{result.total ? `Showing ${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, result.total)} of ${result.total}` : "0 rows"}</span>
        <div className="flex gap-2">
          <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Previous</button>
          <button type="button" disabled={(page + 1) * PAGE_SIZE >= result.total} onClick={() => setPage((p) => p + 1)} className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40">Next</button>
        </div>
      </div>
    </div>
  );
}
