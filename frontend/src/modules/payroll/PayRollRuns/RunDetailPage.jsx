import { useState, useMemo, useEffect, useRef } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Calendar,
  Clock,
  ChevronDown,
  CheckCircle2,
  AlertTriangle,
  Info,
  RefreshCw,
  Loader2,
  Search,
} from "lucide-react";
import RunsTable from "./RunsTable";
import ApproveRunButton from "./ApproveRunButton";
import { CALCULATION_MODE_LABELS, getContributionColumns } from "../../../service/payrollService";

function Step1Configure({ config, setConfig, onNext, calculationMode, employees, selectedEmployees, toggleEmployee, setSelectedEmployees }) {
  const isSimple = calculationMode === "simple";
  const allSelected = employees.length > 0 && selectedEmployees.length === employees.length;
  const [employeeFilterMode, setEmployeeFilterMode] = useState(() => (allSelected ? "all" : "individual"));
  const [employeeSearch, setEmployeeSearch] = useState("");

  const handleFilterModeChange = (mode) => {
    setEmployeeFilterMode(mode);
    if (mode === "all") {
      setSelectedEmployees(employees.map((e) => e.id));
    } else {
      setSelectedEmployees([]);
      setEmployeeSearch("");
    }
  };

  const filteredEmployees = useMemo(() => {
    const q = employeeSearch.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter(
      (e) =>
        e.name?.toLowerCase().includes(q) ||
        e.employeeCode?.toLowerCase().includes(q) ||
        e.department?.toLowerCase().includes(q)
    );
  }, [employees, employeeSearch]);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-[15px] font-bold text-foreground">Configure Payroll Run</h2>
        <p className="text-[13px] text-foreground-muted mt-0.5">Set the pay period and verify parameters</p>
      </div>
      <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-bold ${
        isSimple ? "bg-warning/10 text-warning" : "bg-primary/10 text-primary"
      }`}>
        <span className={`h-1.5 w-1.5 rounded-full ${isSimple ? "bg-warning" : "bg-primary"}`} />
        Active: {CALCULATION_MODE_LABELS[calculationMode] || "Standard Payroll"}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "PAY PERIOD START", value: config.periodStart, key: "periodStart", icon: Calendar, type: "date" },
          { label: "PAY PERIOD END", value: config.periodEnd, key: "periodEnd", icon: Calendar, type: "date" },
          { label: "PAY DATE", value: config.payDate, key: "payDate", icon: Calendar, type: "date" },
          { label: "PAY SCHEDULE", value: config.schedule, key: "schedule", icon: Clock, type: "select", options: ["Monthly", "Bi-Weekly", "Weekly", "Semi-Monthly"] },
        ].map((field) => {
          const Icon = field.icon;
          return (
            <div key={field.key}>
              <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1 block">{field.label}</label>
              <div className="relative">
                <Icon size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground-muted" />
                {field.type === "select" ? (
                  <div className="relative">
                    <select value={field.value} onChange={(e) => setConfig((c) => ({ ...c, [field.key]: e.target.value }))} className="w-full rounded-[12px] border border-border bg-background pl-9 pr-8 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 appearance-none cursor-pointer">
                      {field.options.map((opt) => (<option key={opt} value={opt}>{opt}</option>))}
                    </select>
                    <ChevronDown size={13} className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-foreground-muted" />
                  </div>
                ) : (
                  <input type="date" value={field.value} onChange={(e) => setConfig((c) => ({ ...c, [field.key]: e.target.value }))} className="w-full rounded-[12px] border border-border bg-background pl-9 pr-3 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200" />
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="rounded-[12px] border border-border p-3">
        <label className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-2 block">Employee Filter</label>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground-muted" />
            <input
              type="text"
              placeholder="Search employees by name, code, or department…"
              value={employeeSearch}
              onChange={(e) => setEmployeeSearch(e.target.value)}
              disabled={employeeFilterMode === "all"}
              className="w-full rounded-[12px] border border-border bg-background pl-9 pr-3 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 disabled:opacity-50"
            />
          </div>
          <div className="relative sm:w-56">
            <select
              value={employeeFilterMode}
              onChange={(e) => handleFilterModeChange(e.target.value)}
              className="w-full rounded-[12px] border border-border bg-background pl-3 pr-8 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 appearance-none cursor-pointer"
            >
              <option value="all">All Employees</option>
              <option value="individual">Individual Employees</option>
            </select>
            <ChevronDown size={13} className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-foreground-muted" />
          </div>
        </div>

        {employeeFilterMode === "individual" && (
          <div className="mt-3 max-h-56 overflow-y-auto rounded-[10px] border border-border divide-y divide-border">
            {filteredEmployees.length === 0 ? (
              <p className="p-3 text-[12px] text-foreground-muted">No employees match your search.</p>
            ) : (
              filteredEmployees.map((emp) => (
                <label key={emp.id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-background">
                  <input
                    type="checkbox"
                    checked={selectedEmployees.includes(emp.id)}
                    onChange={() => toggleEmployee(emp.id)}
                    className="rounded border-border h-3.5 w-3.5 text-primary focus:ring-primary"
                  />
                  <span className="text-[13px] text-foreground">{emp.name}</span>
                  {emp.department && <span className="text-[11px] text-foreground-muted">· {emp.department}</span>}
                </label>
              ))
            )}
          </div>
        )}
        <p className="mt-2 text-[11px] text-foreground-muted">
          {employeeFilterMode === "all"
            ? `All ${employees.length} active employees will be included.`
            : `${selectedEmployees.length} of ${employees.length} employees selected.`}
        </p>
      </div>
      <div className="flex items-center justify-between rounded-[12px] border border-warning/20 bg-warning/5 p-3">
        <div className="flex items-center gap-3">
          <Info size={15} className="text-warning" />
          <div>
            <p className="text-xs font-semibold text-warning">Pre-run Validation</p>
            <p className="text-[11px] text-warning/70">
              {isSimple
                ? "Simple mode: Net = Gross minus LOP deductions. No PF/ESI/PT/TDS."
                : "Calculations will use the server-side tax engine (preview = persisted)."}
            </p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-0.5 text-[10px] font-bold text-primary">✓ Ready</span>
      </div>
      <div className="flex justify-end">
        <button
          onClick={onNext}
          disabled={selectedEmployees.length === 0}
          className="flex items-center gap-2 bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50 disabled:pointer-events-none"
        >
          Calculate Payroll <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}

function Step2Review({ employees, selectedEmployees, toggleEmployee, toggleAllEmployees, previewData, totals, loading, onNext, onBack, onRecalculate, onLoadPreview, fmtCurrency, calculationMode, jurisdictionCountry }) {
  const isSimple = calculationMode === "simple";
  const contributionColumns = useMemo(() => getContributionColumns(jurisdictionCountry), [jurisdictionCountry]);
  // Deliberately NOT filtered down to selectedEmployees — every employee the
  // preview was run for stays visible here so unchecking someone doesn't
  // make their row vanish (which would make the checkboxes impossible to
  // use: once unchecked, there'd be no row left to re-check). Totals reflect
  // whatever set the last preview/Recalculate ran for, same as before.
  const enrichedEmployees = useMemo(() => {
    if (previewData?.employees) {
      return previewData.employees.map((e) => ({
        id: e.employeeId,
        name: e.employeeName,
        department: e.department,
        attendanceStatus: e.attendanceStatus,
        monthlyGross: e.monthlyGross,
        monthlyTax: e.monthlyTax,
        monthlyContributions: e.monthlyContributions,
        monthlyNet: e.monthlyNet,
        taxSlabRate: e.taxSlabRate,
        payableDays: e.payableDays,
        totalWorkingDays: e.totalWorkingDays,
        prorated: e.prorated,
        contribComponents: contributionColumns.map((col) => ({
          id: col.id, label: col.label, value: e[col.previewField] ?? 0,
        })),
        monthlyExtra: 0,
      }));
    }
    return employees.map((emp) => ({
      ...emp,
      monthlyGross: Number(emp.ctc) / 12,
      monthlyTax: 0,
      monthlyContributions: 0,
      monthlyNet: Number(emp.ctc) / 12,
      taxSlabRate: "—",
      contribComponents: contributionColumns.map((col) => ({ id: col.id, label: col.label, value: 0 })),
      monthlyExtra: 0,
    }));
  }, [employees, previewData, contributionColumns]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[15px] font-bold text-foreground">Review Calculations</h2>
          <p className="text-[13px] text-foreground-muted mt-0.5">Server-side preview — what you approve is exactly what gets persisted</p>
        </div>
        {loading && <div className="flex items-center gap-2 text-[13px] text-foreground-muted"><Loader2 size={13} className="animate-spin text-info" /> Loading...</div>}
      </div>

      <div className={`grid gap-3 ${isSimple ? "grid-cols-3" : "grid-cols-5"}`}>
        {[
          { label: "Employees", value: totals.count, accent: "text-foreground" },
          { label: "Total Gross", value: fmtCurrency(totals.totalGross), accent: "text-primary" },
          ...(!isSimple ? [
            { label: "Total Taxes", value: fmtCurrency(totals.totalTax), accent: "text-error" },
            { label: "Total Contributions", value: fmtCurrency(totals.totalContributions), accent: "text-category-teal" },
          ] : []),
          { label: "Total Net Pay", value: fmtCurrency(totals.totalNet), accent: "text-info" },
        ].map((m) => (
          <div key={m.label} className="bg-surface border border-border rounded-[18px] p-3 text-center shadow-[0_1px_3px_rgba(0,0,0,0.04)] min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-foreground-muted truncate">{m.label}</p>
            <p className={`mt-1 text-base font-extrabold ${m.accent} min-w-0 whitespace-nowrap overflow-hidden text-ellipsis`}>{m.value}</p>
          </div>
        ))}
      </div>

      {enrichedEmployees.some((e) => e.prorated) && (
        <div className="rounded-[14px] bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40 px-4 py-3 flex items-start gap-2">
          <span className="text-amber-500 text-[13px] mt-0.5">⚠</span>
          <p className="text-[12px] text-amber-700 dark:text-amber-400">
            {enrichedEmployees.filter((e) => e.prorated).length} of {enrichedEmployees.length} employees have prorated pay
            this period due to recorded absence or unpaid leave — see the "Payable Days" column below.
          </p>
        </div>
      )}

      <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <RunsTable employees={enrichedEmployees} selectedEmployees={selectedEmployees} toggleEmployee={toggleEmployee} toggleAllEmployees={toggleAllEmployees} isWizardMode={true} fmtCurrency={fmtCurrency} calculationMode={calculationMode} jurisdictionCountry={jurisdictionCountry} />
      </div>

      <div className="flex items-center justify-between pt-1">
        <button onClick={onBack} className="flex items-center gap-2 border border-border bg-surface-muted rounded-[12px] px-4 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary">
          <ArrowLeft size={14} /> Back
        </button>
        <div className="flex items-center gap-2">
          <button onClick={onRecalculate} disabled={loading} className="flex items-center gap-2 border border-border bg-surface-muted rounded-[12px] px-4 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary disabled:opacity-50">
            <RefreshCw size={14} /> {loading ? "Refreshing…" : "Recalculate"}
          </button>
          <button onClick={onNext} disabled={loading || totals.count === 0} className="flex items-center gap-2 bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50">
            Approve & Continue <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

function Step3Approve({ config, totals, onBack, onNext, fmtCurrency, runId, calculationMode }) {
  const [confirmed, setConfirmed] = useState(false);
  const isSimple = calculationMode === "simple";
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-[15px] font-bold text-foreground">Final Approval</h2>
        <p className="text-[13px] text-foreground-muted mt-0.5">Authorize the payroll run for processing</p>
      </div>
      <div className="bg-surface border border-border rounded-[18px] divide-y divide-border/50 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        {[
          { label: "Pay Period", value: config.periodStart && config.periodEnd ? `${config.periodStart} – ${config.periodEnd}` : "—" },
          { label: "Pay Date", value: config.payDate || "—" },
          { label: "Calculation Mode", value: CALCULATION_MODE_LABELS[calculationMode] || "Standard Payroll" },
          { label: "Total Employees", value: String(totals.count) },
          { label: "Total Gross Pay", value: fmtCurrency(totals.totalGross), accent: "text-primary" },
          ...(!isSimple ? [
            { label: "Total Taxes", value: fmtCurrency(totals.totalTax), accent: "text-error" },
            { label: "Total Contributions", value: fmtCurrency(totals.totalContributions), accent: "text-category-teal" },
          ] : []),
          { label: "Total Net Pay", value: fmtCurrency(totals.totalNet), accent: "text-info" },
        ].map((row) => (
          <div key={row.label} className="flex items-center justify-between px-5 py-3">
            <span className="text-[13px] text-foreground-muted">{row.label}</span>
            <span className={`text-[13px] font-bold ${row.accent || "text-foreground"}`}>{row.value}</span>
          </div>
        ))}
      </div>
      <div className="rounded-[12px] border border-warning/20 bg-warning/5 p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0 text-warning" />
          <div>
            <p className="text-xs font-bold text-warning">Irreversible Action</p>
            <p className="text-[11px] text-warning/70 mt-0.5">Once submitted, this payroll run cannot be cancelled. Funds will be transferred to employee bank accounts on the scheduled pay date.</p>
          </div>
        </div>
      </div>
      <label className="flex items-start gap-3 cursor-pointer group">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-primary" />
        <span className="text-[13px] font-medium text-foreground-muted">I confirm all payroll calculations are accurate and authorize this disbursement</span>
      </label>
      <div className="flex items-center justify-between pt-1">
        <button onClick={onBack} className="flex items-center gap-2 border border-border bg-surface-muted rounded-[12px] px-4 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary">
          <ArrowLeft size={14} /> Back
        </button>
        <ApproveRunButton runId={runId} onApproved={() => onNext()} disabled={!confirmed || !runId} className={!confirmed ? "pointer-events-none" : ""} />
      </div>
    </div>
  );
}

export default function RunDetailPage({ step, config, setConfig, employees, selectedEmployees, toggleEmployee, toggleAllEmployees, setSelectedEmployees, previewData, totals, loading, onNext, onBack, onRecalculate, onLoadPreview, fmtCurrency, runId, calculationMode = "standard", jurisdictionCountry = "IN" }) {
  const previewAttemptedRef = useRef(false);
  useEffect(() => {
    if (step === 2 && selectedEmployees.length > 0 && !previewData && !loading && !previewAttemptedRef.current) {
      previewAttemptedRef.current = true;
      onLoadPreview(selectedEmployees);
    }
    if (step !== 2 || !selectedEmployees.length) previewAttemptedRef.current = false;
  }, [step, selectedEmployees, previewData, loading, onLoadPreview]);

  return (
    <div className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      {step === 1 && (
        <Step1Configure
          config={config}
          setConfig={setConfig}
          onNext={onNext}
          calculationMode={calculationMode}
          employees={employees}
          selectedEmployees={selectedEmployees}
          toggleEmployee={toggleEmployee}
          setSelectedEmployees={setSelectedEmployees}
        />
      )}
      {step === 2 && <Step2Review employees={employees} selectedEmployees={selectedEmployees} toggleEmployee={toggleEmployee} toggleAllEmployees={toggleAllEmployees} previewData={previewData} totals={totals} loading={loading} onNext={onNext} onBack={onBack} onRecalculate={onRecalculate} onLoadPreview={onLoadPreview} fmtCurrency={fmtCurrency} calculationMode={calculationMode} jurisdictionCountry={jurisdictionCountry} />}
      {step === 3 && <Step3Approve config={config} totals={totals} onBack={onBack} onNext={onNext} fmtCurrency={fmtCurrency} runId={runId} calculationMode={calculationMode} />}
      {step === 4 && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 mb-3">
            <CheckCircle2 size={28} className="text-primary" />
          </div>
          <h2 className="text-[15px] font-bold text-foreground">Payroll Run Complete</h2>
          <p className="text-[13px] text-foreground-muted mt-1">{totals.count} employees have been processed. Funds will be transferred on the scheduled pay date.</p>
        </div>
      )}
    </div>
  );
}