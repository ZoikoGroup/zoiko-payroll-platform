import { useEffect, useState } from "react";
import { BarChart3, CalendarClock, FileWarning, Users } from "lucide-react";
import { getGermanyPayrollSummaryReport } from "../../../../service/payrollService";
import { describeLoadError } from "../../../../service/errorClassification";
import { formatCurrency } from "../../../../utils/currency";

// Phase 8BI — Germany statutory payroll summary, surfaced in the
// Compliance -> Germany workspace as a first-class tab. The data comes
// exclusively from get_germany_payroll_summary_report, which aggregates
// REAL, already-persisted Germany PayslipItem/PayrollRun rows for the
// current organization:
//   - CALCULATED  = persisted PENDING/PAID payslip (real money, real sums)
//   - BLOCKED     = persisted FAILED payslip (zero contribution to money
//                   totals, reason surfaced, never a fabricated figure)
//   - UNAVAILABLE = a figure this codebase currently has no persisted path
//                   to compute for the affected rows (e.g. any payslip
//                   still using the pre-Phase-8BR PayslipItem.soli
//                   default) — shown as such, never as a fabricated €0.00.
//                   Phase 8BR: Solidaritätszuschlag itself IS now computed
//                   (engine/germany_internal_tax.py, INTERNAL_FUNCTIONAL_
//                   REFERENCE — not BMF-certified) and persisted for every
//                   Regular/Midijob payslip calculated from this phase on.
function StatCard({ label, value, sub, tone = "default" }) {
  const toneClass = tone === "good" ? "text-green-600" : tone === "warn" ? "text-warning" : "text-foreground";
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-xs font-semibold text-foreground-muted">{label}</p>
      <p className={`mt-1 text-xl font-bold ${toneClass}`}>{value}</p>
      {sub ? <p className="mt-0.5 text-xs text-foreground-disabled">{sub}</p> : null}
    </div>
  );
}

function StatusChip({ status }) {
  if (status === "CALCULATED") {
    return <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-700">CALCULATED</span>;
  }
  if (status === "BLOCKED") {
    return <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700">BLOCKED</span>;
  }
  // Phase 8BU: some PARTIAL payslip(s) exist for this figure — the amount
  // shown alongside this chip is still real, just excludes those payslips'
  // forced-zero placeholder (see excludedPartialCount).
  if (status === "PARTIAL") {
    return <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700">PARTIAL</span>;
  }
  return <span className="inline-flex items-center rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-semibold text-foreground-muted">UNAVAILABLE</span>;
}

export default function GermanyPayrollSummaryTab() {
  const [state, setState] = useState({ loading: true, report: null, error: null });
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [appliedStart, setAppliedStart] = useState("");
  const [appliedEnd, setAppliedEnd] = useState("");

  const load = (start, end) => {
    setState({ loading: true, report: null, error: null });
    const params = {};
    if (start) params.periodStart = start;
    if (end) params.periodEnd = end;
    getGermanyPayrollSummaryReport(params)
      .then((report) => setState({ loading: false, report, error: null }))
      .catch((err) => setState({ loading: false, report: null, error: describeLoadError(err) }));
  };

  useEffect(() => {
    load("", "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyPeriod = () => {
    setAppliedStart(periodStart);
    setAppliedEnd(periodEnd);
    load(periodStart, periodEnd);
  };

  const clearPeriod = () => {
    setPeriodStart("");
    setPeriodEnd("");
    setAppliedStart("");
    setAppliedEnd("");
    load("", "");
  };

  if (state.loading) {
    return (
      <div className="rounded-xl border border-border bg-surface p-5 text-sm text-foreground-muted">
        Loading Germany payroll summary…
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="rounded-xl border border-border bg-surface p-5 text-sm">
        <p className="font-bold text-foreground">
          {state.error.schemaUnavailable
            ? "Summary not available — required migration pending"
            : state.error.networkError
              ? "Backend unreachable"
              : "Failed to load the Germany payroll summary"}
        </p>
        <p className="mt-1 text-xs text-foreground-muted">{state.error.message || ""}</p>
      </div>
    );
  }

  const report = state.report;
  const counts = report.employeeCounts || {};
  const byStatus = counts.byStatus || {};
  const byClassification = counts.byClassification || {};
  const statutory = report.statutoryContributions || {};
  const pension = statutory.pensionInsurance || {};
  const siCombined = statutory.socialInsuranceCombined || {};
  const churchTax = statutory.churchTax || {};
  const solidarity = statutory.solidaritySurcharge || {};
  const wageTax = report.wageTaxStatus || {};
  const blockedEmployees = report.blockedEmployees || [];
  const partialEmployees = report.partialEmployees || [];
  const payrollRuns = report.payrollRuns || [];
  const calculationModes = report.calculationModes || {};
  const usesInternalReference = Object.keys(calculationModes).some((mode) => mode.startsWith("INTERNAL_FUNCTIONAL_REFERENCE"));

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border bg-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold text-foreground">Germany statutory payroll summary</h3>
            <p className="mt-0.5 text-xs text-foreground-muted">
              Aggregated from real persisted payslips for this organization. CALCULATED figures are real sums;
              BLOCKED payslips contribute nothing to any money total and list their reason; figures with no
              persisted field at all are shown as UNAVAILABLE — never fabricated.
              {appliedStart || appliedEnd ? (
                <span className="font-semibold">
                  {" "}Period: {appliedStart || "…"} → {appliedEnd || "…"}
                </span>
              ) : (
                <span className="font-semibold"> All-time (no period filter).</span>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={periodStart}
              onChange={(e) => setPeriodStart(e.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-foreground"
              aria-label="Period start"
            />
            <span className="text-xs text-foreground-disabled">→</span>
            <input
              type="date"
              value={periodEnd}
              onChange={(e) => setPeriodEnd(e.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-foreground"
              aria-label="Period end"
            />
            <button
              onClick={applyPeriod}
              className="rounded-md bg-primary px-3 py-1 text-xs font-semibold text-white transition-colors hover:bg-primary/90"
            >
              Apply
            </button>
            <button
              onClick={clearPeriod}
              className="rounded-md border border-border px-3 py-1 text-xs font-semibold text-foreground-muted transition-colors hover:text-foreground"
            >
              Clear
            </button>
          </div>
        </div>
      </div>

      {usesInternalReference ? (
        <div className="rounded-xl border border-warning/40 bg-warning/5 p-3 text-xs text-foreground">
          <p className="font-semibold">
            Wage tax calculation mode: INTERNAL FUNCTIONAL REFERENCE ({"§32a/§39b EStG"})
          </p>
          <p className="mt-0.5 text-foreground-muted">
            These wage-tax/Soli figures are computed by Zoiko Payroll's internal statutory-reference calculator
            (real German tax law formulas, not fabricated) because no certified BMF Programmablaufplan (PAP) asset
            is published. They are <span className="font-semibold">not BMF-certified</span> — do not represent them
            as official government-certified output.
          </p>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard
          label="Employees"
          value={counts.total ?? 0}
          sub={`${byStatus.CALCULATED ?? 0} calculated · ${byStatus.BLOCKED ?? 0} blocked${byStatus.PARTIAL ? ` · ${byStatus.PARTIAL} partial` : ""}`}
          icon={<Users size={14} />}
        />
        <StatCard label="Gross Pay" value={formatCurrency(report.grossPay?.amount, "EUR")} sub="CALCULATED" tone="good" />
        <StatCard
          label="Net Pay"
          value={formatCurrency(report.netPay?.amount, "EUR")}
          sub={report.netPay?.status === "PARTIAL"
            ? `Excludes ${report.netPay.excludedPartialCount} partial payslip(s)`
            : "CALCULATED"}
          tone={report.netPay?.status === "PARTIAL" ? "warn" : "good"}
        />
        <StatCard
          label="Church Tax"
          value={formatCurrency(churchTax.amount, "EUR")}
          sub={churchTax.status === "CALCULATED" ? "CALCULATED" : churchTax.status || "—"}
        />
        <StatCard
          label="PAP-blocked payslips"
          value={report.papBlockedPayrollCount ?? 0}
          sub="GERMANY_PAP_NOT_AVAILABLE"
          tone={report.papBlockedPayrollCount ? "warn" : "default"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <h4 className="mb-3 flex items-center gap-1.5 text-sm font-bold text-foreground">
            <BarChart3 size={14} /> Statutory contributions
          </h4>
          <table className="w-full text-xs">
            <tbody>
              {[
                {
                  label: "Pension insurance (RV)",
                  status: pension.status,
                  employee: pension.employeeAmount,
                  employer: pension.employerAmount,
                },
                {
                  label: "Social insurance combined (ALV + GKV + PV)",
                  status: siCombined.status,
                  employee: siCombined.employeeAmount,
                  employer: siCombined.employerAmount,
                },
                {
                  label: "Church tax (KiSt)", status: churchTax.status, total: churchTax.amount,
                  excludedPartialCount: churchTax.excludedPartialCount,
                },
                {
                  label: "Solidarity surcharge (Soli)", status: solidarity.status, total: solidarity.amount,
                  reason: solidarity.reason, excludedPartialCount: solidarity.excludedPartialCount,
                },
              ].map((row) => (
                <tr key={row.label} className="border-b border-border/70 last:border-0">
                  <td className="py-2 pr-2 align-top text-foreground-muted">{row.label}</td>
                  <td className="py-2 text-right align-top">
                    {/* Phase 8BU: a PARTIAL row still has a real amount
                        (whatever wasn't excluded) — show it alongside the
                        chip instead of hiding it behind an "unavailable"
                        state, which would bury a genuine, real figure. */}
                    {row.status === "CALCULATED" || row.status === "PARTIAL" ? (
                      <div className="space-y-0.5">
                        {row.total !== undefined ? (
                          <p className="font-semibold text-foreground">{formatCurrency(row.total, "EUR")}</p>
                        ) : (
                          <p className="text-foreground">
                            Employee {formatCurrency(row.employee, "EUR")} · Employer {formatCurrency(row.employer, "EUR")}
                          </p>
                        )}
                        {row.status === "PARTIAL" ? (
                          <div className="flex justify-end">
                            <StatusChip status="PARTIAL" />
                          </div>
                        ) : null}
                        {row.status === "PARTIAL" && row.excludedPartialCount ? (
                          <p className="text-[11px] text-foreground-disabled">
                            Excludes {row.excludedPartialCount} partial payslip(s) where this is unavailable.
                          </p>
                        ) : null}
                      </div>
                    ) : (
                      <div className="text-right">
                        <StatusChip status={row.status} />
                        {row.reason ? (
                          <p className="mt-1 max-w-md text-right text-[11px] text-foreground-disabled">{row.reason}</p>
                        ) : null}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          <h4 className="mb-3 flex items-center gap-1.5 text-sm font-bold text-foreground">
            <FileWarning size={14} /> Wage-tax / blocked status
          </h4>
          <div className="mb-3 flex items-center gap-2 text-xs">
            <span className="text-foreground-muted">Calculated</span>
            <span className="font-bold text-foreground">{wageTax.calculated ?? 0}</span>
            <span className="text-foreground-disabled">·</span>
            <span className="text-foreground-muted">Blocked</span>
            <span className="font-bold text-foreground">{wageTax.blocked ?? 0}</span>
            {wageTax.partial ? (
              <>
                <span className="text-foreground-disabled">·</span>
                <span className="text-foreground-muted">Partial</span>
                <span className="font-bold text-foreground">{wageTax.partial}</span>
              </>
            ) : null}
          </div>
          {Object.keys(wageTax.blockedReasonCounts || {}).length ? (
            <ul className="space-y-1 text-xs">
              {Object.entries(wageTax.blockedReasonCounts || {}).map(([code, count]) => (
                <li key={code} className="flex items-center justify-between rounded-md bg-surface-muted px-2 py-1">
                  <span className="font-mono text-[11px] text-foreground">{code}</span>
                  <span className="font-bold text-foreground">{count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-foreground-disabled">No blocked payslips to report.</p>
          )}
        </div>
      </div>

      {partialEmployees.length ? (
        <div className="rounded-xl border border-border bg-surface p-4">
          <h4 className="mb-3 flex items-center gap-1.5 text-sm font-bold text-foreground">
            <FileWarning size={14} /> Partially calculated employees
          </h4>
          <p className="mb-2 text-xs text-foreground-disabled">
            Real gross/RV/ALV/GKV/PV figures ARE persisted for these employees — only the listed component(s)
            could not be calculated, and net pay is never shown as a fabricated zero.
          </p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-foreground-disabled">
                <th className="py-1 pr-2 font-semibold">Employee</th>
                <th className="py-1 pr-2 font-semibold">Period</th>
                <th className="py-1 font-semibold">Unavailable component(s)</th>
              </tr>
            </thead>
            <tbody>
              {partialEmployees.map((p) => (
                <tr key={`${p.payrollRunId}-${p.employeeId}`} className="border-b border-border/70 last:border-0">
                  <td className="py-2 pr-2 align-top text-foreground">{p.employeeName}</td>
                  <td className="py-2 pr-2 align-top text-foreground-muted">{p.periodLabel}</td>
                  <td className="py-2 align-top">
                    <span className="font-mono text-[11px] text-warning">{(p.unavailableComponents || []).join(", ")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <h4 className="mb-3 flex items-center gap-1.5 text-sm font-bold text-foreground">
            <FileWarning size={14} /> Blocked employees
          </h4>
          {blockedEmployees.length ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-foreground-disabled">
                  <th className="py-1 pr-2 font-semibold">Employee</th>
                  <th className="py-1 pr-2 font-semibold">Period</th>
                  <th className="py-1 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {blockedEmployees.map((b, i) => (
                  <tr key={`${b.payrollRunId}-${b.employeeId}`} className="border-b border-border/70 last:border-0">
                    <td className="py-2 pr-2 align-top text-foreground">{b.employeeName}</td>
                    <td className="py-2 pr-2 align-top text-foreground-muted">{b.periodLabel}</td>
                    <td className="py-2 align-top">
                      <span className="font-mono text-[11px] text-warning">{b.blockedReasonCode}</span>
                      {b.blockedReasonMessage ? (
                        <p className="mt-0.5 text-[11px] text-foreground-disabled">{b.blockedReasonMessage}</p>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-xs text-foreground-disabled">No blocked employees in this period.</p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          <h4 className="mb-3 flex items-center gap-1.5 text-sm font-bold text-foreground">
            <CalendarClock size={14} /> Payroll runs
          </h4>
          {payrollRuns.length ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-foreground-disabled">
                  <th className="py-1 pr-2 font-semibold">Period</th>
                  <th className="py-1 pr-2 font-semibold">Status</th>
                  <th className="py-1 pr-2 font-semibold">Pay date</th>
                  <th className="py-1 text-right font-semibold">Calculated</th>
                  <th className="py-1 text-right font-semibold">Blocked</th>
                </tr>
              </thead>
              <tbody>
                {payrollRuns.map((r) => (
                  <tr key={r.runId} className="border-b border-border/70 last:border-0">
                    <td className="py-2 pr-2 text-foreground">{r.periodLabel}</td>
                    <td className="py-2 pr-2">
                      <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[11px] font-semibold text-foreground-muted">
                        {r.runStatus}
                      </span>
                    </td>
                    <td className="py-2 pr-2 text-foreground-muted">{r.payDate || "—"}</td>
                    <td className="py-2 pr-2 text-right text-foreground">{r.calculatedCount}</td>
                    <td className={`py-2 text-right ${r.blockedCount ? "text-warning" : "text-foreground"}`}>
                      {r.blockedCount}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-xs text-foreground-disabled">No Germany payroll runs for this period.</p>
          )}
        </div>
      </div>
    </div>
  );
}