import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";

import ProtectedRoute from "./components/ProtectedRoute";
import PayrollShell from "./components/PayrollShell";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import RegistrationSuccessPage from "./pages/RegistrationSuccessPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import OrgPortalPage from "./pages/OrgPortalPage";
import DashboardPage from "./pages/DashboardPage";
import UsersPage from "./pages/UsersPage";
import StatutoryRatesPage from "./pages/StatutoryRatesPage";
import OrganizationsPage from "./pages/OrganizationsPage";
import SettingsPage from "./pages/SettingsPage";
import ZoikoPayrollModule from "./modules/payroll";
import OrgAdminDashboardPage from "./modules/organization-admin/DashboardPage";
import OrgAdminOrganizationPage from "./modules/organization-admin/OrganizationPage";
import { ROLE_DEFAULT_REDIRECT, VALID_ROLES } from "./config/roles";

function LandingRedirect() {
  const user = JSON.parse(localStorage.getItem("zoiko_payroll_user") || "null");
  if (user?.role && user.role !== "super_admin") {
    const target = VALID_ROLES.includes(user.role) ? ROLE_DEFAULT_REDIRECT[user.role] : "/payroll";
    return <Navigate to={target} replace />;
  }
  return <Navigate to="/dashboard" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/register/success" element={<RegistrationSuccessPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/portal" element={<OrgPortalPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/statutory-rates" element={<StatutoryRatesPage />} />
        <Route path="/organizations" element={<OrganizationsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route
          path="/payroll"
          element={
            <PayrollShell>
              <ZoikoPayrollModule />
            </PayrollShell>
          }
        />
        <Route
          path="/payroll/*"
          element={
            <PayrollShell>
              <ZoikoPayrollModule />
            </PayrollShell>
          }
        />
        <Route
          path="/organization-admin/dashboard"
          element={
            <PayrollShell>
              <OrgAdminDashboardPage />
            </PayrollShell>
          }
        />
        <Route
          path="/organization-admin/organization"
          element={
            <PayrollShell>
              <OrgAdminOrganizationPage />
            </PayrollShell>
          }
        />
        <Route
          path="/hr-admin/dashboard"
          element={
            <PayrollShell>
              <OrgAdminDashboardPage />
            </PayrollShell>
          }
        />
        <Route
          path="/hr-admin/my-organization"
          element={
            <PayrollShell>
              <OrgAdminOrganizationPage />
            </PayrollShell>
          }
        />
        <Route path="/" element={<LandingRedirect />} />
      </Route>
      <Route path="*" element={<LandingRedirect />} />
    </Routes>
  );
}
