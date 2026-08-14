import { useState, useEffect, useCallback } from "react";
import { Loader2, Calendar, Clock } from "lucide-react";
import { getEnterpriseDashboard } from "../../../../service/payrollService";

function StatTile({ label, value, accent }) {
  return (
    <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</p>
      <p className={`mt-2 text-2xl font-extrabold ${accent || "text-foreground"}`}>{value}</p>
    </div>
  );
}

export default function EnterpriseComplianceDashboard({ refreshKey }) {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const d = await getEnterpriseDashboard();
    setDashboard(d);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={20} className="animate-spin text-category-teal" />
      </div>
    );
  }
  if (!dashboard) return null;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatTile label="Configured Jurisdictions" value={dashboard.configuredCount} accent="text-primary" />
        <StatTile label="Pending Configuration" value={dashboard.pendingCount} accent="text-warning" />
        <StatTile label="Active Countries" value={dashboard.activeCountries.length} accent="text-info" />
        <StatTile label="Completion" value={`${dashboard.completionPct}%`} accent="text-category-teal" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-3">
            <Calendar size={15} className="text-foreground-muted" />
            <p className="text-[13px] font-bold text-foreground">Upcoming Government Filings</p>
          </div>
          {dashboard.upcomingFilings.length === 0 ? (
            <p className="text-[12px] text-foreground-muted">No filing schedules recorded yet.</p>
          ) : (
            <ul className="space-y-2">
              {dashboard.upcomingFilings.map((f, i) => (
                <li key={i} className="text-[12px]">
                  <span className="font-semibold text-foreground">{f.country}:</span>{" "}
                  <span className="text-foreground-muted">{f.schedule}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-3">
            <Clock size={15} className="text-foreground-muted" />
            <p className="text-[13px] font-bold text-foreground">Recent Changes</p>
          </div>
          {dashboard.recentChanges.length === 0 ? (
            <p className="text-[12px] text-foreground-muted">No enterprise activity yet.</p>
          ) : (
            <ul className="space-y-2 divide-y divide-border">
              {dashboard.recentChanges.map((c, i) => (
                <li key={i} className="pt-2 first:pt-0 text-[12px] text-foreground-muted">
                  {c.description}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
