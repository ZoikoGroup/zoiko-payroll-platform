import { Check } from "lucide-react";

// Numbered progress for multi-part forms. `current` is the 1-based active
// step; earlier steps show a tick.
export default function StepIndicator({ steps, current }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Progress">
      {steps.map((label, index) => {
        const number = index + 1;
        const done = number < current;
        const active = number === current;
        return (
          <li key={label} className="flex min-w-0 flex-1 items-center gap-2 last:flex-none">
            <span
              aria-current={active ? "step" : undefined}
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold ${
                done || active ? "bg-[#1260e6] text-white" : "bg-slate-200 text-slate-600"}`}
            >
              {done ? <Check size={15} aria-hidden="true" /> : number}
            </span>
            <span className={`truncate text-[13px] ${active ? "font-semibold text-blue-700" : "text-slate-600"}`}>
              {label}
            </span>
            {number < steps.length && (
              <span className={`mx-1 hidden h-px flex-1 sm:block ${done ? "bg-[#1260e6]" : "bg-slate-300"}`} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
