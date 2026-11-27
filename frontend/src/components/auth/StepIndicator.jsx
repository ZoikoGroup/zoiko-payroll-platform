import { Check } from "lucide-react";

// Numbered progress for multi-step forms. `current` is the 1-based active
// step; earlier steps show a tick and, when `onStepClick` is given, are
// buttons that go back to that step. Labels are never truncated: they wrap,
// and below the sm breakpoint they sit under their number so four steps still
// fit a phone screen.
export default function StepIndicator({ steps, current, onStepClick }) {
  return (
    <nav aria-label="Registration progress">
      <ol className="flex items-start gap-1 sm:items-center sm:gap-2">
        {steps.map((label, index) => {
          const number = index + 1;
          const done = number < current;
          const active = number === current;
          const clickable = done && typeof onStepClick === "function";
          const circle = (
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold transition-colors ${
                active ? "bg-[#1260e6] text-white ring-4 ring-blue-100"
                  : done ? "bg-[#1260e6] text-white"
                    : "border border-slate-300 bg-white text-slate-500"}`}
            >
              {done ? <Check size={15} strokeWidth={3} aria-hidden="true" /> : number}
            </span>
          );
          const text = (
            <span className={`text-center text-[11px] leading-tight sm:text-left sm:text-[13px] ${
              active ? "font-semibold text-blue-700" : done ? "font-medium text-slate-700" : "text-slate-500"}`}
            >
              {label}
              {done && <span className="sr-only"> (completed)</span>}
            </span>
          );
          const inner = (
            <span className="flex flex-col items-center gap-1 sm:flex-row sm:gap-2">
              {circle}
              {text}
            </span>
          );
          return (
            <li key={label} className="flex min-w-0 flex-1 items-center gap-1 last:flex-none sm:gap-2">
              {clickable ? (
                <button
                  type="button"
                  onClick={() => onStepClick(number)}
                  title={`Back to ${label}`}
                  className="rounded-lg p-0.5 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
                >
                  {inner}
                </button>
              ) : (
                <span aria-current={active ? "step" : undefined} className="p-0.5">{inner}</span>
              )}
              {number < steps.length && (
                <span
                  aria-hidden="true"
                  className={`mt-3.5 h-px min-w-3 flex-1 self-start sm:mt-0 sm:self-auto ${done ? "bg-[#1260e6]" : "bg-slate-300"}`}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
