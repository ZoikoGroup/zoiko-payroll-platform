import { useState } from "react";
import { card, useLoad } from "./jpFormat";
import { Table } from "./jpShared";

// One Japan record list + capture form, driven by a field config. Rows are
// captured as DRAFT/REQUESTED and only count once a SECOND user approves them
// (enforced server-side). Blank inputs are omitted, never sent as a guess;
// the backend refuses unknown fields and missing required ones.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
export const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const btnPrimary = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function errorText(e) {
  const detail = e?.response?.data?.detail ?? e?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || String(d)).join("; ");
  return e?.message || "The action failed.";
}

function emptyValues(fields) {
  return Object.fromEntries(fields.map((f) => [f.key, f.type === "weekdays" ? [] : ""]));
}

function toPayload(fields, values) {
  const out = {};
  for (const f of fields) {
    const value = values[f.key];
    if (f.type === "weekdays") {
      if (value.length) out[f.key] = [...value].sort((a, b) => a - b).join(",");
    } else if (value !== "" && value !== undefined && value !== null) {
      out[f.key] = value;
    }
  }
  return out;
}

function Input({ field, value, onChange }) {
  if (field.type === "select" || field.type === "bool") {
    const options = field.type === "bool"
      ? [["", "—"], ["true", "Yes"], ["false", "No"]]
      : [["", "—"], ...field.options.map((o) => (Array.isArray(o) ? o : [o, o]))];
    return (
      <select className={input} value={value} required={field.required} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
    );
  }
  if (field.type === "weekdays") {
    return (
      <div className="flex flex-wrap gap-1" role="group" aria-label={field.label}>
        {WEEKDAYS.map((day, index) => {
          const on = value.includes(index);
          return (
            <button key={day} type="button" aria-pressed={on}
              onClick={() => onChange(on ? value.filter((d) => d !== index) : [...value, index])}
              className={`rounded border px-1.5 py-0.5 text-[11px] ${on ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground-muted"}`}>
              {day}
            </button>
          );
        })}
      </div>
    );
  }
  return (
    <input className={input} type={field.type === "date" ? "date" : "text"}
      inputMode={field.type === "number" ? "decimal" : undefined}
      required={field.required} placeholder={field.placeholder} value={value}
      onChange={(e) => onChange(e.target.value)} />
  );
}

export default function JPRecordSection({
  title, description, testId, load, create, fields = [], columns, actions = [],
  transform, createLabel = "Capture (DRAFT)", createdNotice, empty,
}) {
  const [rows, loadError, loading, reload] = useLoad(load);
  const [values, setValues] = useState(() => emptyValues(fields));
  const [state, setState] = useState({ busy: false, error: null, notice: null });

  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload();
    } catch (e) {
      setState({ busy: false, error: errorText(e), notice: null });
    }
  };

  const submit = (e) => {
    e.preventDefault();
    const payload = toPayload(fields, values);
    run(async () => {
      await create(transform ? transform(payload) : payload);
      setValues(emptyValues(fields));
    }, createdNotice || "Captured as DRAFT — a second user must approve it before payroll uses it.");
  };

  const actionColumn = actions.length ? [{
    label: "Actions",
    render: (row) => (
      <div className="flex flex-wrap gap-1">
        {actions.filter((a) => a.show(row)).map((a) => (
          <button key={a.label} type="button" className={btn} disabled={state.busy}
            onClick={() => run(() => a.run(row), a.ok)}>{a.label}</button>
        ))}
      </div>
    ),
  }] : [];

  return (
    <section className={card} data-testid={testId}>
      <h3 className="text-[14px] font-semibold text-foreground">{title}</h3>
      {description && <p className="mb-3 text-[12px] text-foreground-muted">{description}</p>}
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty={empty} columns={[...columns, ...actionColumn]} />
      )}
      {create && fields.length > 0 && (
        <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label={`Capture: ${title}`}>
          {fields.map((field) => (
            <label key={field.key} className={labelCls}>
              {field.label}{field.required ? " *" : ""}
              <Input field={field} value={values[field.key]}
                onChange={(v) => setValues((current) => ({ ...current, [field.key]: v }))} />
            </label>
          ))}
          <div className="flex items-end">
            <button type="submit" className={btnPrimary} disabled={state.busy}>{createLabel}</button>
          </div>
        </form>
      )}
    </section>
  );
}

export const statusCol = { label: "Status", render: (row) => row.status ?? row.submission_status ?? "—" };
export const periodCol = {
  label: "In force",
  render: (row) => `${row.effective_from || "—"} → ${row.effective_to || "open"}`,
};
export const isDraft = (row) => row.status === "DRAFT";
