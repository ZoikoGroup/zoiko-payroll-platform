import React, { useMemo, useState } from "react";
import { Check, CheckSquare, Search, Square, X } from "lucide-react";
import { DEPARTMENTS, EMPLOYEE_STATUSES } from "../../../service/payrollService";
import EmployeeTable from "./EmployeeTable";

// Shared building blocks for the step-by-step employee workflows (Update
// Employees, Send Template): select employees -> choose fields -> review ->
// apply/send. Presentation only - each workflow keeps its own state and API
// calls.

export const wizardInputClass =
  "w-full rounded-[10px] border border-border bg-background px-3 py-2 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200 disabled:opacity-50";

export const sectionLabelClass = "mb-2 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted";

// ── Step indicator ─────────────────────────────────────────────────────────

export function WizardSteps({ steps, current }) {
  const active = steps[current];
  return (
    <nav aria-label="Progress">
      {/* Phones: compact "Step 2 of 3 · Fields" */}
      <p className="text-[12px] font-semibold text-foreground-muted sm:hidden">
        Step {current + 1} of {steps.length} · <span className="text-foreground">{active?.label}</span>
      </p>
      <ol className="hidden items-center gap-2 sm:flex">
        {steps.map((step, i) => {
          const done = i < current;
          const isCurrent = i === current;
          return (
            <li key={step.id} className="flex flex-1 items-center gap-2 last:flex-none" aria-current={isCurrent ? "step" : undefined}>
              <span
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold transition-colors duration-200 ${
                  done ? "bg-primary text-white" : isCurrent ? "border-2 border-primary text-primary" : "border border-border text-foreground-muted"
                }`}
              >
                {done ? <Check size={14} aria-hidden="true" /> : i + 1}
              </span>
              <span className={`whitespace-nowrap text-[13px] font-semibold ${isCurrent ? "text-foreground" : "text-foreground-muted"}`}>
                {step.label}
              </span>
              {i < steps.length - 1 && <span className={`h-px flex-1 ${done ? "bg-primary" : "bg-border"}`} aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ── Employee picker ────────────────────────────────────────────────────────

const filterSelectClass =
  "rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";

// Selection is a Set of employee ids owned by the caller, who passes its React
// state setter as onSelectionChange (updaters are used). Filtering here only
// narrows what is shown: employees selected earlier stay selected while
// hidden, and the table's own header/row checkboxes only affect visible rows.
export function EmployeePicker({ employees, selectedIds, onSelectionChange, currencyInfo, orgCountryCode, showEmail = false }) {
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [status, setStatus] = useState("");

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (employees || []).filter((e) => {
      if (department && e.department !== department) return false;
      if (status && e.status !== status) return false;
      if (!q) return true;
      return [e.name, e.employeeCode, e.email].some((v) => String(v || "").toLowerCase().includes(q));
    });
  }, [employees, search, department, status]);

  const visibleIds = useMemo(() => new Set(visible.map((e) => e.id)), [visible]);
  const filtered = Boolean(search || department || status);
  const visibleSelected = visible.filter((e) => selectedIds.has(e.id)).length;

  // onSelectionChange is a React state setter: every change is applied as an
  // updater on the LATEST selection. Building the next Set from the
  // selectedIds prop lost clicks made before a re-render (four quick row
  // clicks left only the last one selected).
  function mergeVisible(nextVisibleSelection) {
    // EmployeeTable reports a whole new Set built from the props; turn it
    // into a delta for the visible rows and apply that to the latest state.
    const added = [...nextVisibleSelection].filter((id) => visibleIds.has(id) && !selectedIds.has(id));
    const removed = [...visibleIds].filter((id) => selectedIds.has(id) && !nextVisibleSelection.has(id));
    onSelectionChange((prev) => {
      const next = new Set(prev);
      added.forEach((id) => next.add(id));
      removed.forEach((id) => next.delete(id));
      return next;
    });
  }

  function toggleRow(emp) {
    onSelectionChange((prev) => {
      const next = new Set(prev);
      if (next.has(emp.id)) next.delete(emp.id);
      else next.add(emp.id);
      return next;
    });
  }

  function selectAllVisible() {
    onSelectionChange((prev) => new Set([...prev, ...visibleIds]));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-foreground-muted" aria-hidden="true" />
          <input
            type="text"
            aria-label="Search employees"
            placeholder="Search by name, ID, or email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-[12px] border border-border bg-background py-2.5 pl-9 pr-3.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200"
          />
        </div>
        <select aria-label="Filter by department" value={department} onChange={(e) => setDepartment(e.target.value)} className={filterSelectClass}>
          <option value="">All departments</option>
          {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className={filterSelectClass}>
          <option value="">All statuses</option>
          {EMPLOYEE_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {filtered && (
          <button
            type="button"
            onClick={() => { setSearch(""); setDepartment(""); setStatus(""); }}
            className="inline-flex items-center gap-1 px-2 text-[13px] font-semibold text-foreground-muted transition-colors duration-200 hover:text-primary"
          >
            <X size={14} aria-hidden="true" /> Clear filters
          </button>
        )}
      </div>

      <div
        className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[12px] border px-4 py-2.5 text-[13px] ${
          selectedIds.size > 0 ? "border-primary/30 bg-primary/5" : "border-border bg-surface-muted"
        }`}
        aria-live="polite"
      >
        <span className="font-semibold text-foreground">
          {selectedIds.size} employee{selectedIds.size === 1 ? "" : "s"} selected
          {filtered && selectedIds.size !== visibleSelected ? (
            <span className="font-normal text-foreground-muted"> ({visibleSelected} in this view)</span>
          ) : null}
        </span>
        {visible.length > 0 && visibleSelected < visible.length && (
          <button type="button" onClick={selectAllVisible} className="font-semibold text-primary hover:text-primary-hover">
            Select all {visible.length}{filtered ? " matching" : ""}
          </button>
        )}
        {selectedIds.size > 0 && (
          <button type="button" onClick={() => onSelectionChange(new Set())} className="font-semibold text-foreground-muted hover:text-foreground">
            Clear selection
          </button>
        )}
      </div>

      <EmployeeTable
        employees={visible}
        selectedIds={selectedIds}
        onSelectionChange={mergeVisible}
        onRowClick={toggleRow}
        currencyInfo={currencyInfo}
        orgCountryCode={orgCountryCode}
        showEmail={showEmail}
      />
    </div>
  );
}

// ── Field checklist ────────────────────────────────────────────────────────

// fields: [{ key, label, hint? }]. renderExtra(field) renders under a checked
// field (e.g. the new-value input in Update Employees).
export function FieldChecklist({ fields, checked, onToggle, renderExtra, tone = "primary" }) {
  const on = tone === "teal"
    ? "border-category-teal bg-category-teal/5 text-category-teal"
    : "border-primary bg-primary/5 text-primary";
  return (
    <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
      {fields.map((field) => {
        const isChecked = Boolean(checked[field.key]);
        return (
          <div
            key={field.key}
            className={`rounded-[12px] border px-3.5 py-3 transition-all duration-200 ${isChecked ? on : "border-border"}`}
          >
            <button
              type="button"
              role="checkbox"
              aria-checked={isChecked}
              onClick={() => onToggle(field.key)}
              className={`flex w-full items-center gap-2.5 text-left text-[13px] font-semibold ${isChecked ? "" : "text-foreground"}`}
            >
              {isChecked
                ? <CheckSquare size={16} className="flex-shrink-0" aria-hidden="true" />
                : <Square size={16} className="flex-shrink-0 text-foreground-muted" aria-hidden="true" />}
              <span className="flex-1">{field.label}</span>
              {field.hint ? (
                <span className="text-[10.5px] font-bold uppercase text-foreground-muted">{field.hint}</span>
              ) : null}
            </button>
            {isChecked && renderExtra ? <div className="mt-2.5">{renderExtra(field)}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

// ── Footer ─────────────────────────────────────────────────────────────────

const secondaryButtonClass =
  "rounded-[12px] border border-border bg-surface-muted px-5 py-2.5 text-[13px] font-semibold text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary disabled:opacity-60";
const primaryButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-[12px] bg-primary px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_2px_8px_rgba(25,197,138,0.3)] transition-all duration-200 hover:bg-primary-hover disabled:opacity-60 disabled:shadow-none";

export function WizardFooter({ onCancel, cancelLabel = "Cancel", onPrevious, onNext, nextLabel = "Continue", nextDisabled = false, busy = false, nextIcon = null }) {
  return (
    <div className="flex flex-col-reverse gap-3 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
      <div>
        {onCancel && (
          <button type="button" onClick={onCancel} className={`${secondaryButtonClass} w-full sm:w-auto`}>
            {cancelLabel}
          </button>
        )}
      </div>
      <div className="flex flex-col-reverse gap-3 sm:flex-row">
        {onPrevious && (
          <button type="button" onClick={onPrevious} disabled={busy} className={secondaryButtonClass}>
            Previous
          </button>
        )}
        {onNext && (
          <button type="button" onClick={onNext} disabled={nextDisabled || busy} className={primaryButtonClass}>
            {nextIcon}
            {nextLabel}
          </button>
        )}
      </div>
    </div>
  );
}

export function WizardError({ children }) {
  if (!children) return null;
  return (
    <div role="alert" className="rounded-[12px] border border-error/20 bg-error/10 px-4 py-3 text-[13px] text-error">
      {children}
    </div>
  );
}
