import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import { ToastProvider, useToast } from "../../context/ToastContext";
import { PayrollSetupProvider } from "./PayrollSetupContext";

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
      <div className="mb-4 h-14 w-14 rounded-full bg-error/10 flex items-center justify-center">
        <span className="text-[28px] font-extrabold text-error">404</span>
      </div>
      <p className="text-[15px] font-bold text-foreground">Page not found</p>
      <p className="mt-1 text-[13px] text-foreground-muted">Redirecting to dashboard…</p>
    </div>
  );
}

function PayrollLayout({ children }) {
  const { toasts, removeToast } = useToast();

  return (
    <div className="flex h-full min-h-screen bg-background font-sans relative transition-colors duration-200">

      <div className="flex-1 overflow-auto">{children}</div>

      <div className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2 max-w-sm w-full">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`rounded-[18px] border px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.18)] flex items-center justify-between text-[13px] transition-all duration-200 ${
              toast.type === "success" ? "bg-success-light bg-success-light border-primary/30 dark:border-primary/40 text-primary-hover dark:text-primary"
              : toast.type === "error" ? "bg-error-light border-error/30 dark:border-error/40 text-error"
              : "bg-info-light bg-info-light border-info/30 dark:border-info/40 text-info"
            }`}
          >
            <span>{toast.message}</span>
            <button onClick={() => removeToast(toast.id)} className="ml-3 rounded-[10px] p-1 hover:bg-surface-muted text-foreground-muted transition-all duration-200">
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

  const page = pathname in pages ? pages[pathname] : <NotFoundRedirect />;

  return (
    <ToastProvider>
      <PayrollLayout>{page}</PayrollLayout>
    </ToastProvider>
  );
}

export default function ZoikoPayrollModule() {
  return (
    <PayrollSetupProvider>
      <PayrollModuleContent />
    </PayrollSetupProvider>
  );
}
