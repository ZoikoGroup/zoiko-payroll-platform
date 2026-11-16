import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Clock, Loader2, TriangleAlert } from "lucide-react";
import { getPublicForm, submitPublicForm } from "../service/payrollService";
import zoikoPayrollLogo from "../assets/zoiko-payroll-logo.png";

// Public, no-login page an employee reaches from the "Send Template" email
// link (/forms/fill/:token). The token is the only credential: it identifies
// one form for one employee. Submitted values go to the payroll team's review
// queue and change nothing until they are approved.

const inputClass =
  "w-full rounded-[10px] border border-border bg-surface px-3 py-2.5 text-[14px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";

function toInputValue(field, value) {
  if (value === null || value === undefined) return "";
  if (field.type === "date") return String(value).slice(0, 10);
  return String(value);
}

function FieldInput({ field, value, onChange }) {
  const id = `field-${field.key}`;
  if (field.type === "select" && Array.isArray(field.options) && field.options.length > 0) {
    return (
      <select id={id} value={value} required={field.required} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        <option value="">Select…</option>
        {field.options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    );
  }
  return (
    <input
      id={id}
      type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
      step={field.type === "number" ? "any" : undefined}
      value={value}
      required={field.required}
      onChange={(e) => onChange(e.target.value)}
      className={inputClass}
    />
  );
}

function StatusCard({ icon: Icon, tone, title, children }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <Icon className={`h-10 w-10 ${tone}`} aria-hidden="true" />
      <h2 className="text-[17px] font-bold text-foreground">{title}</h2>
      <p className="max-w-sm text-[14px] text-foreground-muted">{children}</p>
    </div>
  );
}

export default function PublicFormPage() {
  const { token } = useParams();
  const [form, setForm] = useState(null);
  const [values, setValues] = useState({});
  const [loadError, setLoadError] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submittedMessage, setSubmittedMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    getPublicForm(token)
      .then((data) => {
        if (cancelled) return;
        setForm(data);
        const initial = {};
        for (const f of data.fields || []) initial[f.key] = toInputValue(f, data.currentValues?.[f.key]);
        setValues(initial);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.status === 404 ? "This link is invalid." : err.message || "Could not load this form.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError("");
    try {
      const payload = {};
      for (const f of form.fields || []) {
        const v = values[f.key];
        payload[f.key] = f.type === "number" && v !== "" ? Number(v) : v;
      }
      const res = await submitPublicForm(token, payload);
      setSubmittedMessage(res?.message || "Thank you — your response has been submitted for review.");
    } catch (err) {
      setSubmitError(err.message || "Could not submit the form. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  let body;
  if (loadError) {
    body = <StatusCard icon={TriangleAlert} tone="text-error" title="Link not available">{loadError} Please contact your payroll team for a new link.</StatusCard>;
  } else if (!form) {
    body = (
      <div className="flex justify-center py-10">
        <Loader2 className="h-7 w-7 animate-spin text-primary" aria-label="Loading form" />
      </div>
    );
  } else if (submittedMessage || form.status === "submitted") {
    body = (
      <StatusCard icon={CheckCircle2} tone="text-success" title="Response received">
        {submittedMessage || "This form has already been submitted. Your payroll team will review it."}
      </StatusCard>
    );
  } else if (form.status === "expired") {
    body = <StatusCard icon={Clock} tone="text-warning" title="This link has expired">Please contact your payroll team for a new link.</StatusCard>;
  } else {
    body = (
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <h1 className="text-[20px] font-bold text-foreground">{form.formName}</h1>
          <p className="mt-1 text-[14px] text-foreground-muted">
            Hi {form.employeeName}, please check the details below and update anything that has changed. Your payroll
            team reviews every response before it is applied.
          </p>
        </div>
        {(form.fields || []).map((field) => (
          <div key={field.key}>
            <label htmlFor={`field-${field.key}`} className="mb-1.5 block text-[13px] font-semibold text-foreground">
              {field.label}
              {field.required ? <span className="text-error"> *</span> : null}
            </label>
            <FieldInput field={field} value={values[field.key] ?? ""} onChange={(v) => setValues((prev) => ({ ...prev, [field.key]: v }))} />
          </div>
        ))}
        {submitError && (
          <p role="alert" className="rounded-[10px] border border-error/20 bg-error/10 px-3 py-2 text-[13px] text-error">
            {submitError}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex w-full items-center justify-center gap-2 rounded-[12px] bg-primary px-5 py-3 text-[14px] font-bold text-white transition hover:bg-primary-hover disabled:opacity-60"
        >
          {submitting ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : null}
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </form>
    );
  }

  return (
    <div className="min-h-screen bg-background px-4 py-10">
      <div className="mx-auto w-full max-w-lg">
        <img src={zoikoPayrollLogo} alt="Zoiko Payroll" className="mx-auto mb-6 h-9 w-auto" />
        <div className="rounded-[18px] border border-border bg-surface p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] sm:p-8">{body}</div>
      </div>
    </div>
  );
}
