import { useState, useEffect, useCallback, useMemo } from "react";
import { Check, Plus, List, FileText, Play, AlertTriangle } from "lucide-react";
import { useToast } from "../ToastContext";
import RunsTable from "./RunsTable";
import RunDetailPage from "./RunDetailPage";
import RunDetailPanel from "./RunDetailPanel";
import {
  fetchRuns,
  createRun,
  getEmployeesWithAttendance,
  getAttendanceRecords,
  previewPayrollRun,
  CALCULATION_MODE_LABELS,
} from "../../../service/payrollService";
import { getCurrencyForJurisdiction, formatCurrency } from "../../../utils/currency";
import { usePayrollSetup } from "../PayrollSetupContext";

const WIZARD_STEPS = [
  { id: 1, label: "Configure", icon: FileText },
  { id: 2, label: "Calculate", icon: List },
  { id: 3, label: "Approve", icon: Check },
  { id: 4, label: "Process", icon: Play },
];

function createCurrencyFormatter(currencyInfo) {
  if (!currencyInfo) {
    // Unrecognized jurisdiction — fall back to the shared currency util's
    // own default rather than hardcoding a specific country's currency.
    return (n) => (n == null ? "—" : formatCurrency(n));
  }
  return (n) => {
    if (n == null) return "—";
    return new Intl.NumberFormat(currencyInfo.locale || "en-US", {
      style: "currency",
      currency: currencyInfo.code,
      maximumFractionDigits: currencyInfo.decimalDigits ?? 2,
    }).format(n);
  };
}

export default function PayrollRunsPage() {
  const { addToast } = useToast();
  const [runs, setRuns] = useState([]);
  const [view, setView] = useState("list");
  const [wizardStep, setWizardStep] = useState(0);
  const [wizardConfig, setWizardConfig] = useState({
    periodStart: "",
    periodEnd: "",
    payDate: "",
    schedule: "Monthly",
  });
  const [employees, setEmployees] = useState([]);
  const [selectedEmployees, setSelectedEmployees] = useState([]);
  const [loadingEmployees, setLoadingEmployees] = useState(false);
  const [createdRunId, setCreatedRunId] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [selectedRun, setSelectedRun] = useState(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  // Sourced from the shared, once-per-session PayrollSetupContext instead of
  // this page's own independent fetchComplianceData()/getActivePolicy() calls.
  const { company, calculationMode: contextCalculationMode } = usePayrollSetup();
  const jurisdictionCountry = company?.jurisdictionCountry || "IN";
  const jurisdictionState = company?.jurisdictionState || "";
  // loadPreview() below can override this per-preview if the backend's
  // resolved mode differs from the context's — starts from the shared value.
  const [calculationModeOverride, setCalculationModeOverride] = useState(null);
  const calculationMode = calculationModeOverride ?? contextCalculationMode;

  const currencyInfo = useMemo(() => getCurrencyForJurisdiction(jurisdictionCountry), [jurisdictionCountry]);
  const fmtCurrency = useMemo(() => createCurrencyFormatter(currencyInfo), [currencyInfo]);

  const loadRuns = useCallback(async () => {
    const data = await fetchRuns();
    setRuns(data);
  }, []);

  useEffect(() => {
    loadRuns();
    // Refetch on tab focus too — this page has no polling, so a run
    // approved/created from another tab (or the Dashboard) would otherwise
    // stay stale here until a manual reload.
    window.addEventListener("focus", loadRuns);
    return () => window.removeEventListener("focus", loadRuns);
  }, [loadRuns]);

  const stats = useMemo(() => {
    const total = runs.length;
    const pending = runs.filter(
      (r) => r.status === "Draft" || r.status === "Review"
    ).length;
    const paid = runs.filter((r) => r.status === "Paid").length;
    return { total, pending, paid };
  }, [runs]);

  const totals = useMemo(() => {
    if (previewData?.totals) return previewData.totals;
    return { count: 0, totalGross: 0, totalTax: 0, totalContributions: 0, totalNet: 0 };
  }, [previewData]);

  const loadPreview = useCallback(async (empIds) => {
    setLoadingPreview(true);
    try {
      const data = await previewPayrollRun(
        empIds,
        jurisdictionCountry,
        wizardConfig.periodStart,
        wizardConfig.periodEnd,
        calculationMode,
      );
      setPreviewData(data);
      if (data?.calculationMode) setCalculationModeOverride(data.calculationMode);
    } catch {
      addToast?.("Failed to calculate payroll preview.", "error");
      setPreviewData(null);
    } finally {
      setLoadingPreview(false);
    }
  }, [jurisdictionCountry, wizardConfig.periodStart, wizardConfig.periodEnd, calculationMode, addToast]);

  const startWizard = async () => {
    // Validate active-employee eligibility immediately on click, before the
    // wizard (and its date-selection step) ever opens — previously this only
    // surfaced later, inside the Step 2 confirm modal, making it look like
    // the check was gated behind picking a payroll date.
    setLoadingEmployees(true);
    try {
      const empData = await getEmployeesWithAttendance({ status: "Active" });
      const list = Array.isArray(empData) ? empData : [];
      if (list.length === 0) {
        addToast?.("No active employees found. Add active employees before creating a payroll run.", "error");
        return;
      }
      setEmployees(list);
      setSelectedEmployees(list.map((e) => e.id));
      setView("wizard");
      setWizardStep(1);
    } catch {
      addToast?.("Failed to load payroll data.", "error");
    } finally {
      setLoadingEmployees(false);
    }
  };

  // Runs after the "Confirm Payroll Run" dialog is accepted — creates the run
  // and advances the wizard. Kept separate from nextStep() so confirming the
  // dialog can't re-enter nextStep()'s step-2 attendance-check branch (which
  // was reopening the same dialog a second time via a stale-state re-check).
  const createRunAndAdvance = async () => {
    try {
      const newRun = await createRun({
        periodStart: wizardConfig.periodStart,
        periodEnd: wizardConfig.periodEnd,
        payDate: wizardConfig.payDate,
        schedule: wizardConfig.schedule,
        employeeIds: selectedEmployees,
        totals,
        calculationMode,
      });
      const id = newRun?.id ?? newRun?._id ?? newRun?.runId;
      if (id) setCreatedRunId(id);
    } catch {
      addToast?.("Failed to create payroll run. Please try again.", "error");
      return;
    }
    if (wizardStep < 4) setWizardStep((s) => s + 1);
  };

  const nextStep = async () => {
    if (wizardStep === 2) {
      try {
        const attRecords = await getAttendanceRecords({
          startDate: wizardConfig.periodStart,
          endDate: wizardConfig.periodEnd,
        });
        const hasAttendance = Array.isArray(attRecords) && attRecords.length > 0;
        if (!hasAttendance) {
          addToast?.("No attendance records found for the selected period. Please record attendance before creating a payroll run.", "error");
          return;
        }
      } catch {
        addToast?.("Unable to verify attendance records. Please try again.", "error");
        return;
      }
      setShowConfirmModal(true);
      return;
    }
    if (wizardStep < 4) setWizardStep((s) => s + 1);
    if (wizardStep === 3) {
      addToast?.("Payroll run submitted successfully.", "success");
      setView("list");
      setWizardStep(0);
      setEmployees([]);
      setSelectedEmployees([]);
      setCreatedRunId(null);
      setPreviewData(null);
      loadRuns();
    }
  };

  const handleConfirmCreate = () => {
    setShowConfirmModal(false);
    createRunAndAdvance();
  };

  const prevStep = () => {
    if (wizardStep > 1) setWizardStep((s) => s - 1);
  };

  const recalculate = async () => {
    await loadPreview(selectedEmployees);
    addToast?.("Payroll data refreshed from server.", "success");
  };

  const handleRunChanged = async (runId) => {
    if (runId === "approve-refresh") {
      await loadRuns();
      return;
    }
    if (runId) {
      addToast?.("Payroll run deleted.", "success");
    }
    await loadRuns();
  };

  const toggleEmployee = (id) => {
    setSelectedEmployees((prev) =>
      prev.includes(id) ? prev.filter((eid) => eid !== id) : [...prev, id]
    );
  };

  const toggleAllEmployees = () => {
    if (selectedEmployees.length === employees.length) {
      setSelectedEmployees([]);
    } else {
      setSelectedEmployees(employees.map((e) => e.id));
    }
  };

  const isWizard = view === "wizard";

  return (
    <div className="flex h-full min-h-screen bg-background font-sans">
      <aside className="w-[200px] flex-shrink-0 flex flex-col border-r border-border bg-surface p-5">
        <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-5">
          Run Progress
        </p>
        <div className="flex-1 space-y-1">
          {WIZARD_STEPS.map((step, i) => {
            const completed = isWizard && wizardStep > step.id;
            const active = isWizard && wizardStep === step.id;
            const StepIcon = step.icon;
            return (
              <div key={step.id} className="flex items-start gap-2.5">
                <div className="flex flex-col items-center">
                    <div
                    className={`flex h-9 w-9 items-center justify-center rounded-full border-2 text-xs font-bold transition-all ${
                      completed
                        ? "border-primary bg-primary text-white"
                        : active
                        ? "border-primary bg-primary/10 text-primary ring-4 ring-primary/20"
                        : "border-border bg-surface text-foreground-muted"
                    }`}
                  >
                    {completed ? <Check size={14} /> : <StepIcon size={14} />}
                  </div>
                  {i < WIZARD_STEPS.length - 1 && (
                    <div className={`w-px h-5 my-0.5 ${completed || active ? "bg-primary" : "bg-border"}`} />
                  )}
                </div>
                <div className="pt-1.5">
                  <p className={`text-xs font-semibold ${completed || active ? "text-foreground" : "text-foreground-muted"}`}>
                    {step.label}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
        {jurisdictionCountry && (
          <div className="mt-4 rounded-[12px] bg-surface-muted border border-border p-3">
            <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1">Jurisdiction</p>
            <p className="text-xs font-bold text-foreground">{jurisdictionCountry}</p>
            {jurisdictionState && <p className="text-[10px] text-foreground-muted mt-0.5">{jurisdictionState}</p>}
          </div>
        )}
        <div className="mt-3 rounded-[12px] bg-surface-muted border border-border p-3">
          <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-1">Policy Mode</p>
          <p className={`text-xs font-bold ${calculationMode === "simple" ? "text-warning" : "text-primary"}`}>
            {CALCULATION_MODE_LABELS[calculationMode] || "Standard Payroll"}
          </p>
        </div>
      </aside>

      <div className="flex-1 flex flex-col overflow-auto">
        <header className="flex items-center justify-between px-8 py-5 border-b border-border bg-surface">
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-foreground">Payroll Runs</h1>
            <p className="text-[13px] text-foreground-muted mt-0.5">
              {isWizard ? `Processing payroll for ${jurisdictionCountry}` : "View and manage existing payroll runs"}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {!isWizard ? (
              <button
                onClick={startWizard}
                disabled={loadingEmployees}
                className="flex items-center gap-2 bg-primary rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-primary-hover shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Plus size={15} />
                {loadingEmployees ? "Loading…" : "Create New Run"}
              </button>
            ) : (
              <button
                onClick={() => { setView("list"); setWizardStep(0); setEmployees([]); setSelectedEmployees([]); setPreviewData(null); }}
                className="flex items-center gap-2 border border-border bg-surface-muted rounded-[12px] px-4 py-2 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-error hover:text-error"
              >
                Cancel
              </button>
            )}
          </div>
        </header>

        <div className="flex-1 p-5">
          {!isWizard ? (
            <div className="space-y-6">
              <div className="grid grid-cols-3 gap-4">
                {[
                  { label: "Total Runs", value: stats.total, accent: "text-foreground" },
                  { label: "Pending Review", value: stats.pending, accent: "text-warning" },
                  { label: "Paid", value: stats.paid, accent: "text-primary" },
                ].map((c) => (
                  <div key={c.label} className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{c.label}</p>
                    <p className={`mt-2 text-3xl font-extrabold ${c.accent}`}>{c.value}</p>
                  </div>
                ))}
              </div>
              <div className="bg-surface border border-border rounded-[18px] overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
                <div className="flex items-center justify-between p-5">
                  <h3 className="text-[15px] font-bold text-foreground">Payroll Runs</h3>
                </div>
                <div className="px-5 pb-5">
                  <RunsTable runs={runs} onSelect={setSelectedRun} onDelete={handleRunChanged} isWizardMode={false} fmtCurrency={fmtCurrency} />
                </div>
              </div>
            </div>
          ) : (
            <RunDetailPage
              step={wizardStep}
              config={wizardConfig}
              setConfig={setWizardConfig}
              employees={employees}
              selectedEmployees={selectedEmployees}
              toggleEmployee={toggleEmployee}
              toggleAllEmployees={toggleAllEmployees}
              setSelectedEmployees={setSelectedEmployees}
              previewData={previewData}
              totals={totals}
              jurisdictionCountry={jurisdictionCountry}
              calculationMode={calculationMode}
              runId={createdRunId}
              loading={loadingEmployees || loadingPreview}
              onNext={nextStep}
              onBack={prevStep}
              onRecalculate={recalculate}
              onLoadPreview={loadPreview}
              fmtCurrency={fmtCurrency}
            />
          )}
        </div>
      </div>

      {selectedRun && (
        <RunDetailPanel run={selectedRun} onClose={() => setSelectedRun(null)} fmtCurrency={fmtCurrency} />
      )}

      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-surface border border-border rounded-[18px] p-6 w-full max-w-md shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-warning/10 text-warning">
                <AlertTriangle size={20} />
              </div>
              <h3 className="text-lg font-bold text-foreground">Confirm Payroll Run</h3>
            </div>
            <p className="text-[13px] text-foreground-muted mb-4">
              Please ensure all <strong>attendance records</strong> have been recorded for the selected period before creating the payroll run. Missing attendance data may result in incorrect calculations.
            </p>
            <p className="text-[13px] text-foreground-muted mb-6">
              <strong>Note:</strong> Only <strong>Active Employees</strong> will be included in this payroll run.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 rounded-[12px] border border-border text-[13px] font-semibold text-foreground-muted hover:border-error hover:text-error transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmCreate}
                className="px-4 py-2 rounded-[12px] bg-primary text-[13px] font-bold text-white hover:bg-primary-hover transition-colors"
              >
                Confirm & Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
