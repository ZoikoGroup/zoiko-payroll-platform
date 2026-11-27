import { AlertCircle, ChevronDown, Info } from "lucide-react";

import { authInputClass } from "../authUi";

// Form primitives for the registration wizard. Every control is the same
// height (44px), and errors render inline under the field in the app's own
// style instead of the browser's validation bubble (the form uses noValidate).

const INVALID = "border-red-400! focus:border-red-500! focus:ring-red-500/15!";

export function errorId(id) {
  return `${id}-error`;
}

export function controlClass({ withIcon = true, withTrailing = false, invalid = false } = {}) {
  return `${authInputClass({ withIcon, withTrailing })} h-11 ${invalid ? INVALID : ""}`;
}

export function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p id={errorId(id)} className="mt-1.5 flex items-start gap-1 text-[12px] leading-snug text-red-600">
      <AlertCircle size={13} className="mt-px shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </p>
  );
}

export function Field({ id, label, required, info, hint, error, className = "", children }) {
  return (
    <div className={`min-w-0 ${className}`}>
      <div className="mb-1.5 flex min-h-5 items-center justify-between gap-2">
        <label htmlFor={id} className="text-[13px] font-semibold text-slate-800">
          {label}{required && <span className="text-red-600" aria-hidden="true"> *</span>}
        </label>
        {info && (
          <span title={info} className="shrink-0 text-slate-500">
            <Info size={15} aria-label={info} />
          </span>
        )}
      </div>
      {children}
      {error ? <FieldError id={id} message={error} /> : hint && <div className="mt-1.5 text-[12px] text-slate-500">{hint}</div>}
    </div>
  );
}

/** aria props for a control whose Field may show `error`. */
export function invalidProps(id, error, required) {
  return {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? errorId(id) : undefined,
    "aria-required": required ? true : undefined,
  };
}

export function IconInput({ icon: Icon, id, error, required, className = "", ...props }) {
  return (
    <div className="relative">
      <Icon size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
      <input id={id} {...props} {...invalidProps(id, error, required)}
        className={`${controlClass({ invalid: Boolean(error) })} read-only:bg-slate-50 read-only:text-slate-600 ${className}`} />
    </div>
  );
}

export function IconSelect({ icon: Icon, id, error, required, children, ...props }) {
  return (
    <div className="relative">
      <Icon size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
      <select id={id} {...props} {...invalidProps(id, error, required)}
        className={`${controlClass({ withTrailing: true, invalid: Boolean(error) })} appearance-none truncate disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400`}>
        {children}
      </select>
      <ChevronDown size={16} className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
    </div>
  );
}

export function StepHeading({ title, subtitle }) {
  return (
    <div className="mb-3">
      <h3 className="text-[16px] font-bold text-slate-900">{title}</h3>
      {subtitle && <p className="mt-0.5 text-[13px] text-slate-500">{subtitle}</p>}
    </div>
  );
}
