import { CheckCircle2, Circle } from "lucide-react";

// Mirrors backend PAYROLL_STATUS_ORDER (models.py) — kept as its own local
// copy the same way RunsTable.jsx already does, rather than importing
// across files for a single constant.
const STEPS = ["Draft", "Review", "Approved", "Authorized", "Paid", "Closed"];

function fmtDateTime(v) {
  if (!v) return null;
  try {
    return new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return String(v);
  }
}

// Real who/when only for the stages that actually record it today
// (Approved/Authorized/Paid) — Draft/Review/Closed have no actor column on
// PayrollRun, so this intentionally shows nothing for them rather than a
// fabricated value.
function actorFor(step, run) {
  if (step === "Approved") return { by: run.approvedBy, at: run.approvedAt };
  if (step === "Authorized") return { by: run.authorizedBy, at: run.authorizedAt };
  if (step === "Paid") return { by: run.paidBy, at: run.processedAt };
  return null;
}

export default function RunStatusTimeline({ run, vertical = false, className = "" }) {
  if (!run?.status) return null;
  const currentIdx = STEPS.indexOf(run.status);

  if (vertical) {
    return (
      <div className={`bg-surface-muted rounded-[18px] p-4 ${className}`}>
        <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">Run Progress</h4>
        <ol>
          {STEPS.map((step, idx) => {
            const done = idx < currentIdx;
            const isCurrent = idx === currentIdx;
            const actor = actorFor(step, run);

            return (
              <li key={step} className="relative flex gap-3 pb-4 last:pb-0">
                {idx < STEPS.length - 1 && (
                  <span
                    className={`absolute left-[8px] top-[18px] bottom-0 w-[2px] ${idx < currentIdx ? "bg-primary" : "bg-border"}`}
                  />
                )}
                <div className="relative z-10 flex h-[18px] w-[18px] shrink-0 items-center justify-center">
                  {done ? (
                    <CheckCircle2 size={18} className="text-primary bg-surface-muted rounded-full" />
                  ) : (
                    <Circle
                      size={18}
                      className={isCurrent ? "text-info" : "text-foreground-muted"}
                      fill={isCurrent ? "#35B6F5" : "none"}
                      fillOpacity={isCurrent ? 0.15 : 1}
                    />
                  )}
                </div>
                <div className="min-w-0 pt-0.5">
                  <p className={`text-[11px] font-bold ${done || isCurrent ? "text-foreground" : "text-foreground-muted"}`}>
                    {step}
                  </p>
                  {actor?.by && (
                    <p className="text-[10px] text-foreground-muted mt-0.5 leading-tight">
                      {actor.by}
                      {actor.at && <><br />{fmtDateTime(actor.at)}</>}
                    </p>
                  )}
                  {isCurrent && !actor?.by && (
                    <p className="text-[10px] font-semibold text-info mt-0.5">In progress</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  return (
    <div className={`bg-surface-muted rounded-[18px] p-5 mb-5 ${className}`}>
      <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-4">Run Progress</h4>
      <div className="flex items-start">
        {STEPS.map((step, idx) => {
          const done = idx < currentIdx;
          const isCurrent = idx === currentIdx;
          const actor = actorFor(step, run);

          return (
            <div key={step} className="flex-1 flex flex-col relative">
              {idx !== 0 && (
                <div
                  className={`absolute top-[9px] h-[2px] ${idx <= currentIdx ? "bg-primary" : "bg-border"}`}
                  style={{ left: "-50%", right: "50%" }}
                />
              )}
              <div className="flex items-center justify-center z-10">
                {done ? (
                  <CheckCircle2 size={18} className="text-primary bg-surface-muted rounded-full" />
                ) : (
                  <Circle
                    size={18}
                    className={isCurrent ? "text-info" : "text-foreground-muted"}
                    fill={isCurrent ? "#35B6F5" : "none"}
                    fillOpacity={isCurrent ? 0.15 : 1}
                  />
                )}
              </div>
              <div className="text-center mt-2 px-1">
                <p className={`text-[11px] font-bold ${done || isCurrent ? "text-foreground" : "text-foreground-muted"}`}>
                  {step}
                </p>
                {actor?.by && (
                  <p className="text-[10px] text-foreground-muted mt-0.5 leading-tight">
                    {actor.by}
                    {actor.at && <><br />{fmtDateTime(actor.at)}</>}
                  </p>
                )}
                {isCurrent && !actor?.by && (
                  <p className="text-[10px] font-semibold text-info mt-0.5">In progress</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
