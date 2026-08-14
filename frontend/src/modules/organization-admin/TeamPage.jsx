import { useCallback, useEffect, useState } from "react";
import { UserPlus, Mail, Ban, RefreshCw, Users, CheckCircle2, AlertTriangle, Search } from "lucide-react";

import { useAuth } from "../../context/AuthContext";
import { ROLES, ROLE_LABELS } from "../../config/roles";
import Modal from "../../components/Modal";
import ConfirmDialog from "../../components/ConfirmDialog";
import StatusPill from "../../components/StatusPill";
import { getEmployees } from "../../service/payrollService";
import {
  listOrgUsers, invitePayrollAdmin, deactivateOrgUser, resendUserInvite,
} from "../../service/orgAdminService";

// This route renders directly under PayrollShell (not inside the payroll
// module or the Super Admin shell), so neither of the app's two
// ToastContext providers is mounted here — same reason OrganizationPage.jsx
// uses a local inline banner instead of useToast(). Keep this consistent.
function Banner({ feedback }) {
  if (!feedback) return null;
  const isError = feedback.type === "error";
  return (
    <div
      className={`mb-4 flex items-center gap-2 rounded-lg border px-4 py-3 text-sm ${
        isError
          ? "border-red-200 bg-red-50 text-red-600 dark:bg-red-950/30 dark:border-red-900 dark:text-red-400"
          : "border-green-200 bg-green-50 text-green-700 dark:bg-green-950/30 dark:border-green-900 dark:text-green-400"
      }`}
    >
      {isError ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
      {feedback.message}
    </div>
  );
}

function splitName(fullName) {
  const parts = (fullName || "").trim().split(/\s+/);
  return { firstName: parts[0] || "", lastName: parts.slice(1).join(" ") || parts[0] || "" };
}

function InviteModal({ onClose, onInvited, onError, existingEmails }) {
  const [source, setSource] = useState("employee"); // "employee" | "manual"
  const [form, setForm] = useState({ email: "", firstName: "", lastName: "", phone: "" });
  const [busy, setBusy] = useState(false);

  // Sourced from GET /api/payroll/employees, which scopes strictly to the
  // logged-in Org Admin's own organization_id (from their JWT, not a
  // client-supplied value) — a Sterling Vantage admin can never see or pick
  // an employee belonging to any other organization here.
  const [employees, setEmployees] = useState([]);
  const [employeesLoading, setEmployeesLoading] = useState(true);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(null);

  useEffect(() => {
    getEmployees({ status: "Active" }).then((rows) => {
      setEmployees(Array.isArray(rows) ? rows : []);
      setEmployeesLoading(false);
    });
  }, []);

  const alreadyInvitedEmails = new Set((existingEmails || []).map((e) => e.toLowerCase()));
  const filteredEmployees = employees.filter((e) => {
    if (!e.email) return false; // can't invite a login without an email
    const q = employeeSearch.trim().toLowerCase();
    if (!q) return true;
    return (e.name || "").toLowerCase().includes(q) || e.email.toLowerCase().includes(q);
  });

  function selectEmployee(emp) {
    const { firstName, lastName } = splitName(emp.name);
    setForm({ email: emp.email, firstName, lastName, phone: emp.phone || "" });
    setSelectedEmployeeId(emp.id);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await invitePayrollAdmin(form);
      onInvited(form.email);
      onClose();
    } catch (err) {
      onError(err.message || "Failed to invite Payroll Admin.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Invite Payroll Admin" onClose={onClose} maxWidth="max-w-xl">
      <p className="text-sm text-foreground-muted mb-4">
        They'll receive an email with a link to set their own password. Payroll Admin is the only role you can
        invite here.
      </p>

      <div className="flex gap-1.5 bg-slate-100 dark:bg-white/5 rounded-lg p-1 mb-4">
        <button
          type="button"
          onClick={() => setSource("employee")}
          className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
            source === "employee"
              ? "bg-surface text-foreground shadow-sm"
              : "text-foreground-muted"
          }`}
        >
          From Existing Employee
        </button>
        <button
          type="button"
          onClick={() => setSource("manual")}
          className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
            source === "manual"
              ? "bg-surface text-foreground shadow-sm"
              : "text-foreground-muted"
          }`}
        >
          Enter Manually
        </button>
      </div>

      {source === "employee" && (
        <div className="mb-4">
          <div className="relative mb-2">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={employeeSearch}
              onChange={(e) => setEmployeeSearch(e.target.value)}
              placeholder="Search your organization's employees…"
              className="w-full rounded-lg border border-border bg-background py-2 pl-8 pr-3 text-sm text-foreground"
            />
          </div>
          <div className="max-h-48 overflow-y-auto rounded-lg border border-border">
            {employeesLoading ? (
              <p className="py-6 text-center text-sm text-foreground-disabled">Loading employees…</p>
            ) : filteredEmployees.length === 0 ? (
              <p className="py-6 text-center text-sm text-foreground-disabled">
                No matching active employees with an email on file.
              </p>
            ) : (
              filteredEmployees.map((emp) => {
                const alreadyInvited = alreadyInvitedEmails.has((emp.email || "").toLowerCase());
                return (
                  <button
                    key={emp.id}
                    type="button"
                    disabled={alreadyInvited}
                    onClick={() => selectEmployee(emp)}
                    className={`flex w-full items-center justify-between gap-3 border-b border-border-light px-3.5 py-2.5 text-left last:border-b-0 ${
                      selectedEmployeeId === emp.id
                        ? "bg-primary-light dark:bg-primary-active/20"
                        : "hover:bg-surface-muted"
                    } ${alreadyInvited ? "opacity-40 cursor-not-allowed" : ""}`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-foreground">{emp.name}</span>
                      <span className="block truncate text-xs text-foreground-disabled">{emp.email}</span>
                    </span>
                    {alreadyInvited && (
                      <span className="shrink-0 text-[11px] text-foreground-disabled">Already a user</span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}

      {(source === "manual" || selectedEmployeeId) && (
        <form onSubmit={handleSubmit} className="space-y-3">
          {source === "employee" && selectedEmployeeId && (
            <p className="text-xs text-foreground-muted">
              Pre-filled from the employee record — you can still adjust it below before sending.
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-foreground-secondary mb-1">First name</label>
              <input
                required
                value={form.firstName}
                onChange={(e) => setForm((f) => ({ ...f, firstName: e.target.value }))}
                className="w-full rounded-lg border border-border bg-background py-2 px-3 text-sm text-foreground"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-foreground-secondary mb-1">Last name</label>
              <input
                required
                value={form.lastName}
                onChange={(e) => setForm((f) => ({ ...f, lastName: e.target.value }))}
                className="w-full rounded-lg border border-border bg-background py-2 px-3 text-sm text-foreground"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-foreground-secondary mb-1">Email</label>
            <input
              required
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              className="w-full rounded-lg border border-border bg-background py-2 px-3 text-sm text-foreground"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-foreground-secondary mb-1">Phone (optional)</label>
            <input
              value={form.phone}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
              className="w-full rounded-lg border border-border bg-background py-2 px-3 text-sm text-foreground"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="px-4 py-2 rounded-lg text-sm font-medium text-foreground-secondary bg-slate-100 dark:bg-white/10 hover:bg-slate-200 dark:hover:bg-white/20 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50"
            >
              {busy ? "Sending…" : "Send Invite"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export default function TeamPage() {
  const { hasRole } = useAuth();
  const isOrgAdmin = hasRole(ROLES.ORG_ADMIN);

  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [showInvite, setShowInvite] = useState(false);
  const [deactivating, setDeactivating] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    listOrgUsers({ limit: 100 })
      .then((res) => setUsers(res.users || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (isOrgAdmin) load();
  }, [isOrgAdmin, load]);

  async function handleDeactivate() {
    setBusy(true);
    try {
      await deactivateOrgUser(deactivating.id);
      setFeedback({ type: "success", message: `${deactivating.first_name} deactivated.` });
      setDeactivating(null);
      load();
    } catch (err) {
      setFeedback({ type: "error", message: err.message || "Failed to deactivate user." });
    } finally {
      setBusy(false);
    }
  }

  async function handleResend(user) {
    try {
      await resendUserInvite(user.id);
      setFeedback({ type: "success", message: `Invite re-sent to ${user.email}.` });
    } catch (err) {
      setFeedback({ type: "error", message: err.message || "Failed to resend invite." });
    }
  }

  if (!isOrgAdmin) {
    return (
      <div className="p-6 lg:p-8 flex flex-col items-center justify-center gap-2 py-20 text-center">
        <Users size={28} className="text-border-strong" />
        <p className="text-sm text-foreground-disabled">
          Only an Organization Admin can manage the team.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Team</h1>
          <p className="text-sm text-foreground-muted mt-0.5">
            Invite Payroll Admins into your organization and manage their access.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={() => setShowInvite(true)}
            className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white hover:bg-primary-hover"
          >
            <UserPlus size={16} />
            Invite Payroll Admin
          </button>
        </div>
      </div>

      <Banner feedback={feedback} />

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Joined</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-border-light">
                <td className="px-4 py-3 font-medium text-foreground">
                  {u.first_name} {u.last_name}
                </td>
                <td className="px-4 py-3 text-foreground-secondary">{u.email}</td>
                <td className="px-4 py-3 text-foreground-secondary">{ROLE_LABELS[u.role] || u.role}</td>
                <td className="px-4 py-3">
                  <StatusPill status={u.is_active ? "active" : "inactive"} />
                </td>
                <td className="px-4 py-3 text-xs text-foreground-muted">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    {u.role === ROLES.PAYROLL_ADMIN && (
                      <button
                        onClick={() => handleResend(u)}
                        title="Resend invite email"
                        className="rounded-lg bg-slate-100 dark:bg-white/10 p-1.5 text-foreground-secondary hover:bg-slate-200 dark:hover:bg-white/20"
                      >
                        <Mail size={14} />
                      </button>
                    )}
                    {u.role === ROLES.PAYROLL_ADMIN && u.is_active && (
                      <button
                        onClick={() => setDeactivating(u)}
                        title="Deactivate"
                        className="rounded-lg bg-red-50 dark:bg-red-950/40 p-1.5 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-950/60"
                      >
                        <Ban size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && users.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Users size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No team members yet.</p>
          </div>
        )}
      </div>

      {showInvite && (
        <InviteModal
          existingEmails={users.map((u) => u.email)}
          onClose={() => setShowInvite(false)}
          onInvited={(email) => {
            setFeedback({ type: "success", message: `Invite sent to ${email}.` });
            load();
          }}
          onError={(message) => setFeedback({ type: "error", message })}
        />
      )}
      {deactivating && (
        <ConfirmDialog
          title="Deactivate User"
          message={`Deactivate ${deactivating.first_name} ${deactivating.last_name} (${deactivating.email})? They will no longer be able to log in.`}
          confirmLabel="Deactivate"
          busy={busy}
          onConfirm={handleDeactivate}
          onClose={() => setDeactivating(null)}
        />
      )}
    </div>
  );
}
