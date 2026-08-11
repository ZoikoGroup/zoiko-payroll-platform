import React, { useEffect, useState, useCallback } from "react";
import { KeyRound, RefreshCw, Users as UsersIcon } from "lucide-react";

import { apiFetch } from "../api/client";
import { useToast } from "../context/ToastContext";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";

const ROLES = ["org_admin", "payroll_admin", "employee"];

function initialsFor(firstName, lastName, email) {
  const name = [firstName, lastName].filter(Boolean).join(" ") || email || "";
  return (
    name
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase() || "?"
  );
}

export default function UsersPage() {
  const { addToast } = useToast();
  const [users, setUsers] = useState([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    apiFetch("/api/super-admin/users", {
      params: { search, role, limit: 200 },
    })
      .then((data) => {
        setUsers(data.users);
        setTotal(data.total);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [search, role]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    apiFetch("/api/auth/me").then(setMe).catch(() => {});
  }, []);

  async function toggleStatus(u) {
    setBusyId(u.id);
    try {
      await apiFetch(`/api/super-admin/users/${u.id}/status`, {
        method: "PUT",
        params: { is_active: !u.is_active },
      });
      addToast?.(`User ${u.email} ${u.is_active ? "deactivated" : "activated"}.`);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(u) {
    setBusyId(u.id);
    try {
      await apiFetch(`/api/super-admin/users/${u.id}/reset-password`, { method: "PUT" });
      addToast?.(`Reset link sent to ${u.email}.`);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Platform Users</h1>
        <p className="text-sm text-slate-500 mt-0.5">{loading ? "Loading…" : `${total} user${total === 1 ? "" : "s"}`}</p>
      </div>

      <div className="flex flex-wrap gap-3 mb-4">
        <SearchInput value={search} onChange={setSearch} placeholder="Search email or name…" />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
        >
          <option value="">All roles</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
        >
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="bg-white rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-slate-100 hover:bg-slate-50/60 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-800">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-orange-100 text-xs font-semibold text-orange-600">
                      {initialsFor(u.first_name, u.last_name, u.email)}
                    </span>
                    {u.first_name} {u.last_name}
                  </div>
                </td>
                <td className="px-4 py-3 text-slate-600">{u.email}</td>
                <td className="px-4 py-3">
                  <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                    {u.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">{u.organization_name || "—"}</td>
                <td className="px-4 py-3">
                  <StatusPill status={u.is_active ? "active" : "inactive"} />
                </td>
                <td className="px-4 py-3 text-slate-500">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      disabled={busyId === u.id || (me && me.id === u.id)}
                      title={me && me.id === u.id ? "You can't deactivate your own account" : undefined}
                      onClick={() => toggleStatus(u)}
                      className={`rounded-lg px-2.5 py-1 text-xs font-medium disabled:opacity-40 ${
                        u.is_active
                          ? "bg-red-50 text-red-600 hover:bg-red-100"
                          : "bg-green-50 text-green-700 hover:bg-green-100"
                      }`}
                    >
                      {u.is_active ? "Deactivate" : "Activate"}
                    </button>
                    <button
                      disabled={busyId === u.id}
                      onClick={() => resetPassword(u)}
                      className="flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-40"
                    >
                      <KeyRound size={12} />
                      Reset PW
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && users.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <UsersIcon size={28} className="text-slate-300" />
            <p className="text-sm text-slate-400">
              {search || role ? "No users match your filters." : "No users found."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
