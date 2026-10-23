import { useState } from "react";
import { CalendarDays } from "lucide-react";
import { btnPrimary, card, Field, input, Messages } from "../brShared";
import { localToday, statusTone } from "./brEmployerUtils";

// Shared pieces for the Brazil employer-onboarding panels (ZP-BR-ENG-001
// Phase 3), used by the organisation's Compliance Centre (editable) and the
// Super Admin Employer tab (readOnly). Mirrors the Mexico employer panels.

export function ReadinessDateBar({ on, onChange }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border-2 border-primary/40 bg-primary/5 p-3" data-testid="br-readiness-on">
      <CalendarDays size={18} className="text-primary" />
      <span className="text-[13px] font-semibold text-foreground">
        Readiness on <span className="text-primary">{on}</span>
      </span>
      <input
        type="date" aria-label="Readiness on" required
        className="rounded-lg border border-border bg-surface px-2 py-1 text-[13px] text-foreground"
        value={on} onChange={(e) => e.target.value && onChange(e.target.value)}
      />
      <button type="button" className="text-[12px] text-foreground-muted underline" onClick={() => onChange(localToday())}>
        Today (your local date)
      </button>
      <span className="text-[11px] text-foreground-muted">This date is sent with every readiness request; the server date is never used.</span>
    </div>
  );
}

export function Panel({ title, hint, children, testId }) {
  return (
    <section className={card} data-testid={testId}>
      <h3 className="text-[14px] font-semibold text-foreground">{title}</h3>
      {hint && <p className="mt-1 text-[12px] text-foreground-muted">{hint}</p>}
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </section>
  );
}

export function Badge({ value }) {
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${statusTone[value] || "bg-surface-muted text-foreground"}`}>{value || "—"}</span>;
}

// A small form: fields = [{ key, label, type?: "text"|"date"|"number"|"select"|"checkbox", options?, required?, placeholder? }].
export function MiniForm({ fields, onSubmit, submitLabel, busy, error, notice, initial = {}, testId }) {
  const [state, setState] = useState(() => ({ ...initial }));
  const set = (k, v) => setState((s) => ({ ...s, [k]: v }));
  return (
    <form
      className="flex flex-col gap-2" data-testid={testId}
      onSubmit={async (e) => { e.preventDefault(); if (await onSubmit(state)) setState({ ...initial }); }}
    >
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {fields.map((f) => (
          <Field key={f.key} label={`${f.label}${f.required ? " *" : ""}`}>
            {f.type === "select" ? (
              <select className={input} name={f.key} value={state[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>
                <option value="">—</option>
                {f.options.map((o) => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
              </select>
            ) : f.type === "checkbox" ? (
              <input type="checkbox" name={f.key} checked={Boolean(state[f.key])} onChange={(e) => set(f.key, e.target.checked)} />
            ) : (
              <input
                className={input} name={f.key} type={f.type || "text"} value={state[f.key] ?? ""}
                placeholder={f.placeholder} onChange={(e) => set(f.key, e.target.value)}
              />
            )}
          </Field>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button type="submit" className={btnPrimary} disabled={busy}>{submitLabel}</button>
        <Messages error={error} notice={notice} />
      </div>
    </form>
  );
}
