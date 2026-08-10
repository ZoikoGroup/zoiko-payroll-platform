import { useEffect } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { X, Moon, Sun, Lock, Loader2 } from "lucide-react";
import { ToastProvider, useToast } from "./ToastContext";
import { DarkModeProvider, useDarkMode } from "../../context/DarkModeContext";
import { PayrollSetupProvider, usePayrollSetup, PAYROLL_ONBOARDING_MESSAGE } from "./PayrollSetupContext";

import DashboardPage  from "./DashBoards/DashboardPage";
import EmployeeList   from "./Payroll_Employees/EmployeeListPage";
import PayrollRunsPage from "./PayRollRuns/PayrollRunsPage";
import PayslipsPage   from "./PaySlips/PayslipsPage";
import CompliancePage from "./Compliances/CompliancePage";
import AttendancePage from "./Attendance/AttendancePage";
import PayrollLeavesPage from "./Attendance/Payroll_Leaves";
import ReportsPage from "./Reports/ReportsPage";
import PayrollPolicyPage from "./PayrollPolicy/PayrollPolicyPage";

const pageMap = (navigate) => ({
  "/payroll":                <DashboardPage onNewPayrollRun={() => navigate("/payroll/payroll-runs")} />,
  "/payroll/employees":      <EmployeeList />,
  "/payroll/payroll-runs":   <PayrollRunsPage />,
  "/payroll/payslips":       <PayslipsPage />,
  "/payroll/compliances":    <CompliancePage />,
  "/payroll/attendance":     <AttendancePage />,
  "/payroll/leaves":         <PayrollLeavesPage />,
  "/payroll/reports":        <ReportsPage />,
  "/payroll/policy":         <PayrollPolicyPage />,
});

// Every Payroll sub-module except Policy/Compliance themselves and the
// dashboard — mandatory onboarding gate. Sub-modules are still reachable
// (the sidebar no longer disables/hides them) — this is purely a
// content-level swap, backed by PayrollSetupContext's once-per-session
// fetch rather than a re-check on every navigation.
const ONBOARDING_GATED_PATHS = new Set([
  "/payroll/employees", "/payroll/attendance", "/payroll/leaves",
  "/payroll/payroll-runs", "/payroll/payslips", "/payroll/reports",
]);

function useOnboardingGate(pathname) {
  const gated = ONBOARDING_GATED_PATHS.has(pathname);
  const { gateOk, loading } = usePayrollSetup();
  if (!gated) return "unlocked";
  if (loading) return "checking";
  return gateOk ? "unlocked" : "locked";
}

function OnboardingCheckSpinner() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <Loader2 size={24} className="animate-spin text-[#19C58A]" />
    </div>
  );
}

function OnboardingLockedPage() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center px-6">
      <div className="mb-4 h-14 w-14 rounded-full bg-[#F8A60A]/10 flex items-center justify-center">
        <Lock size={28} className="text-[#F8A60A]" />
      </div>
      <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Payroll setup required</p>
      <p className="mt-1 max-w-md text-[13px] text-[#9E9690]">{PAYROLL_ONBOARDING_MESSAGE}</p>
      <div className="mt-5 flex gap-3">
        <Link
          to="/payroll/policy"
          className="rounded-[12px] bg-[#19C58A] px-4 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A]"
        >
          Go to Payroll Policy
        </Link>
        <Link
          to="/payroll/compliances"
          className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] px-4 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
        >
          Go to Compliance
        </Link>
      </div>
    </div>
  );
}

function NotFoundRedirect() {
  const navigate = useNavigate();
  const { addToast } = useToast();

  useEffect(() => {
    addToast?.("Page not found. Redirecting to dashboard.", "error");
    const timer = setTimeout(() => navigate("/payroll", { replace: true }), 1500);
    return () => clearTimeout(timer);
  }, [navigate, addToast]);

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="mb-4 h-14 w-14 rounded-full bg-[#FF6E86]/10 flex items-center justify-center">
        <span className="text-[28px] font-extrabold text-[#FF6E86]">404</span>
      </div>
      <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Page not found</p>
      <p className="mt-1 text-[13px] text-[#9E9690]">Redirecting to dashboard…</p>
    </div>
  );
}

function DarkModeToggle() {
  const { isDark, toggle } = useDarkMode();
  return (
    <button
      onClick={toggle}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="fixed top-4 right-4 z-[9998] rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] p-2.5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all duration-200 hover:-translate-y-[1px] text-[#6B6560] dark:text-[#A69B93]"
    >
      {isDark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

function PayrollLayout({ children }) {
  const { toasts, removeToast } = useToast();

  return (
    <div className="flex h-full min-h-screen bg-[#F8F7F4] dark:bg-[#1A1816] font-sans relative transition-colors duration-200">

      <div className="flex-1 overflow-auto">{children}</div>

      <DarkModeToggle />

      <div className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2 max-w-sm w-full">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`rounded-[18px] border px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.18)] flex items-center justify-between text-[13px] transition-all duration-200 ${
              toast.type === "success" ? "bg-[#E3F9EF] dark:bg-[#123527] border-[#19C58A]/30 dark:border-[#19C58A]/40 text-[#15B07A] dark:text-[#19C58A]"
              : toast.type === "error" ? "bg-[#FFEAEF] dark:bg-[#3A1520] border-[#FF6E86]/30 dark:border-[#FF6E86]/40 text-[#E4506A] dark:text-[#FF6E86]"
              : "bg-[#E7F6FE] dark:bg-[#122C3A] border-[#35B6F5]/30 dark:border-[#35B6F5]/40 text-[#1E93CC] dark:text-[#35B6F5]"
            }`}
          >
            <span>{toast.message}</span>
            <button onClick={() => removeToast(toast.id)} className="ml-3 rounded-[10px] p-1 hover:bg-[#F0EDE8] dark:hover:bg-[#38312D] text-[#9E9690] dark:text-[#9E9690] transition-all duration-200">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function PayrollModuleContent() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const pages = pageMap(navigate);
  const gateState = useOnboardingGate(pathname);

  let page;
  if (!(pathname in pages)) {
    page = <NotFoundRedirect />;
  } else if (gateState === "checking") {
    page = <OnboardingCheckSpinner />;
  } else if (gateState === "locked") {
    page = <OnboardingLockedPage />;
  } else {
    page = pages[pathname];
  }

  return (
    <DarkModeProvider>
      <ToastProvider>
        <PayrollLayout>{page}</PayrollLayout>
      </ToastProvider>
    </DarkModeProvider>
  );
}

export default function ZoikoPayrollModule() {
  return (
    <PayrollSetupProvider>
      <PayrollModuleContent />
    </PayrollSetupProvider>
  );
}
