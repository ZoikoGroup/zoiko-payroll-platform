import { useState, useEffect, useCallback } from "react";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { getUsNewHireReports, markUsNewHireReportFiled } from "../../../service/payrollService";

// US New Hire Reporting (Production-Readiness Plan Phase 5) — compliance
// TRACKING, not report generation: a Pending row is auto-created
// server-side for every new US employee (see service.create_employee's
// own auto-trigger), and an Org Admin marks it Filed once they've
// actually reported the hire to their state's registry. due_date is a
// SUGGESTED deadline (hire date + 20 days) — editable server-side per
// row via the manual-create endpoint, never presented as an
// authoritative legal deadline, since the real number of days genuinely
// varies by state.

function fmtDate(d) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" });
  } catch {
    return d;
  }
}

function isOverdue(row) {
  if (row.status !== "Pending" || !row.dueDate) return false;
  return new Date(row.dueDate) < new Date(new Date().toDateString());
}

// title/subtitle: optional overrides so this same component/API (the
// backend's NewHireReport table and /api/payroll/us/new-hire-reports
// endpoints are org-scoped only, with no country column/filter at all —
// see service.list_new_hire_reports) can serve Puerto Rico's ASUME
// reporting too (PR-007/PR-023, auto-created by service.create_employee's
// own PR branch) without duplicating this panel. Defaults preserve
// today's exact US copy unchanged.
export default function USNewHireReportingPanel({
  title = "New Hire Reporting",
  subtitle = "Every US employee's hire is required to be reported to a state new-hire registry within a short window. " +
    "A Pending row is created automatically when a new US employee is added. The due date shown is a " +
    "SUGGESTION (hire date + 20 days) — this platform does not model each state's exact deadline, which " +
    "genuinely varies; verify and mark filed once actually reported.",
} = {}) {
  const [rows, setRows] = useState([]);
  const [statusFilter, setStatusFilter] = useState("Pending");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getUsNewHireReports(statusFilter === "All" ? null : statusFilter);
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Failed to load New Hire Reporting rows.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  async function handleMarkFiled(row) {
    setBusyId(row.id);
    try {
      await markUsNewHireReportFiled(row.id);
      await load();
    } catch (err) {
      setError(err.message || "Failed to mark as filed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="max-w-4xl space-y-4">
      <div className="rounded-[14px] border border-border bg-surface p-5">
        <h3 className="mb-1 text-[15px] font-bold text-foreground">{title}</h3>
        <p className="mb-4 text-[12px] text-foreground-secondary">{subtitle}</p>

        <div className="mb-3 flex items-center gap-2">
          {["Pending", "Filed", "All"].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded-full px-3 py-1.5 text-[12px] font-semibold ${
                statusFilter === s ? "bg-primary text-white" : "border border-border text-foreground-secondary hover:bg-surface-muted"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {error && <p className="mb-3 rounded-[12px] bg-error/10 px-3.5 py-2.5 text-[12px] text-error">{error}</p>}

        {loading ? (
          <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="py-8 text-center text-xs text-foreground-disabled">No {statusFilter === "All" ? "" : statusFilter.toLowerCase()} New Hire Reporting rows.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-light text-left text-foreground-muted">
                  <th className="pb-2 pr-3">Employee</th>
                  <th className="pb-2 pr-3">Work State</th>
                  <th className="pb-2 pr-3">Hire Date</th>
                  <th className="pb-2 pr-3">Due Date</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-b border-border-light last:border-0">
                    <td className="py-2 pr-3 font-medium text-foreground">{r.employeeName || `Employee #${r.employeeId}`}</td>
                    <td className="py-2 pr-3 text-foreground-muted">{r.workState || "—"}</td>
                    <td className="py-2 pr-3 text-foreground-muted">{fmtDate(r.hireDate)}</td>
                    <td className={`py-2 pr-3 ${isOverdue(r) ? "font-bold text-error" : "text-foreground-muted"}`}>
                      {fmtDate(r.dueDate)}
                      {isOverdue(r) && <AlertTriangle size={11} className="ml-1 inline -mt-0.5" />}
                    </td>
                    <td className="py-2 pr-3">
                      {r.status === "Filed" ? (
                        <span className="flex items-center gap-1 text-success"><CheckCircle2 size={13} /> Filed{r.filedDate ? ` (${fmtDate(r.filedDate)})` : ""}</span>
                      ) : (
                        <span className={isOverdue(r) ? "font-semibold text-error" : "text-warning"}>{isOverdue(r) ? "Overdue" : "Pending"}</span>
                      )}
                    </td>
                    <td className="py-2">
                      {r.status !== "Filed" && (
                        <button
                          onClick={() => handleMarkFiled(r)}
                          disabled={busyId === r.id}
                          className="rounded-md border border-border px-2.5 py-1 text-[11px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
                        >
                          {busyId === r.id ? "Marking…" : "Mark Filed"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
