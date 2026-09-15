import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { getFilingCalendarEntries } from "../../../service/superAdminService";

// India Compliance Calendar (ZP-TAX-IN-2026-27-001 §6.3, gap-closure
// Phase F, 2026-09-11) — a read view over the EXISTING generic
// StatutoryFilingCalendar registry (service.py's list_filing_calendar,
// already exposed at GET /api/super-admin/report-templates/filing-
// calendar) filtered to India — no new backend endpoint, no new seed
// logic: backend/scripts/seed_statutory_report_templates.py already
// seeds Form 138's own Q1-Q4 due dates (31 Jul / 31 Oct / 31 Jan / 31
// May) exactly as printed in §6.3, via this same StatutoryFilingCalendar
// model. Whether that seed script has actually been RUN against any
// live/test database in this session is unverified — this tab shows
// whatever rows genuinely exist, with an honest empty state otherwise
// (never fabricated placeholder dates).
const STATUS_STYLE = {
  Scheduled: "bg-info/10 text-info",
  Due: "bg-warning/10 text-warning",
  Filed: "bg-success/10 text-success",
  Overdue: "bg-error/10 text-error",
};

export default function INComplianceCalendarTab() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getFilingCalendarEntries({ country: "IN" })
      .then((data) => setEntries(Array.isArray(data) ? data : []))
      .finally(() => setLoading(false));
  }, []);

  const sorted = [...entries].sort((a, b) => String(a.dueDate).localeCompare(String(b.dueDate)));

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-info/30 bg-info/5 px-3 py-2 text-[11px] text-foreground-secondary">
        India's statutory filing due dates (Form 138 quarterly TDS statement, §6.3, and any other filing-calendar
        entries seeded for India) — reads the same platform-wide filing-calendar registry every other jurisdiction
        uses. Empty means nothing has been seeded for India yet, not that no obligation exists.
      </div>
      {loading ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : sorted.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-8 text-center text-xs text-foreground-disabled">
          No filing-calendar entries seeded for India yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-background text-left text-foreground-muted">
              <tr>
                <th className="px-3 py-2">Report</th>
                <th className="px-3 py-2">Reporting Year</th>
                <th className="px-3 py-2">Period</th>
                <th className="px-3 py-2">Due Date</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((e) => (
                <tr key={e.id} className="border-t border-border-light">
                  <td className="px-3 py-2 font-medium text-foreground flex items-center gap-1.5"><CalendarClock size={13} className="text-foreground-disabled" /> {e.reportType}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{e.reportingYear}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{e.periodLabel || e.periodKey}</td>
                  <td className="px-3 py-2 text-foreground-secondary">{e.dueDate}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_STYLE[e.status] || "bg-surface-muted text-foreground-muted"}`}>{e.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
