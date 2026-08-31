import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";

import ProtectedRoute from "./components/ProtectedRoute";
import PayrollShell from "./components/PayrollShell";
import SuperAdminShell from "./components/SuperAdminShell";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import RegistrationSuccessPage from "./pages/RegistrationSuccessPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import OrgPortalPage from "./pages/OrgPortalPage";
import DashboardPage from "./pages/DashboardPage";
import UsersPage from "./pages/UsersPage";
import OrganizationsPage from "./pages/OrganizationsPage";
import SettingsPage from "./pages/SettingsPage";
import PolicyConfigPage from "./pages/PolicyConfigPage";
import CompliancePage from "./pages/CompliancePage";
import EngineFallbackDefaultsPage from "./pages/EngineFallbackDefaultsPage";
import {
  INCompliancePage, USACompliancePage, UKCompliancePage,
  AUCompliancePage, CACompliancePage, DECompliancePage,
} from "./pages/JurisdictionCompliance";
import StatutoryRatesPage from "./pages/StatutoryRatesPage";
import {
  INStatutoryPage, USAStatutoryPage, UKStatutoryPage,
  AUStatutoryPage, CAStatutoryPage, DEStatutoryPage,
} from "./pages/JurisdictionStatutory";
import FinancePage from "./pages/FinancePage";
import ReportsPage from "./pages/ReportsPage";
import ZoikoPayrollModule from "./modules/payroll";
import OrgAdminOrganizationPage from "./modules/organization-admin/OrganizationPage";
import AssistAdminPage from "./modules/assist/AssistAdminPage";
import TeamPage from "./modules/organization-admin/TeamPage";
import { ROLE_DEFAULT_REDIRECT, VALID_ROLES } from "./config/roles";

function LandingRedirect() {
  const user = JSON.parse(localStorage.getItem("zoiko_payroll_user") || "null");
  if (user?.role && user.role !== "super_admin") {
    const target = VALID_ROLES.includes(user.role) ? ROLE_DEFAULT_REDIRECT[user.role] : "/payroll";
    return <Navigate to={target} replace />;
  }
  return <Navigate to="/super-admin/dashboard" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/register/success" element={<RegistrationSuccessPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/portal" element={<OrgPortalPage />} />

        {/* Super Admin console — canonical routes */}
        <Route
          path="/super-admin/dashboard"
          element={
            <SuperAdminShell>
              <DashboardPage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/organizations"
          element={
            <SuperAdminShell>
              <OrganizationsPage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/users"
          element={
            <SuperAdminShell>
              <UsersPage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/compliance/policy/new"
          element={
            <SuperAdminShell>
              <PolicyConfigPage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/compliance"
          element={
            <SuperAdminShell>
              <CompliancePage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/compliance/engine-defaults"
          element={
            <SuperAdminShell>
              <EngineFallbackDefaultsPage />
            </SuperAdminShell>
          }
        />
        {/* Jurisdiction Compliance — one dedicated page per country,
            reusing the shared JurisdictionLayout. The optional
            :jurisdiction segment pre-selects a state (e.g.
            /super-admin/compliance/india/Telangana). */}
        <Route path="/super-admin/compliance/india" element={<SuperAdminShell><INCompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/india/:jurisdiction" element={<SuperAdminShell><INCompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/united-states" element={<SuperAdminShell><USACompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/united-states/:jurisdiction" element={<SuperAdminShell><USACompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/united-kingdom" element={<SuperAdminShell><UKCompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/united-kingdom/:jurisdiction" element={<SuperAdminShell><UKCompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/australia" element={<SuperAdminShell><AUCompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/australia/:jurisdiction" element={<SuperAdminShell><AUCompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/canada" element={<SuperAdminShell><CACompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/canada/:jurisdiction" element={<SuperAdminShell><CACompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/germany" element={<SuperAdminShell><DECompliancePage /></SuperAdminShell>} />
        <Route path="/super-admin/compliance/germany/:jurisdiction" element={<SuperAdminShell><DECompliancePage /></SuperAdminShell>} />
        <Route
          path="/super-admin/statutory-rates"
          element={
            <SuperAdminShell>
              <StatutoryRatesPage />
            </SuperAdminShell>
          }
        />
        {/* Jurisdiction Statutory Rates — one dedicated page per country,
            same split/pattern as Jurisdiction Compliance above. */}
        <Route path="/super-admin/statutory-rates/india" element={<SuperAdminShell><INStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/india/:jurisdiction" element={<SuperAdminShell><INStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/united-states" element={<SuperAdminShell><USAStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/united-states/:jurisdiction" element={<SuperAdminShell><USAStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/united-kingdom" element={<SuperAdminShell><UKStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/united-kingdom/:jurisdiction" element={<SuperAdminShell><UKStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/australia" element={<SuperAdminShell><AUStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/australia/:jurisdiction" element={<SuperAdminShell><AUStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/canada" element={<SuperAdminShell><CAStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/canada/:jurisdiction" element={<SuperAdminShell><CAStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/germany" element={<SuperAdminShell><DEStatutoryPage /></SuperAdminShell>} />
        <Route path="/super-admin/statutory-rates/germany/:jurisdiction" element={<SuperAdminShell><DEStatutoryPage /></SuperAdminShell>} />
        <Route
          path="/super-admin/finance"
          element={
            <SuperAdminShell>
              <FinancePage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/reports"
          element={
            <SuperAdminShell>
              <ReportsPage />
            </SuperAdminShell>
          }
        />
        <Route
          path="/super-admin/settings"
          element={
            <SuperAdminShell>
              <SettingsPage />
            </SuperAdminShell>
          }
        />

        {/* Legacy paths — permanent redirects so old links/bookmarks keep working */}
        <Route path="/dashboard" element={<Navigate to="/super-admin/dashboard" replace />} />
        <Route path="/users" element={<Navigate to="/super-admin/users" replace />} />
        <Route path="/statutory-rates" element={<Navigate to="/super-admin/statutory-rates" replace />} />
        <Route path="/organizations" element={<Navigate to="/super-admin/organizations" replace />} />
        <Route path="/settings" element={<Navigate to="/super-admin/settings" replace />} />
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
          path="/organization-admin/organization"
          element={
            <PayrollShell>
              <OrgAdminOrganizationPage />
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
        <Route
          path="/payroll/assist-admin"
          element={
            <PayrollShell>
              <AssistAdminPage />
            </PayrollShell>
          }
        />
        <Route
          path="/organization-admin/team"
          element={
            <PayrollShell>
              <TeamPage />
            </PayrollShell>
          }
        />
        {/* Dashboard + My Organization consolidated into one module — old
            dashboard URLs redirect so nothing that linked/bookmarked them breaks. */}
        <Route path="/organization-admin/dashboard" element={<Navigate to="/organization-admin/organization" replace />} />
        <Route path="/hr-admin/dashboard" element={<Navigate to="/hr-admin/my-organization" replace />} />
        <Route path="/" element={<LandingRedirect />} />
      </Route>
      <Route path="*" element={<LandingRedirect />} />
    </Routes>
  );
}
