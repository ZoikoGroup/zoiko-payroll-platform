import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, CalendarCheck } from "lucide-react";

const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ROWS_COLLAPSED = 8;
export const ATTENDANCE_OVERRIDE_MIN_REASON = 10;

// Pre-run attendance check for the payroll run wizard. The same check runs
// server-side on create/generate/recalculate (ATTENDANCE_INCOMPLETE), so this
// panel only explains the block early — it is not the enforcement itself.
export default function AttendanceReadinessPanel({
  readiness,
  loading,
  error,
  onRefresh,
  overrideEnabled,
  setOverrideEnabled,
  overrideReason,
  setOverrideReason,
}) {
  const navigate = useNavigate();
  const [showAll, setShowAll] = useState(false);

  if (loading && !readiness) {
    return (
      <div className="rounded-[14px] border border-border bg-surface-muted px-4 py-3 flex items-center gap-2 text-[13px] text-foreground-muted">
        <Loader2 size={14} className="animate-spin text-info" /> Checking attendance for this pay period…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-[14px] border border-error/30 bg-error/5 px-4 py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-error">Couldn{"'"}t check attendance: {error}</p>
        <button type="button" onClick={onRefresh} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-error">
          <RefreshCw size={13} /> Try again
        </button>
      </div>
    );
  }

  if (!readiness) return null;

  const inScope = readiness.totalEmployees - readiness.exemptEmployees;
  const offDays = (readiness.weeklyOffDays || []).map((d) => WEEKDAY_SHORT[d]).join(", ") || "none";
  const scopeNote = readiness.employmentTypes?.length
    ? `Required for: ${readiness.employmentTypes.join(", ")} employees.`
    : "Required for all employees.";

  if (readiness.incompleteEmployees === 0) {
    return (
      <div className="rounded-[14px] border border-primary/20 bg-primary/5 px-4 py-3 flex items-start gap-2">
        <CheckCircle2 size={16} className="text-primary mt-0.5 flex-shrink-0" />
        <p className="text-[13px] text-foreground">
          Attendance is complete for {readiness.completeEmployees} of {inScope} employee(s) in this pay period.
          <span className="text-foreground-muted"> Weekly off: {offDays}; company holidays excluded.</span>
        </p>
      </div>
    );
  }

  const blocking = readiness.required;
  const rows = showAll ? readiness.missing : readiness.missing.slice(0, ROWS_COLLAPSED);
  const reasonTooShort = overrideEnabled && overrideReason.trim().length < ATTENDANCE_OVERRIDE_MIN_REASON;

  return (
    <div className={`rounded-[14px] border px-4 py-3 space-y-3 ${blocking ? "border-error/30 bg-error/5" : "border-warning/30 bg-warning/10"}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-2 min-w-0">
          <AlertTriangle size={16} className={`mt-0.5 flex-shrink-0 ${blocking ? "text-error" : "text-warning"}`} />
          <div className="min-w-0">
            <p className={`text-[13px] font-bold ${blocking ? "text-error" : "text-warning"}`}>
              {blocking
                ? "Attendance sheet incomplete — payroll can't run"
                : "Attendance incomplete (not required by your payroll policy)"}
            </p>
            <p className="text-[12px] text-foreground-muted mt-0.5">
              {readiness.incompleteEmployees} of {inScope} employee(s) are missing attendance for working days in this period.
              Days with no attendance would otherwise be paid as present. Weekly off: {offDays}; company holidays excluded. {scopeNote}
            </p>
          </div>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <button type="button" onClick={() => navigate("/payroll/attendance")}
            className="inline-flex items-center gap-1.5 rounded-[12px] bg-primary px-3 py-2 text-[12px] font-bold text-white hover:bg-primary-hover">
            <CalendarCheck size={13} /> Go to Attendance
          </button>
          <button type="button" onClick={onRefresh} disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-[12px] border border-border bg-surface px-3 py-2 text-[12px] font-semibold text-foreground-muted hover:border-primary hover:text-primary disabled:opacity-50">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Re-check
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-[12px] border border-border bg-surface">
        <table className="w-full text-left text-[12px]">
          <thead className="bg-surface-muted text-[10px] font-bold uppercase tracking-widest text-foreground-muted">
            <tr>
              <th className="px-3 py-2">Employee</th>
              <th className="px-3 py-2 whitespace-nowrap">Recorded / Expected</th>
              <th className="px-3 py-2">Missing dates</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((m) => (
              <tr key={m.employeeId}>
                <td className="px-3 py-2 text-foreground">
                  <span className="font-semibold">{m.employeeName}</span>
                  {m.employeeCode && <span className="text-foreground-muted"> · {m.employeeCode}</span>}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-foreground-muted">{m.recordedDays} / {m.expectedDays}</td>
                <td className="px-3 py-2 text-foreground-muted">
                  {m.missingDates.slice(0, 6).join(", ")}
                  {m.missingDays > 6 && ` +${m.missingDays - 6} more`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(readiness.missing.length > ROWS_COLLAPSED || readiness.missingTruncated) && (
        <div className="flex items-center gap-3 text-[12px]">
          {readiness.missing.length > ROWS_COLLAPSED && (
            <button type="button" onClick={() => setShowAll((v) => !v)} className="font-semibold text-info">
              {showAll ? "Show fewer" : `Show all ${readiness.missing.length}`}
            </button>
          )}
          {readiness.missingTruncated && (
            <span className="text-foreground-muted">List limited to the first {readiness.missing.length} employees.</span>
          )}
        </div>
      )}

      {blocking && (
        <div className="rounded-[12px] border border-border bg-surface p-3 space-y-2">
          <label className="flex items-start gap-2 text-[12px] text-foreground cursor-pointer">
            <input type="checkbox" checked={overrideEnabled} onChange={(e) => setOverrideEnabled(e.target.checked)} className="mt-0.5" />
            <span>
              <strong>Admin override:</strong> run payroll anyway. Employees above will be paid as present for every day without attendance.
              Your name and reason are recorded on the run and in the activity log.
            </span>
          </label>
          {overrideEnabled && (
            <div>
              <textarea
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                rows={2}
                maxLength={1000}
                placeholder="Reason (required) — e.g. biometric export delayed, attendance verified manually by HR"
                className="w-full rounded-[10px] border border-border bg-background px-3 py-2 text-[12px] text-foreground focus:outline-none focus:border-primary"
              />
              {reasonTooShort && (
                <p className="text-[11px] text-error mt-1">Enter at least {ATTENDANCE_OVERRIDE_MIN_REASON} characters.</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
