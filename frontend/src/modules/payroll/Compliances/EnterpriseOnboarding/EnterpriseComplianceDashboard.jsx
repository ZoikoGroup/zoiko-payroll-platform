import { useState, useEffect, useCallback } from "react";
import { Loader2, Calendar, Clock } from "lucide-react";
import { getEnterpriseDashboard } from "../../../../service/payrollService";

function StatTile({ label, value, accent }) {
  return (
    <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">{label}</p>
      <p className={`mt-2 text-2xl font-extrabold ${accent || "text-[#1A1816] dark:text-[#F0EDE8]"}`}>{value}</p>
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
        <Loader2 size={20} className="animate-spin text-[#9D7BF2]" />
      </div>
    );
  }
  if (!dashboard) return null;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatTile label="Configured Jurisdictions" value={dashboard.configuredCount} accent="text-[#19C58A]" />
        <StatTile label="Pending Configuration" value={dashboard.pendingCount} accent="text-[#F8A60A]" />
        <StatTile label="Active Countries" value={dashboard.activeCountries.length} accent="text-[#35B6F5]" />
        <StatTile label="Completion" value={`${dashboard.completionPct}%`} accent="text-[#9D7BF2]" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-3">
            <Calendar size={15} className="text-[#9E9690]" />
            <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Upcoming Government Filings</p>
          </div>
          {dashboard.upcomingFilings.length === 0 ? (
            <p className="text-[12px] text-[#9E9690]">No filing schedules recorded yet.</p>
          ) : (
            <ul className="space-y-2">
              {dashboard.upcomingFilings.map((f, i) => (
                <li key={i} className="text-[12px]">
                  <span className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{f.country}:</span>{" "}
                  <span className="text-[#6B6560] dark:text-[#A69B93]">{f.schedule}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-2 mb-3">
            <Clock size={15} className="text-[#9E9690]" />
            <p className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Recent Changes</p>
          </div>
          {dashboard.recentChanges.length === 0 ? (
            <p className="text-[12px] text-[#9E9690]">No enterprise activity yet.</p>
          ) : (
            <ul className="space-y-2 divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
              {dashboard.recentChanges.map((c, i) => (
                <li key={i} className="pt-2 first:pt-0 text-[12px] text-[#6B6560] dark:text-[#A69B93]">
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
