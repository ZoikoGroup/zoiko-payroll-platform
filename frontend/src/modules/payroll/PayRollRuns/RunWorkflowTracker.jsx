import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, Loader2, Lock } from "lucide-react";

import Stepper from "./Stepper";
import {
  PAYROLL_OPERATOR_LABEL,
  PAYROLL_STATUS_ORDER,
  STEP_GUIDE,
  formatWhen,
  stepCompletion,
} from "./runWorkflow";

// The payroll run tracker in the Payroll Runs list's Run progress panel
// (the run detail view shows only RunHeaderAction). Every step explains itself on hover,
// keyboard focus or tap; the "Next action" line performs the current step
// through the caller's onAdvance (which keeps the existing confirmation
// dialogs and server-side permission checks) or says who has to do it.

function stepState(idx, currentIdx) {
  if (idx < currentIdx) return "done";
  if (idx === currentIdx) return "current";
  return "upcoming";
}

const STATE_LABEL = { done: "Done", current: "Current step", upcoming: "Upcoming" };

const STATE_BADGE = {
  current: "bg-info/10 text-info",
  done: "bg-primary/10 text-primary",
  upcoming: "bg-surface-muted text-foreground-muted",
};

/** The guide tooltip shell: portal + fixed position next to `anchor`, so a
 * scrolling panel or a modal never clips it. Shared with the Create Run
 * wizard steps. */
export function GuideTooltip({ id, anchor, title, badge, badgeTone = "upcoming", children }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);

  useLayoutEffect(() => {
    function place() {
      const rect = anchor?.getBoundingClientRect();
      const box = ref.current?.getBoundingClientRect();
      if (!rect || !box) return;
      const margin = 8;
      let left = rect.left + rect.width / 2 - box.width / 2;
      left = Math.max(margin, Math.min(left, window.innerWidth - box.width - margin));
      const below = rect.bottom + 8;
      const top = below + box.height > window.innerHeight - margin ? Math.max(margin, rect.top - box.height - 8) : below;
      setPos({ left, top });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchor]);

  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      style={{ position: "fixed", left: pos?.left ?? -9999, top: pos?.top ?? -9999, zIndex: 1000 }}
      className="pointer-events-none w-72 max-w-[calc(100vw-16px)] rounded-[12px] border border-border bg-surface p-3 text-left shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="text-[13px] font-bold text-foreground">{title}</p>
        {badge && (
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STATE_BADGE[badgeTone] || STATE_BADGE.upcoming}`}>
            {badge}
          </span>
        )}
      </div>
      {children}
    </div>,
    document.body,
  );
}

function StepTooltip({ id, anchor, step, state, run, canOperate }) {
  const guide = STEP_GUIDE[step];
  const done = state === "done" ? stepCompletion(step, run) : null;
  return (
    <GuideTooltip id={id} anchor={anchor} title={step} badge={STATE_LABEL[state]} badgeTone={state}>
      <p className="text-[12px] leading-snug text-foreground-secondary">{guide.meaning}</p>
      {done?.by && (
        <p className="mt-1.5 text-[11px] text-foreground-muted">
          {done.verb} by <span className="font-semibold text-foreground">{done.by}</span>
          {done.at && <> on {formatWhen(done.at)}</>}
        </p>
      )}
      {state !== "done" && guide.howTo && (
        <p className="mt-1.5 text-[12px] leading-snug text-foreground">{guide.howTo}</p>
      )}
      {state === "current" && guide.action && !canOperate && (
        <p className="mt-1.5 flex items-start gap-1.5 text-[12px] font-semibold text-warning">
          <Lock size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          Waiting for {PAYROLL_OPERATOR_LABEL}. Your role can view this run but can&apos;t move it forward.
        </p>
      )}
    </GuideTooltip>
  );
}

/** The run's next step as one button, for the run detail view's header. Same
 * onAdvance (confirmation dialogs + server checks) as the tracker's Next
 * action; without permission, a short grey note says who has to do it. */
export function RunHeaderAction({ run, canOperate, onAdvance, busy }) {
  const guide = STEP_GUIDE[run?.status];
  if (!guide?.action) return null; // Closed (or unknown): nothing to do
  if (!canOperate || !onAdvance) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-foreground-muted" title={`Waiting for ${PAYROLL_OPERATOR_LABEL}`}>
        <Lock size={12} aria-hidden="true" /> Waiting for a payroll admin
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onAdvance(run)}
      disabled={busy}
      className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-bold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
    >
      {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <ArrowRight size={14} aria-hidden="true" />}
      {busy ? "Working…" : guide.action}
    </button>
  );
}

/** The "Next action" box under the tracker. */
function RunNextAction({ run, canOperate, onAdvance, busy, onHighlight }) {
  const guide = STEP_GUIDE[run.status];
  if (!guide) return null;
  if (!guide.action) {
    return (
      <p className="mt-4 rounded-[12px] bg-primary/10 px-3 py-2 text-[12px] font-semibold text-primary">
        This run is complete. Nothing else to do.
      </p>
    );
  }
  return (
    <div
      className="mt-4 rounded-[12px] border border-info/30 bg-info/5 px-3 py-2.5"
      onMouseEnter={() => onHighlight?.(run.id)}
      onMouseLeave={() => onHighlight?.(null)}
      onFocus={() => onHighlight?.(run.id)}
      onBlur={() => onHighlight?.(null)}
    >
      <p className="text-[11px] font-bold uppercase tracking-widest text-info">Next action</p>
      <p className="mt-0.5 text-[13px] font-semibold text-foreground">{guide.action}</p>
      {canOperate ? (
        onAdvance && (
          <button
            type="button"
            onClick={() => onAdvance(run)}
            disabled={busy}
            className="mt-2 inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-3.5 py-2 text-[12px] font-bold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <ArrowRight size={13} aria-hidden="true" />}
            {busy ? "Working…" : guide.action}
          </button>
        )
      ) : (
        <p className="mt-1 flex items-start gap-1.5 text-[12px] text-warning">
          <Lock size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          Waiting for {PAYROLL_OPERATOR_LABEL}.
        </p>
      )}
    </div>
  );
}

export default function RunWorkflowTracker({
  run,
  canOperate = false,
  onAdvance,
  busy = false,
  // (runId | null) => void: called while the current step or the Next action
  // is hovered / focused, so the page can light up that run's Advance button.
  onHighlight,
}) {
  const baseId = useId();
  const [open, setOpen] = useState(null); // { step, pinned, anchor }
  const containerRef = useRef(null);

  // A tap outside closes a pinned tooltip (touch screens have no hover).
  useEffect(() => {
    if (!open?.pinned) return undefined;
    const onDown = (e) => {
      if (!containerRef.current?.contains(e.target)) setOpen(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  if (!run?.status) return null;
  const currentIdx = PAYROLL_STATUS_ORDER.indexOf(run.status);
  const currentStep = PAYROLL_STATUS_ORDER[currentIdx];
  const lightUp = (step) => { if (step === currentStep && STEP_GUIDE[step]?.action) onHighlight?.(run.id); };
  const lightOff = () => onHighlight?.(null);

  const stepButtonProps = (step) => ({
    onMouseEnter: (e) => { const anchor = e.currentTarget; lightUp(step); setOpen((o) => (o?.pinned ? o : { step, pinned: false, anchor })); },
    onMouseLeave: () => { lightOff(); setOpen((o) => (o?.pinned ? o : null)); },
    onFocus: (e) => { const anchor = e.currentTarget; lightUp(step); setOpen((o) => (o?.pinned ? o : { step, pinned: false, anchor })); },
    onBlur: () => { lightOff(); setOpen((o) => (o?.pinned ? o : null)); },
    onClick: (e) => {
      const anchor = e.currentTarget;
      setOpen((o) => (o?.step === step && o.pinned ? null : { step, pinned: true, anchor }));
    },
    onKeyDown: (e) => { if (e.key === "Escape") setOpen(null); },
    "aria-describedby": open?.step === step ? `${baseId}-${step}` : undefined,
  });

  return (
    <div ref={containerRef}>
      <Stepper
        label="Payroll run progress"
        steps={PAYROLL_STATUS_ORDER.map((step, idx) => {
          const state = stepState(idx, currentIdx);
          const done = state === "done" ? stepCompletion(step, run) : null;
          const sub = state === "done"
            ? (done?.by ? `${done.by}${done.at ? ` · ${formatWhen(done.at)}` : ""}` : "Done")
            : state === "current" ? "Current step" : null;
          return { key: step, state, label: step, sub };
        })}
        getStepProps={(step) => stepButtonProps(step.key)}
      />

      {open?.anchor && (
        <StepTooltip
          id={`${baseId}-${open.step}`}
          anchor={open.anchor}
          step={open.step}
          state={stepState(PAYROLL_STATUS_ORDER.indexOf(open.step), currentIdx)}
          run={run}
          canOperate={canOperate}
        />
      )}

      <RunNextAction run={run} canOperate={canOperate} onAdvance={onAdvance} busy={busy} onHighlight={onHighlight} />
    </div>
  );
}
