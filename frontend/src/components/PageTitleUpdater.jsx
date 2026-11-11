import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { getPageLabel as getSuperAdminPageLabel } from "./superAdminNav";

const PUBLIC_TITLES = {
  "/": "Cloud Payroll & Statutory Compliance Platform",
  "/login": "Sign In",
  "/register": "Create Account",
  "/trial-register": "Try Free",
  "/register/success": "Registration Successful",
  "/register/plan-review": "Review Plan",
  "/forgot-password": "Forgot Password",
  "/reset-password": "Reset Password",
  "/billing/plans": "Plans & Pricing",
  "/billing/checkout/success": "Checkout Successful",
  "/billing/checkout/cancel": "Checkout Cancelled",
};

const PAYROLL_TITLES = {
  "/payroll": "Dashboard",
  "/payroll/employees": "Employees",
  "/payroll/attendance": "Attendance",
  "/payroll/leaves": "Leaves",
  "/payroll/policy": "Payroll Policy",
  "/payroll/payroll-runs": "Payroll Runs",
  "/payroll/payslips": "Payslips",
  "/payroll/compliances": "Compliance",
  "/payroll/employer-statutory": "Employer Statutory",
  "/payroll/reports": "Reports",
  "/payroll/assist-admin": "Assist Admin",
  "/hr-admin/my-organization": "My Organization",
  "/hr-admin/subscription": "Subscription",
  "/organization-admin/organization": "My Organization",
  "/organization-admin/team": "Team Management",
  "/organization-admin/subscription": "Subscription & Billing",
  "/organization-admin/support-access": "Support Access",
  "/organization-admin/security-activity": "Security Activity",
  "/organization-admin/api-clients": "API Clients",
  "/organization-admin/data-governance": "Data Governance",
  "/organization-admin/scope": "Data Scope",
  "/account/security": "Account Security Settings",
};

function formatTitle(pageName, section) {
  if (!pageName) return "Zoiko Payroll";
  if (section) {
    return `${pageName} - ${section} | Zoiko Payroll`;
  }
  return `${pageName} | Zoiko Payroll`;
}

export function resolvePageTitle(pathname) {
  if (!pathname || pathname === "/") {
    return "Zoiko Payroll | Cloud Payroll & Statutory Compliance Platform";
  }

  // Exact public routes
  if (PUBLIC_TITLES[pathname]) {
    return formatTitle(PUBLIC_TITLES[pathname]);
  }

  // Exact or prefix payroll routes
  for (const [route, label] of Object.entries(PAYROLL_TITLES)) {
    if (pathname === route || pathname.startsWith(`${route}/`)) {
      return formatTitle(label);
    }
  }

  // Super Admin routes
  if (pathname.startsWith("/super-admin")) {
    const adminLabel = getSuperAdminPageLabel(pathname);
    return formatTitle(adminLabel, "Super Admin");
  }

  return "Zoiko Payroll";
}

export default function PageTitleUpdater() {
  const { pathname } = useLocation();

  useEffect(() => {
    document.title = resolvePageTitle(pathname);
  }, [pathname]);

  return null;
}

