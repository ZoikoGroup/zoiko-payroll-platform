// Presentational pieces shared by every jurisdiction's Policy page —
// moved as-is from policyFormShared.jsx / PolicyConfigPage.jsx as part of
// splitting Policy authoring into per-jurisdiction pages. No behavior
// changes versus the single-page version.
import { useState } from "react";
import { Lock, Unlock, Plus, X } from "lucide-react";
import { compactInputClass } from "./policyUtils";

// One field's label row — required marker and/or a lock indicator (for a
// field that's disabled because this is a "New Version", not editable
// because of anything the value itself does) sit next to the label text
// instead of being buried in prose.
export function FieldLabel({ children, required, locked }) {
  return (
    <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-foreground-muted">
      {children}
      {required && <span className="text-error">*</span>}
      {locked && <Lock size={11} className="ml-auto text-foreground-disabled" />}
    </label>
  );
}

export function FieldError({ message }) {
  if (!message) return null;
  return <p className="mt-1 text-[11px] text-error">{message}</p>;
}

// A section of the page gets exactly one border, one title, one optional
// description — no further nested boxes around its own content. Employee
// Category cards / Allowance rows / LockableFields still get their own
// light border since each is a genuinely distinct configurable item, not
// redundant wrapping.
export function Section({ title, description, children }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 sm:p-6">
      <div className="mb-5">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-1 text-xs text-foreground-muted">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export function MetaChip({ label, children }) {
  if (!children) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1 text-xs">
      <span className="text-foreground-disabled">{label}</span>
      <span className="font-medium text-foreground">{children}</span>
    </span>
  );
}

// A default value (this pack's own suggestion) plus an independent
// "Allow override" flag (whether an assigned organization may replace that
// value). The two are unrelated to each other's editability — Super Admin
// can always edit the value here regardless of the lock state, since the
// lock only governs what an ORGANIZATION can later do with it — so the
// value control is never disabled by allowOverride, only visually paired
// with a lock/unlock indicator for the flag next to it.
export function LockableField({ label, node, type, choices, onChangeValue, onChangeAllow }) {
  const value = node.value;
  const allowOverride = node.allowOverride !== false;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-foreground-secondary">{label}</span>
        <label
          className="flex cursor-pointer select-none items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap"
          style={
            allowOverride
              ? { background: "var(--color-success-light)", color: "var(--color-success)" }
              : { background: "var(--color-surface-muted)", color: "var(--color-foreground-muted)" }
          }
          title={allowOverride ? "Organizations may override this value" : "Locked — organizations must keep this value"}
        >
          <input
            type="checkbox"
            checked={allowOverride}
            onChange={(e) => onChangeAllow(e.target.checked)}
            className="sr-only"
          />
          {allowOverride ? <Unlock size={10} /> : <Lock size={10} />}
          {allowOverride ? "Overridable" : "Locked"}
        </label>
      </div>
      {type === "select" ? (
        <select value={value ?? ""} onChange={(e) => onChangeValue(e.target.value || null)} className={compactInputClass}>
          <option value="">No default</option>
          {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      ) : type === "boolean" ? (
        <select
          value={value === true ? "true" : value === false ? "false" : ""}
          onChange={(e) => onChangeValue(e.target.value === "" ? null : e.target.value === "true")}
          className={compactInputClass}
        >
          <option value="">No default</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : (
        <input
          type="number"
          min={0}
          value={value ?? ""}
          onChange={(e) => onChangeValue(e.target.value === "" ? null : Number(e.target.value))}
          placeholder="No default"
          className={compactInputClass}
        />
      )}
    </div>
  );
}

// One row of the Allowance Components editor — label + %/flat amount +
// an "allow override" gate for the whole component (not per-field like
// LockableField; a partially-locked allowance isn't a real use case).
export function AllowanceComponentRow({ node, onChange, onRemove }) {
  const value = node.value || {};
  const allowOverride = node.allowOverride !== false;
  return (
    <div className="grid grid-cols-1 gap-2 rounded-lg border border-border bg-surface p-2.5 sm:grid-cols-[1fr_110px_110px_auto_auto] sm:items-center">
      <input
        value={value.label ?? ""}
        onChange={(e) => onChange({ value: { ...value, label: e.target.value } })}
        placeholder="Transport Allowance"
        className={compactInputClass}
      />
      <input
        type="number"
        min={0}
        value={value.pct ?? ""}
        onChange={(e) => onChange({ value: { ...value, pct: e.target.value === "" ? null : Number(e.target.value), flat_amount: null } })}
        placeholder="% of gross"
        className={compactInputClass}
      />
      <input
        type="number"
        min={0}
        value={value.flat_amount ?? ""}
        onChange={(e) => onChange({ value: { ...value, flat_amount: e.target.value === "" ? null : Number(e.target.value), pct: null } })}
        placeholder="Flat amount"
        className={compactInputClass}
      />
      <label className="flex items-center gap-1 whitespace-nowrap text-[10px] text-foreground-disabled">
        <input
          type="checkbox"
          checked={allowOverride}
          onChange={(e) => onChange({ allowOverride: e.target.checked })}
          className="h-3.5 w-3.5 rounded border-slate-300"
        />
        Allow override
      </label>
      <button type="button" onClick={onRemove} className="rounded-md p-1.5 text-foreground-disabled hover:bg-error/10 hover:text-error" title="Remove">
        <X size={14} />
      </button>
    </div>
  );
}

// Replaces a blocking window.prompt() with an inline reveal — clicking
// "Add" opens a name input right where the button was, Enter/Add commits
// it, Escape/X discards it, and nothing else on the page moves or reloads.
export function AddAllowanceComponent({ onAdd }) {
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");

  function submit() {
    if (!label.trim()) return;
    onAdd(label.trim());
    setLabel("");
    setAdding(false);
  }

  if (!adding) {
    return (
      <button
        type="button"
        onClick={() => setAdding(true)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:border-primary hover:bg-surface-muted hover:text-primary"
      >
        <Plus size={13} /> Add Allowance Component
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-surface p-2">
      <input
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") { setAdding(false); setLabel(""); }
        }}
        placeholder="e.g. Transport Allowance"
        className={compactInputClass}
      />
      <button type="button" onClick={submit} className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover">
        Add
      </button>
      <button
        type="button"
        onClick={() => { setAdding(false); setLabel(""); }}
        className="shrink-0 rounded-md p-1.5 text-foreground-disabled hover:bg-surface-muted"
        title="Cancel"
      >
        <X size={14} />
      </button>
    </div>
  );
}
