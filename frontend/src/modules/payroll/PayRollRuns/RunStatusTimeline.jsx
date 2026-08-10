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

export default function RunStatusTimeline({ run }) {
  if (!run?.status) return null;
  const currentIdx = STEPS.indexOf(run.status);

  return (
    <div className="bg-[#F8F7F4] dark:bg-[#2A2520] rounded-[18px] p-5 mb-5">
      <h4 className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-4">Run Progress</h4>
      <div className="flex items-start">
        {STEPS.map((step, idx) => {
          const done = idx < currentIdx;
          const isCurrent = idx === currentIdx;
          const actor = actorFor(step, run);

          return (
            <div key={step} className="flex-1 flex flex-col relative">
              {idx !== 0 && (
                <div
                  className={`absolute top-[9px] h-[2px] ${idx <= currentIdx ? "bg-[#19C58A]" : "bg-[#E5E0D9] dark:bg-[#38312D]"}`}
                  style={{ left: "-50%", right: "50%" }}
                />
              )}
              <div className="flex items-center justify-center z-10">
                {done ? (
                  <CheckCircle2 size={18} className="text-[#19C58A] bg-white dark:bg-[#2A2520] rounded-full" />
                ) : (
                  <Circle
                    size={18}
                    className={isCurrent ? "text-[#35B6F5]" : "text-[#9E9690]"}
                    fill={isCurrent ? "#35B6F5" : "none"}
                    fillOpacity={isCurrent ? 0.15 : 1}
                  />
                )}
              </div>
              <div className="text-center mt-2 px-1">
                <p className={`text-[11px] font-bold ${done || isCurrent ? "text-[#1A1816] dark:text-[#F0EDE8]" : "text-[#9E9690]"}`}>
                  {step}
                </p>
                {actor?.by && (
                  <p className="text-[10px] text-[#9E9690] mt-0.5 leading-tight">
                    {actor.by}
                    {actor.at && <><br />{fmtDateTime(actor.at)}</>}
                  </p>
                )}
                {isCurrent && !actor?.by && (
                  <p className="text-[10px] font-semibold text-[#35B6F5] mt-0.5">In progress</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
