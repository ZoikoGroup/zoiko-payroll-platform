import React, { useEffect, useState, useCallback } from "react";
import { Eye, KeyRound, RefreshCw, Users as UsersIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { apiFetch, clearSession } from "../api/client";
import { useToast } from "../context/ToastContext";
import SearchInput from "../components/SearchInput";
import StatusPill from "../components/StatusPill";
import UserDetailDrawer, { formatDateTime } from "../components/superAdmin/UserDetailDrawer";

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

// Role badge styling
function roleBadge(role) {
  const map = {
    org_admin: "bg-blue-50 text-blue-700",
    payroll_admin: "bg-indigo-50 text-indigo-700",
    employee: "bg-slate-50 text-slate-700",
  };
  return `inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${map[role] || "bg-surface-muted text-foreground-secondary"}`;
}

// ZP-PRIV A03: platform staff cannot reset credentials for a tenant user
// without tenant consent or a live JIT support grant. A tenant user has a
// non-null organization_id; a platform user has organization_id === null.
function canResetPassword(u) {
  return u.organization_id == null;
}

export default function UsersPage() {
  const { addToast } = useToast();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [detailId, setDetailId] = useState(null);

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
      .catch((err) => {
        // 401 means the session is invalid — clear it and send to login.
        // A 403 is a missing permission, not a dead session.
        if (err.status === 401) {
          clearSession();
          navigate("/login", { replace: true });
          return;
        }
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [search, role, navigate]);

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
      if (err.status === 401) {
        clearSession();
        navigate("/login", { replace: true });
        return;
      }
      addToast?.(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(u) {
    setBusyId(u.id);
    try {
      await apiFetch(`/api/super-admin/users/${u.id}/reset-password`, { method: "PUT" });
      addToast?.(`Password reset link sent to ${u.email}.`);
      load();
    } catch (err) {
      if (err.status === 401) {
        clearSession();
        navigate("/login", { replace: true });
        return;
      }
      addToast?.(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Platform Users</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          {loading ? "Loading…" : `${total} user${total === 1 ? "" : "s"}`}
        </p>
      </div>

      <div className="flex flex-wrap gap-3 mb-4">
        <SearchInput value={search} onChange={setSearch} placeholder="Search email or name…" />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-lg border border-border bg-surface text-foreground px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus-ring"
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
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
        >
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">
          {error}
        </p>
      )}

      <div className="bg-surface rounded-xl shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
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
              <tr
                key={u.id}
                onClick={() => setDetailId(u.id)}
                className="cursor-pointer border-t border-border-light hover:bg-surface-muted/60 transition-colors"
              >
                <td className="px-4 py-3 font-medium text-foreground-secondary">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-light text-xs font-semibold text-primary-hover">
                      {initialsFor(u.first_name, u.last_name, u.email)}
                    </span>
                    <div className="flex flex-col">
                      <span className="font-medium text-foreground">
                        {u.first_name} {u.last_name}
                      </span>
                      {u.organization_id == null && (
                        <span className="text-[10px] text-foreground-muted">Platform account</span>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-foreground-secondary">{u.email}</td>
                <td className="px-4 py-3">
                  <span className={roleBadge(u.role)}>{u.role}</span>
                </td>
                <td className="px-4 py-3 text-foreground-muted">
                  {u.organization_name || (u.organization_id == null ? "— (platform)" : "—")}
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={u.is_active ? "active" : "inactive"} />
                </td>
                <td
                  className="px-4 py-3 whitespace-nowrap text-foreground-muted"
                  title={u.created_at ? new Date(u.created_at).toISOString().replace("T", " ").slice(0, 19) + " UTC" : undefined}
                >
                  {formatDateTime(u.created_at) || "—"}
                </td>
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-2 whitespace-nowrap">
                    <button
                      onClick={() => setDetailId(u.id)}
                      className="flex items-center gap-1 rounded-lg bg-primary-light px-2.5 py-1 text-xs font-medium text-primary-hover hover:bg-primary/20"
                    >
                      <Eye size={12} />
                      View
                    </button>
                    <button
                      disabled={busyId === u.id || (me && me.id === u.id)}
                      title={me && me.id === u.id ? "You can't deactivate your own account" : undefined}
                      onClick={() => toggleStatus(u)}
                      className={`rounded-lg px-2.5 py-1 text-xs font-medium disabled:opacity-40 ${
                        u.is_active
                          ? "bg-error-light text-error hover:bg-error/20"
                          : "bg-success-light text-success hover:bg-success/20"
                      }`}
                    >
                      {u.is_active ? "Deactivate" : "Activate"}
                    </button>
                    <button
                      disabled={busyId === u.id || !canResetPassword(u)}
                      title={
                        !canResetPassword(u)
                          ? "Cannot reset tenant credentials without tenant consent or a live JIT support grant (ZP-PRIV A03)"
                          : undefined
                      }
                      onClick={() => resetPassword(u)}
                      className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium disabled:opacity-40 ${
                        !canResetPassword(u)
                          ? "bg-surface-muted text-foreground-disabled cursor-not-allowed"
                          : "bg-surface-muted text-foreground-secondary hover:bg-border-light"
                      }`}
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
            <UsersIcon size={28} className="text-foreground-disabled" />
            <p className="text-sm text-foreground-disabled">
              {search || role ? "No users match your filters." : "No users found."}
            </p>
          </div>
        )}
      </div>
      {detailId !== null && <UserDetailDrawer userId={detailId} onClose={() => setDetailId(null)} />}
    </div>
  );
}
