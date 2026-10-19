import React from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { getAccessToken, getStoredUser } from "../api/client";

// Navigation guard only - the server (route policy + data scope) is the
// control. This just keeps each role on the screens it can actually use, so
// nobody lands on a page whose every call would be refused.
const TENANT_PREFIXES = ["/payroll", "/billing/", "/register/", "/organization-admin/", "/hr-admin/"];
// Platform roles other than super_admin: the Support Access page and their
// own account security settings only.
const PLATFORM_LIMITED_PREFIXES = ["/super-admin/support-access", "/account/security"];
// Platform Security additionally reads the security & privacy plane (ZP-PRIV E).
const PLATFORM_SECURITY_PREFIXES = [
  ...PLATFORM_LIMITED_PREFIXES,
  "/super-admin/audit-explorer",
  "/super-admin/alerts",
  "/super-admin/privileged-inventory",
  "/super-admin/machine-clients",
  "/super-admin/privacy-assurance",
];

function allowed(pathname, prefixes) {
  return prefixes.some((p) => pathname === p || pathname.startsWith(p.endsWith("/") ? p : `${p}/`) ||
    pathname === p.replace(/\/$/, ""));
}

export default function ProtectedRoute() {
  const location = useLocation();
  if (!getAccessToken()) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  const role = getStoredUser()?.role;
  const { pathname } = location;
  if (role === "super_admin") {
    return <Outlet />;
  }
  if (role === "platform_security") {
    return allowed(pathname, PLATFORM_SECURITY_PREFIXES) ? <Outlet /> : <Navigate to="/super-admin/support-access" replace />;
  }
  if (role === "support_operator") {
    return allowed(pathname, PLATFORM_LIMITED_PREFIXES) ? <Outlet /> : <Navigate to="/super-admin/support-access" replace />;
  }
  if (role === "support_temp") {
    return pathname === "/support-session" ? <Outlet /> : <Navigate to="/support-session" replace />;
  }
  if (role && !allowed(pathname, [...TENANT_PREFIXES, "/account/security"])) {
    return <Navigate to="/payroll" replace />;
  }
  return <Outlet />;
}
