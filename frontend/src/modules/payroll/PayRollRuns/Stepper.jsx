import { Check } from "lucide-react";

// The one (vertical) stepper used by the payroll-run step lists: the Create
// New Run wizard (Configure -> Process) and the Run progress panel (Draft ->
// Closed). Spacing and the connecting line are computed from the SAME
// constants as the step circles, so the line always runs exactly from the
// centre of one circle to the centre of the next - whatever the step height
// or screen size.
//
//   steps: [{ key, state: "done" | "current" | "upcoming", label, sub?, icon? }]
//   getStepProps(step, index) -> props for the step's <button> (hover / focus /
//     tap handlers, aria-*). Each step is a button so its guide can open on
//     hover, keyboard focus or tap.
//   fill: from the lg breakpoint, spread the steps evenly down
//     the height the parent gives the stepper (each gap capped); smaller or
//     short screens keep compact spacing, so nothing overlaps.

const PAD_X = 4; // step button horizontal padding (px)
const PAD_Y = 6; // step button vertical padding (px)

function Marker({ state, index, icon: Icon, size }) {
  const box = { width: size, height: size };
  if (state === "done") {
    return (
      <span style={box} className="relative z-10 flex shrink-0 items-center justify-center rounded-full bg-primary text-white">
        <Check size={Math.round(size / 2)} strokeWidth={3} aria-hidden="true" />
      </span>
    );
  }
  return (
    <span
      style={box}
      className={`relative z-10 flex shrink-0 items-center justify-center rounded-full border-2 text-[11px] font-bold ${
        state === "current"
          ? "border-info bg-surface text-info ring-4 ring-info/15"
          : "border-border bg-surface text-foreground-muted"}`}
    >
      {Icon ? <Icon size={Math.round(size * 0.42)} aria-hidden="true" /> : index + 1}
    </span>
  );
}

export default function Stepper({
  steps,
  label,
  fill = false,
  markerSize = 28,
  getStepProps = () => ({}),
}) {
  const r = markerSize / 2;
  const centreX = PAD_X + r; // circle centre, from the step's left edge
  const centreY = PAD_Y + r; // circle centre, from the step's top edge
  const n = steps.length;
  // A connector is "done" (coloured) when the step after it has been reached.
  const reached = (i) => steps[i]?.state === "done" || steps[i]?.state === "current";

  return (
    <ol aria-label={label} className={`flex flex-col ${fill ? "lg:min-h-0 lg:flex-1" : ""}`}>
      {steps.map((step, i) => (
        <li
          key={step.key}
          aria-current={step.state === "current" ? "step" : undefined}
          className={`relative ${fill && i < n - 1 ? "lg:min-h-0 lg:max-h-[150px] lg:flex-1" : ""} ${
            step.state === "upcoming" ? "opacity-60" : ""}`}
        >
          {i < n - 1 && (
            // From this circle's centre down to the next one's: the next step
            // starts where this <li> ends, so its centre is exactly 100% below.
            <span
              aria-hidden="true"
              className={`absolute w-0.5 -translate-x-1/2 ${reached(i + 1) ? "bg-primary" : "bg-border"}`}
              style={{ left: centreX, top: centreY, height: "100%" }}
            />
          )}
          <button
            type="button"
            {...getStepProps(step, i)}
            style={{ padding: `${PAD_Y}px ${PAD_X}px` }}
            className={`relative flex w-full items-start gap-2.5 rounded-[10px] text-left transition-colors hover:bg-surface-muted focus-visible:outline-2 focus-visible:outline-primary ${
              step.state === "current" ? "bg-info/5" : ""}`}
          >
            <Marker state={step.state} index={i} icon={step.icon} size={markerSize} />
            <span className="min-w-0" style={{ paddingTop: Math.max(0, r - 9) }}>
              <span className={`block text-[13px] font-semibold leading-[18px] ${step.state === "upcoming" ? "text-foreground-muted" : "text-foreground"}`}>
                {step.label}
              </span>
              {step.sub && (
                <span className={`block text-[11px] leading-tight ${step.state === "current" ? "font-semibold text-info" : "text-foreground-muted"}`}>
                  {step.sub}
                </span>
              )}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
