import { useState, useMemo, useEffect, useCallback } from "react";
import { FileText, Download, ChevronRight, CheckCircle2, AlertCircle, Clock, Receipt, Settings, Trash2, AlertTriangle, Filter } from "lucide-react";
import { useToast } from "../ToastContext";
import PayslipFilters from "./PayslipFilters";
import PayslipStub from "./PayslipStub";
import PayslipDownloadButton from "./PayslipDownloadButton";
import { getPayslips, getEmployees, deletePayslip } from "../../../service/payrollService";
import { formatCurrency } from "../../../utils/currency";
import { usePayrollSetup } from "../PayrollSetupContext";

const statusConfig = {
  Paid:     { color: "bg-[#19C58A]/10 text-[#19C58A]", icon: CheckCircle2 },
  Pending:  { color: "bg-[#F8A60A]/10 text-[#F8A60A]", icon: Clock       },
  Failed:   { color: "bg-[#FF6E86]/10 text-[#FF6E86]", icon: AlertCircle },
};

const tabs = [
  { id: "payslips",       label: "Payslips",              icon: FileText },
  { id: "payslip-detail", label: "Payslip Detail",        icon: Receipt },
  { id: "settings",       label: "Settings & Templates",  icon: Settings },
];

export default function PayslipsPage() {
  const { addToast } = useToast();
  const [activeTab, setActiveTab] = useState("payslips");
  const [search, setSearch] = useState("");
  const [periodFilter, setPeriodFilter] = useState("All Periods");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [selectedPayslip, setSelectedPayslip] = useState(null);
  const [selectAll, setSelectAll] = useState(false);
  const [selected, setSelected] = useState(new Set());

  const [payslips, setPayslips] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Sourced from the shared, once-per-session PayrollSetupContext instead of
  // this page's own independent getCompanyProfile() call.
  const { company: companyProfile, currencyCode } = usePayrollSetup();
  const [deletingId, setDeletingId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);

  const loadPayslips = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getPayslips({
        search: search || undefined,
        period: periodFilter !== "All Periods" ? periodFilter : undefined,
        employeeId: employeeFilter || undefined,
      });
      setPayslips(data);
    } catch {
      setError("Failed to load payslips. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [search, periodFilter, employeeFilter]);

  useEffect(() => {
    loadPayslips();
  }, [loadPayslips]);

  // Clear the current selection whenever the filters change — otherwise the
  // "Payslip Detail" tab's fallback (below) only ever picks a default once,
  // then keeps showing that same employee even after the employee/period
  // filter is changed to someone else.
  useEffect(() => {
    setSelectedPayslip(null);
  }, [employeeFilter, periodFilter, search]);

  useEffect(() => {
    getEmployees().then(setEmployees).catch(() => {});
  }, []);

  const periods = useMemo(
    () => ["All Periods", ...Array.from(new Set(payslips.map((p) => p.period))).filter(Boolean)],
    [payslips]
  );

  const handleSelectAll = () => {
    if (selectAll) {
      setSelected(new Set());
    } else {
      setSelected(new Set(payslips.map((p) => p.id)));
    }
    setSelectAll(!selectAll);
  };

  const handleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const stats = useMemo(() => ({
    total: payslips.length,
    paid: payslips.filter((p) => p.status === "Paid").length,
    pending: payslips.filter((p) => p.status === "Pending").length,
  }), [payslips]);

  const handleDeletePayslip = async (payslipId) => {
    setDeletingId(payslipId);
    try {
      await deletePayslip(payslipId);
      addToast?.("Payslip deleted successfully.", "success");
      setSelected((prev) => { const n = new Set(prev); n.delete(payslipId); return n; });
      await loadPayslips();
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || "Failed to delete payslip.";
      addToast?.(msg, "error");
    } finally {
      setDeletingId(null);
      setConfirmDelete(null);
    }
  };

  const handleBulkDelete = async () => {
    const toDelete = payslips.filter((p) => selected.has(p.id));
    setBulkDeleting(true);
    let failed = 0;
    for (const p of toDelete) {
      try {
        await deletePayslip(p.id);
      } catch {
        failed++;
      }
    }
    setBulkDeleting(false);
    setConfirmDelete(null);
    if (failed > 0) {
      addToast?.(`${toDelete.length - failed} deleted, ${failed} failed.`, failed === toDelete.length ? "error" : "success");
    } else {
      addToast?.(`${toDelete.length} payslips deleted.`, "success");
    }
    setSelected(new Set());
    await loadPayslips();
  };

  return (
    <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8 space-y-5">
      <div className="rounded-[18px] bg-[#19C58A]/5 border border-[#19C58A]/15 p-7">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[12px] bg-[#19C58A] flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
            <FileText size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-[#1A1816] dark:text-[#F0EDE8]">Payslips</h1>
            <p className="text-[13px] font-medium text-[#9E9690]">{stats.total} payslips · {stats.paid} distributed</p>
          </div>
        </div>
      </div>

      <div className="flex gap-1 bg-[#F0EDE8] dark:bg-[#38312D] rounded-[14px] p-1 w-fit flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => {
              if (t.id === "payslip-detail" && !selectedPayslip && payslips.length > 0) {
                setSelectedPayslip(payslips[0]);
              }
              setActiveTab(t.id);
            }}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-[12px] text-[13px] font-medium transition-all duration-200 ${
              activeTab === t.id ? "bg-white dark:bg-[#221D1A] text-[#19C58A] shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-[#9E9690] hover:text-[#6B6560]"
            }`}
          >
            <t.icon size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "payslips" && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-4 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <div className="p-2.5 rounded-[12px] bg-[#19C58A]/10">
                <FileText className="w-5 h-5 text-[#19C58A]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{stats.total}</p>
                <p className="text-[13px] text-[#9E9690]">Total Payslips</p>
              </div>
            </div>
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-4 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <div className="p-2.5 rounded-[12px] bg-[#19C58A]/10">
                <CheckCircle2 className="w-5 h-5 text-[#19C58A]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{stats.paid}</p>
                <p className="text-[13px] text-[#9E9690]">Distributed</p>
              </div>
            </div>
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-4 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <div className="p-2.5 rounded-[12px] bg-[#F8A60A]/10">
                <Clock className="w-5 h-5 text-[#F8A60A]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{stats.pending}</p>
                <p className="text-[13px] text-[#9E9690]">Pending</p>
              </div>
            </div>
          </div>

          {selected.size > 0 && (
            <div className="flex items-center gap-3 px-4 py-3 bg-[#19C58A]/5 border border-[#19C58A]/20 rounded-[18px] text-[13px]">
              <span className="font-semibold text-[#19C58A]">{selected.size} selected</span>
              <span className="text-[12px] text-[#9E9690]">Go to Settings &amp; Templates to delete the selected payslip(s).</span>
              <button onClick={() => setSelected(new Set())} className="text-[12px] text-[#9E9690] hover:text-[#FF6E86] font-medium ml-auto">
                Clear Selection
              </button>
            </div>
          )}

          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
            {loading ? (
              <div className="p-6 space-y-4">
                {[1,2,3].map((i) => (
                  <div key={i} className="flex items-center gap-4 animate-pulse">
                    <div className="w-4 h-4 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                    <div className="w-16 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                    <div className="w-32 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                    <div className="w-24 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                    <div className="w-20 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                    <div className="flex-1" />
                    <div className="w-16 h-5 rounded-full bg-[#F0EDE8] dark:bg-[#38312D]" />
                  </div>
                ))}
              </div>
            ) : error ? (
              <div className="text-center py-12 space-y-3">
                <p className="text-[13px] text-[#FF6E86]">{error}</p>
                <button onClick={loadPayslips} className="text-[13px] font-bold text-[#19C58A] hover:text-[#15B07A] transition-all duration-200">
                  Retry
                </button>
              </div>
            ) : (
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
                    <th className="px-4 py-3.5 w-10">
                      <input type="checkbox" checked={selectAll} onChange={handleSelectAll} className="w-4 h-4 rounded border-[#E5E0D9] dark:border-[#38312D] text-[#19C58A]" />
                    </th>
                    {["Payslip ID","Employee","Department","Pay Period","Pay Date","Net Pay","Status",""].map((h) => (
                      <th key={h} className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E5E0D9]/50 dark:divide-[#38312D]/50">
                  {payslips.map((p) => {
                    const sc = statusConfig[p.status] || statusConfig.Paid;
                    const Icon = sc.icon;
                    return (
                      <tr key={p.id} className="hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors duration-150">
                        <td className="px-4 py-4">
                          <input
                            type="checkbox"
                            checked={selected.has(p.id)}
                            onChange={() => handleSelect(p.id)}
                            className="w-4 h-4 rounded border-[#E5E0D9] dark:border-[#38312D] text-[#19C58A]"
                          />
                        </td>
                        <td className="px-5 py-4 font-mono text-[12px] text-[#9E9690] font-semibold">{p.id}</td>
                        <td className="px-5 py-4">
                          <button onClick={() => setSelectedPayslip(p)} className="font-semibold text-[#1A1816] dark:text-[#F0EDE8] hover:text-[#19C58A] text-left transition-colors duration-200">
                            {p.employee}
                          </button>
                        </td>
                        <td className="px-5 py-4 text-[#6B6560] dark:text-[#A69B93]">{p.department}</td>
                        <td className="px-5 py-4 text-[#6B6560] dark:text-[#A69B93]">{p.period}</td>
                        <td className="px-5 py-4 text-[#6B6560] dark:text-[#A69B93]">{p.payDate}</td>
                        <td className="px-5 py-4 font-bold text-[#1A1816] dark:text-[#F0EDE8]">{formatCurrency(p.netPay || 0, currencyCode)}</td>
                        <td className="px-5 py-4">
                          <span className={`flex items-center gap-1.5 w-fit rounded-full px-3 py-1 text-[11px] font-bold ${sc.color}`}>
                            <Icon size={11} /> {p.status}
                          </span>
                        </td>
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-1">
                            <button onClick={() => { setSelectedPayslip(p); setActiveTab("payslip-detail"); }} className="p-1.5 rounded-[10px] text-[#9E9690] hover:text-[#1A1816] dark:hover:text-[#F0EDE8] hover:bg-[#F0EDE8] dark:hover:bg-[#38312D] transition-all duration-150">
                              <ChevronRight size={15} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            {!loading && !error && payslips.length === 0 && (
              <div className="text-center py-16">
                <FileText size={40} className="mx-auto mb-3 text-[#9E9690]/40" />
                <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">No payslips match your filters</p>
                <p className="text-[13px] text-[#9E9690] mt-1">Try adjusting your search or filters</p>
              </div>
            )}
          </div>

          {selectedPayslip && activeTab !== "payslip-detail" && (
            <PayslipStub payslip={selectedPayslip} onClose={() => setSelectedPayslip(null)} currencyCode={currencyCode} company={companyProfile} />
          )}
        </>
      )}

      {activeTab === "payslip-detail" && (
        <>
          {selectedPayslip ? (
            <PayslipStub payslip={selectedPayslip} onClose={() => { setSelectedPayslip(null); setActiveTab("payslips"); }} currencyCode={currencyCode} company={companyProfile} />
          ) : (
            <div className="text-center py-16">
              <Receipt size={40} className="mx-auto mb-3 text-[#9E9690]/40" />
              <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Select a payslip from the Payslip Detail tab to view details</p>
            </div>
          )}
        </>
      )}

      {activeTab === "settings" && (
        <>
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] mb-5">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2.5 rounded-[12px] bg-[#35B6F5]/10">
                <Filter className="w-5 h-5 text-[#35B6F5]" />
              </div>
              <div>
                <h2 className="text-[16px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Filter Payslips</h2>
                <p className="text-[13px] text-[#9E9690]">Narrow down the payslip list below by search, period, or employee.</p>
              </div>
            </div>
            <PayslipFilters
              search={search} onSearchChange={setSearch}
              periodFilter={periodFilter} onPeriodChange={setPeriodFilter}
              employeeFilter={employeeFilter} onEmployeeChange={setEmployeeFilter}
              employees={employees}
              periods={periods}
            />
          </div>

          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2.5 rounded-[12px] bg-[#FF6E86]/10">
                <Trash2 className="w-5 h-5 text-[#FF6E86]" />
              </div>
              <div>
                <h2 className="text-[16px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Delete Payslips</h2>
                <p className="text-[13px] text-[#9E9690]">Only payslips in Draft payroll runs can be deleted. Deleted payslips cannot be recovered.</p>
              </div>
            </div>

            {confirmDelete === "bulk" ? (
              <div className="flex items-center gap-3 px-4 py-3 bg-[#FF6E86]/5 border border-[#FF6E86]/20 rounded-[14px] text-[13px] mb-4">
                <AlertTriangle size={16} className="text-[#FF6E86] shrink-0" />
                <span className="text-[#6B6560] dark:text-[#A69B93]">Delete <strong className="text-[#FF6E86]">{selected.size} payslips</strong>? This action cannot be undone.</span>
                <button
                  onClick={handleBulkDelete}
                  disabled={bulkDeleting}
                  className="flex items-center gap-1.5 rounded-[10px] bg-[#FF6E86] text-white px-4 py-1.5 text-[12px] font-bold transition-all duration-200 hover:bg-[#E55A72] shadow-[0_2px_8px_rgba(255,110,134,0.3)] disabled:opacity-50"
                >
                  <Trash2 size={12} /> {bulkDeleting ? "Deleting..." : "Confirm Delete"}
                </button>
                <button onClick={() => setConfirmDelete(null)} className="text-[12px] text-[#9E9690] hover:text-[#6B6560] font-medium ml-auto">
                  Cancel
                </button>
              </div>
            ) : (
              selected.size > 0 && (
                <button
                  onClick={() => setConfirmDelete("bulk")}
                  className="flex items-center gap-1.5 rounded-[12px] bg-[#FF6E86] text-white px-4 py-1.5 text-[12px] font-bold transition-all duration-200 hover:bg-[#E55A72] shadow-[0_2px_8px_rgba(255,110,134,0.3)] hover:shadow-[0_4px_14px_rgba(255,110,134,0.4)] mb-4"
                >
                  <Trash2 size={12} /> Delete Selected ({selected.size})
                </button>
              )
            )}

            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
              {loading ? (
                <div className="p-6 space-y-4">
                  {[1,2,3].map((i) => (
                    <div key={i} className="flex items-center gap-4 animate-pulse">
                      <div className="w-4 h-4 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                      <div className="w-16 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                      <div className="w-32 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                      <div className="w-24 h-3 rounded bg-[#F0EDE8] dark:bg-[#38312D]" />
                      <div className="flex-1" />
                      <div className="w-20 h-5 rounded-full bg-[#F0EDE8] dark:bg-[#38312D]" />
                    </div>
                  ))}
                </div>
              ) : payslips.length === 0 ? (
                <div className="text-center py-16">
                  <FileText size={40} className="mx-auto mb-3 text-[#9E9690]/40" />
                  <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">No payslips found</p>
                  <p className="text-[13px] text-[#9E9690] mt-1">There are no payslips to manage.</p>
                </div>
              ) : (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
                      <th className="px-4 py-3.5 w-10">
                        <input type="checkbox" checked={selectAll} onChange={handleSelectAll} className="w-4 h-4 rounded border-[#E5E0D9] dark:border-[#38312D] text-[#19C58A]" />
                      </th>
                      {["Payslip ID","Employee","Department","Pay Period","Net Pay","Status","Action"].map((h) => (
                        <th key={h} className="px-5 py-3.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E5E0D9]/50 dark:divide-[#38312D]/50">
                    {payslips.map((p) => {
                      const sc = statusConfig[p.status] || statusConfig.Paid;
                      const Icon = sc.icon;
                      const isDeleting = deletingId === p.id;
                      return (
                        <tr key={p.id} className={`transition-colors duration-150 ${isDeleting ? "opacity-50" : "hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520]"}`}>
                          <td className="px-4 py-4">
                            <input
                              type="checkbox"
                              checked={selected.has(p.id)}
                              onChange={() => handleSelect(p.id)}
                              className="w-4 h-4 rounded border-[#E5E0D9] dark:border-[#38312D] text-[#19C58A]"
                            />
                          </td>
                          <td className="px-5 py-4 font-mono text-[12px] text-[#9E9690] font-semibold">{p.id}</td>
                          <td className="px-5 py-4 font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{p.employee}</td>
                          <td className="px-5 py-4 text-[#6B6560] dark:text-[#A69B93]">{p.department}</td>
                          <td className="px-5 py-4 text-[#6B6560] dark:text-[#A69B93]">{p.period}</td>
                          <td className="px-5 py-4 font-bold text-[#1A1816] dark:text-[#F0EDE8]">{formatCurrency(p.netPay || 0, currencyCode)}</td>
                          <td className="px-5 py-4">
                            <span className={`flex items-center gap-1.5 w-fit rounded-full px-3 py-1 text-[11px] font-bold ${sc.color}`}>
                              <Icon size={11} /> {p.status}
                            </span>
                          </td>
                          <td className="px-5 py-4">
                            {confirmDelete === p.id ? (
                              <div className="flex items-center gap-1.5">
                                <button
                                  onClick={() => handleDeletePayslip(p.id)}
                                  disabled={isDeleting}
                                  className="flex items-center gap-1 rounded-[8px] bg-[#FF6E86] text-white px-3 py-1 text-[11px] font-bold transition-all duration-200 hover:bg-[#E55A72] disabled:opacity-50"
                                >
                                  <Trash2 size={10} /> {isDeleting ? "..." : "Yes"}
                                </button>
                                <button onClick={() => setConfirmDelete(null)} className="rounded-[8px] bg-[#F0EDE8] dark:bg-[#38312D] text-[#9E9690] px-3 py-1 text-[11px] font-bold hover:text-[#6B6560] transition-all duration-200">
                                  No
                                </button>
                              </div>
                            ) : (
                              <div className="flex items-center gap-1">
                                <PayslipDownloadButton payslip={p} iconOnly />
                                <button
                                  onClick={() => setConfirmDelete(p.id)}
                                  disabled={isDeleting}
                                  title="Delete payslip"
                                  className="rounded-[10px] p-1.5 text-[#9E9690] hover:text-[#FF6E86] hover:bg-[#FF6E86]/10 transition-colors disabled:opacity-50"
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}


    </div>
  );
}