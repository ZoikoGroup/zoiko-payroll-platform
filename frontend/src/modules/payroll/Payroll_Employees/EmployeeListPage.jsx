import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Users, UserPlus, Upload, Download, RefreshCw, List, Search, Filter, X, Send, Inbox } from "lucide-react";
import { useToast } from "../ToastContext";
import { getEmployees, bulkDeleteEmployees, getFormSubmissions, DEPARTMENTS, EMPLOYEE_STATUSES } from "../../../service/payrollService";
import { getCurrencyForJurisdiction } from "../../../utils/currency";
import { usePayrollSetup } from "../PayrollSetupContext";
import * as XLSX from "xlsx";
import EmployeeTable from "./EmployeeTable";
import EmployeeForm from "./EmployeeForm";
import EmployeeDetailPanel from "./EmployeeDetailPanel";
import EmployeeBulkImportModal from "./EmployeeBulkImportModal";
import EmployeeBulkEditPanel from "./EmployeeBulkEditPanel";
import SendTemplateBuilder from "./SendTemplateBuilder";
import SubmissionsReviewPanel from "./SubmissionsReviewPanel";

const tabs = [
  { id: "list",        label: "Employee List", icon: List },
  { id: "add",         label: "Add Employee",  icon: UserPlus },
];

export default function EmployeeListPage() {
  const { addToast } = useToast();
  const [activeTab, setActiveTab] = useState("list");
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [status, setStatus] = useState("");
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [deleting, setDeleting] = useState(false);
  const [pendingSubmissionCount, setPendingSubmissionCount] = useState(0);

  // Sourced from the shared, once-per-session PayrollSetupContext instead of
  // an independent fetchComplianceData() call on this page's own mount.
  const { company } = usePayrollSetup();
  const currencyInfo = useMemo(() => {
    if (!company) return null;
    return getCurrencyForJurisdiction(company.jurisdictionCountry) || getCurrencyForJurisdiction(company.jurisdiction_country);
  }, [company]);

  const refreshPendingSubmissionCount = useCallback(() => {
    getFormSubmissions("pending").then((rows) => setPendingSubmissionCount(rows.length)).catch(() => {});
  }, []);

  useEffect(() => {
    refreshPendingSubmissionCount();
  }, [refreshPendingSubmissionCount]);

  const loadEmployees = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await getEmployees({ search, department, status });
      setEmployees(data?.items || data || []);
    } catch (err) {
      setLoadError(err.message || "Could not load employees. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [search, department, status]);

  useEffect(() => {
    const timeout = setTimeout(loadEmployees, 300);
    return () => clearTimeout(timeout);
  }, [loadEmployees]);

  useEffect(() => {
    // Refetch on tab focus too — this page has no polling, so an employee
    // added/edited from another tab would otherwise stay stale here until a
    // manual reload.
    window.addEventListener("focus", loadEmployees);
    return () => window.removeEventListener("focus", loadEmployees);
  }, [loadEmployees]);

  function handleEmployeeUpdated(updated) {
    setEmployees((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    setSelectedEmployee(updated);
  }

  function handleEmployeeDeleted(id) {
    setEmployees((prev) => prev.filter((e) => e.id !== id));
    setSelectedEmployee(null);
  }

  function handleEmployeeCreated(created) {
    setEmployees((prev) => [created, ...prev]);
    setActiveTab("list");
  }

  function handleEmployeesBulkImported(createdList) {
    setEmployees((prev) => [...createdList, ...prev]);
    setActiveTab("list");
  }

  function handleEmployeesBulkUpdated(updatedList) {
    const updatedMap = new Map(updatedList.map((e) => [e.id, e]));
    setEmployees((prev) => prev.map((e) => updatedMap.get(e.id) || e));
    if (selectedEmployee && updatedMap.has(selectedEmployee.id)) {
      setSelectedEmployee(updatedMap.get(selectedEmployee.id));
    }
    setActiveTab("list");
  }

  function handleExportEmployees() {
    if (employees.length === 0) {
      addToast?.("No employees to export.", "error");
      return;
    }
    const rows = employees.map((emp) => ({
      "ID": emp.employeeCode || "",
      "Employee Name": emp.name || "",
      "Email": emp.email || "",
      "Phone": emp.phone || "",
      "Department": emp.department || "",
      "Designation": emp.designation || "",
      "Employment Type": emp.employmentType || "",
      "Status": emp.status || "",
      "Date of Joining (YYYY-MM-DD)": emp.dateOfJoining || "",
      "CTC": emp.ctc || "",
      "Basic": emp.basic || "",
      "HRA": emp.hra || "",
      "Bank Name": emp.bankName || "",
      "Bank Account Number": emp.bankAccountNumber || "",
      "IFSC Code": emp.ifscCode || "",
      "PAN Number": emp.panNumber || "",
      "UAN": emp.uan || "",
    }));
    const headers = Object.keys(rows[0]);
    const ws = XLSX.utils.json_to_sheet(rows, { header: headers });
    ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 18) }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Employees");
    const dateStamp = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(wb, `employees_export_${dateStamp}.xlsx`);
    addToast?.(`Exported ${rows.length} employee(s).`, "success");
  }

  async function handleBulkDelete() {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`Delete ${selectedIds.size} employee${selectedIds.size > 1 ? "s" : ""}?`)) return;
    setDeleting(true);
    try {
      const res = await bulkDeleteEmployees([...selectedIds]);
      const deletedSet = new Set(res.deleted || []);
      setEmployees((prev) => prev.filter((e) => !deletedSet.has(e.id)));
      setSelectedIds(new Set());
      if (selectedEmployee && deletedSet.has(selectedEmployee.id)) {
        setSelectedEmployee(null);
      }
      const deletedCount = (res.deleted || []).length;
      const failedCount = (res.failed || []).length;
      if (deletedCount > 0 && failedCount === 0) {
        addToast?.(`${deletedCount} employee${deletedCount > 1 ? "s" : ""} deleted.`, "success");
      } else if (deletedCount > 0 && failedCount > 0) {
        addToast?.(`${deletedCount} deleted, ${failedCount} skipped (${res.failed.map((f) => f.reason).join("; ")})`, "warning");
      } else if (failedCount > 0) {
        addToast?.(`Could not delete: ${res.failed.map((f) => f.reason).join("; ")}`, "error");
      }
    } catch (err) {
      addToast?.(err.message || "Delete failed.", "error");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6">
          <h1 className="text-[28px] font-extrabold tracking-tight text-[#1A1816] dark:text-[#F0EDE8]">Payroll Employees</h1>
          <p className="text-[13px] font-medium text-[#9E9690] mt-1">Manage employee records used in payroll processing.</p>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[16px] p-1.5 mb-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2 text-[13px] font-semibold rounded-[12px] transition-all duration-200 ${
                activeTab === t.id ? "bg-[#19C58A]/10 text-[#19C58A]" : "text-[#9E9690] hover:text-[#1A1816] dark:hover:text-[#F0EDE8] hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520]"
              }`}
            >
              <t.icon size={15} />
              {t.label}
            </button>
          ))}

          <div className="hidden sm:block h-6 w-px bg-[#E5E0D9] dark:bg-[#38312D] mx-1" />

          <button
            onClick={() => setActiveTab("bulk-import")}
            className="flex items-center gap-1.5 rounded-[12px] px-3.5 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#19C58A]"
          >
            <Upload size={15} />
            Import
          </button>
          <button
            onClick={() => setActiveTab("bulk-update")}
            className="flex items-center gap-1.5 rounded-[12px] px-3.5 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#9D7BF2]"
          >
            <RefreshCw size={15} />
            Update Employees
          </button>
          <button
            onClick={() => setActiveTab("send-template")}
            className="flex items-center gap-1.5 rounded-[12px] px-3.5 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#19C58A]"
          >
            <Send size={15} />
            Send Template
          </button>
          <button
            onClick={() => setActiveTab("review-submissions")}
            className="relative flex items-center gap-1.5 rounded-[12px] px-3.5 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#F8A60A]"
          >
            <Inbox size={15} />
            Review Submissions
            {pendingSubmissionCount > 0 && (
              <span className="absolute -top-1 -right-1 flex items-center justify-center min-w-[18px] h-[18px] rounded-full bg-[#F8A60A] text-white text-[10px] font-bold px-1">
                {pendingSubmissionCount}
              </span>
            )}
          </button>
          <button
            onClick={handleExportEmployees}
            className="flex items-center gap-1.5 rounded-[12px] px-3.5 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#35B6F5]"
          >
            <Download size={15} />
            Export
          </button>
        </div>

        {activeTab === "list" && (
          <>
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)] mb-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                  <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#9E9690]" />
                  <input
                    type="text"
                    placeholder="Search by name, ID, or email…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] pl-9 pr-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200 sm:max-w-xs"
                  />
                </div>
                <select
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
                >
                  <option value="">All departments</option>
                  {DEPARTMENTS.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
                >
                  <option value="">All statuses</option>
                  {EMPLOYEE_STATUSES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                {(search || department || status) && (
                  <button
                    onClick={() => { setSearch(""); setDepartment(""); setStatus(""); }}
                    className="text-[13px] font-semibold text-[#9E9690] hover:text-[#19C58A] transition-colors duration-200 px-2"
                  >
                    <X size={14} className="inline mr-1" />
                    Clear
                  </button>
                )}
              </div>
            </div>

            {loadError && (
              <div className="mb-4 rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">
                {loadError}
              </div>
            )}

            <div>
              {selectedIds.size > 0 && (
                <div className="mb-3 flex items-center gap-3 bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[12px] px-4 py-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
                  <span className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{selectedIds.size} selected</span>
                  <button
                    onClick={handleBulkDelete}
                    disabled={deleting}
                    className="bg-[#FF6E86] rounded-[12px] px-4 py-2 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#E55A72] shadow-[0_2px_8px_rgba(255,110,134,0.3)] disabled:opacity-60"
                  >
                    {deleting ? "Deleting…" : "Delete selected"}
                  </button>
                </div>
              )}
              <EmployeeTable
                employees={employees}
                loading={loading}
                onRowClick={setSelectedEmployee}
                selectedEmployeeId={selectedEmployee?.id}
                selectedIds={selectedIds}
                onSelectionChange={setSelectedIds}
                currencyInfo={currencyInfo}
              />
            </div>

            {selectedEmployee && (
              <EmployeeDetailPanel
                employee={selectedEmployee}
                onClose={() => setSelectedEmployee(null)}
                onUpdated={handleEmployeeUpdated}
                onDeleted={handleEmployeeDeleted}
                currencyInfo={currencyInfo}
              />
            )}
          </>
        )}

        {activeTab === "add" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h2 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-6">Add Employee</h2>
            <EmployeeForm onCancel={() => setActiveTab("list")} onSaved={handleEmployeeCreated} currencyInfo={currencyInfo} />
          </div>
        )}

        {activeTab === "bulk-import" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <EmployeeBulkImportModal
              onClose={() => setActiveTab("list")}
              onImported={handleEmployeesBulkImported}
            />
          </div>
        )}

        {activeTab === "bulk-update" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <EmployeeBulkEditPanel
              employees={employees}
              selectedIds={selectedIds}
              onClose={() => setActiveTab("list")}
              onSaved={handleEmployeesBulkUpdated}
              currencyInfo={currencyInfo}
            />
          </div>
        )}

        {activeTab === "send-template" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <SendTemplateBuilder
              employees={employees}
              selectedIds={selectedIds}
              onClose={() => setActiveTab("list")}
              onSent={refreshPendingSubmissionCount}
              currencyInfo={currencyInfo}
            />
          </div>
        )}

        {activeTab === "review-submissions" && (
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Review Submissions</h2>
              <button onClick={() => setActiveTab("list")} className="text-[13px] font-semibold text-[#9E9690] hover:text-[#19C58A] transition-colors duration-200">
                Back to list
              </button>
            </div>
            <SubmissionsReviewPanel
              onApplied={() => {
                loadEmployees();
                refreshPendingSubmissionCount();
              }}
            />
          </div>
        )}

      </div>
    </div>
  );
}
