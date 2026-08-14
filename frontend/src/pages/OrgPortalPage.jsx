import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Building2, LogOut, UserCircle2 } from "lucide-react";

import { apiFetch, clearSession, getStoredUser } from "../api/client";
import { ROLE_LABELS, ROLES } from "../config/roles";

export default function OrgPortalPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState(getStoredUser());
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch("/api/auth/me")
      .then(setUser)
      .catch((err) => setError(err.message));
  }, []);

  function logout() {
    clearSession();
    navigate("/login", { replace: true });
  }

  const roleLabel = user?.role ? ROLE_LABELS[user.role] || user.role : "—";

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-primary-light via-white to-primary-light px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center">
          <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-9 w-auto object-contain" />
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-8 shadow-xl shadow-slate-900/[0.04]">
          <div className="flex justify-center">
            <div className="grid h-16 w-16 place-items-center rounded-full bg-gradient-to-br from-brand-blue to-category-teal shadow-lg shadow-brand-blue/25">
              <UserCircle2 size={32} className="text-white" />
            </div>
          </div>

          <h1 className="mt-5 text-center text-xl font-semibold tracking-tight text-slate-900">
            Welcome, {user?.first_name || "there"}
          </h1>
          <p className="mt-1 text-center text-sm text-slate-500">{user?.email || ""}</p>

          <div className="mt-6 space-y-3 rounded-xl border border-slate-100 bg-slate-50/60 p-4 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Role</span>
              <span className="inline-block rounded-full bg-primary-light px-2.5 py-0.5 text-xs font-medium text-info">
                {roleLabel}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Organization</span>
              <span className="flex items-center gap-1.5 font-medium text-slate-700">
                <Building2 size={14} className="text-slate-400" />
                {user?.organization_code || "—"}
              </span>
            </div>
          </div>

          {error && <p className="mt-4 text-center text-sm text-red-600">{error}</p>}

          <p className="mt-6 text-center text-xs leading-relaxed text-slate-400">
            Your payroll workspace is ready. Your organization admin can invite you to run pay
            runs, statutory rates and payslips.
          </p>

          {(user?.role === ROLES.ORG_ADMIN || user?.role === ROLES.PAYROLL_ADMIN) && (
            <Link
              to="/payroll"
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-brand-blue to-category-teal px-4 py-3 text-sm font-medium text-white shadow-sm transition-colors hover:from-brand-blue hover:to-category-teal"
            >
              Go to Payroll
            </Link>
          )}

          <button
            onClick={logout}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
