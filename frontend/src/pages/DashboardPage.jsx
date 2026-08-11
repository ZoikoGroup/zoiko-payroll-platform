import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, Users, ShieldCheck, CreditCard, RefreshCcw } from "lucide-react";

import { apiFetch } from "../api/client";

const CARDS = [
  { key: "total_organizations", label: "Organizations", icon: Building2 },
  { key: "active_organizations", label: "Active Organizations", icon: Building2 },
  { key: "total_users", label: "Users", icon: Users },
  { key: "super_admins", label: "Super Admins", icon: ShieldCheck },
  { key: "org_admins", label: "Org Admins", icon: Users },
  { key: "payroll_admins", label: "Payroll Admins", icon: Users },
  { key: "employees", label: "Employee Logins", icon: Users },
  { key: "total_payroll_employees", label: "Payroll Employees", icon: CreditCard },
  { key: "total_payroll_runs", label: "Payroll Runs", icon: RefreshCcw },
];

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    apiFetch("/api/super-admin/dashboard/stats")
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!stats) return <p className="text-slate-500">Loading…</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
        <button
          onClick={load}
          disabled={loading}
          title="Refresh stats"
          className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {CARDS.map(({ key, label, icon: Icon }) => (
          <div key={key} className="bg-white rounded-xl shadow-sm p-5">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-3xl font-bold text-slate-900">{stats[key] ?? 0}</div>
                <div className="text-xs text-slate-500 mt-1">{label}</div>
              </div>
              <Icon size={20} className="text-orange-500" />
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mt-8 mb-3">
        <h2 className="text-lg font-semibold text-slate-900">Recent Organizations</h2>
        <Link to="/organizations" className="text-sm font-medium text-orange-600 hover:text-orange-700">
          View all →
        </Link>
      </div>
      <div className="bg-white rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Code</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {(stats.recent_organizations || []).map((org) => (
              <tr key={org.id} className="border-t border-slate-100">
                <td className="px-4 py-3 font-medium text-slate-800">{org.organization_name}</td>
                <td className="px-4 py-3 text-slate-500">{org.organization_code}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                      org.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}
                  >
                    {org.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">
                  {new Date(org.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
