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
      <div className="mb-4 h-14 w-14 rounded-full bg-[#FF6E86]/10 flex items-center justify-center">
        <span className="text-[28px] font-extrabold text-[#FF6E86]">404</span>
      </div>
      <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Page not found</p>
      <p className="mt-1 text-[13px] text-[#9E9690]">Redirecting to dashboard…</p>
    </div>
  );
}

function PayrollLayout({ children }) {
  const { toasts, removeToast } = useToast();

  return (
    <div className="flex h-full min-h-screen bg-[#F8F7F4] dark:bg-[#1A1816] font-sans relative transition-colors duration-200">

      <div className="flex-1 overflow-auto">{children}</div>

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
