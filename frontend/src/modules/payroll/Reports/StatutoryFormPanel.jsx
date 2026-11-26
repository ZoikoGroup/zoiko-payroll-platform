import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, ExternalLink, FileText, Loader2 } from "lucide-react";
import {
  generateAuSuperstream,
  generateIndiaForm123,
  generateIndiaForm130,
  generateReport,
  getEmployees,
} from "../../../service/payrollService";
import INForm138Panel from "./INForm138Panel";

// One statutory form from the Super Admin report catalog
// (GET /payroll/report-templates/catalog), with its own generate panel:
// reporting year, period / run or employee, Generate, and the due dates
// Super Admin published in the filing calendar. Which inputs it needs
// follows the form's `generator`:
//   in_form_138               quarter-level, employer-wide (INForm138Panel)
//   in_form_130 / in_form_123 one document per employee
//   generic_run / au_superstream  one finalized payroll run of this country
//   dedicated                 generated from the country's own workspace

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";
const FINALIZED = ["Approved", "Authorized", "Paid", "Closed"];

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
    </label>
  );
}

function formatDueDate(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

// Upcoming due dates first; once all have passed, the latest ones.
function upcomingDueDates(calendar = [], year, limit = 4) {
  const rows = calendar.filter((c) => !year || c.reportingYear === year);
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = rows.filter((c) => c.dueDate >= today);
  return (upcoming.length ? upcoming : rows.slice(-limit)).slice(0, limit);
}

function DueDates({ calendar, year }) {
  const rows = upcomingDueDates(calendar, year);
  if (!rows.length) {
    return <p className="text-[12px] text-foreground-muted">No due dates published for {year || "this form"} yet.</p>;
  }
  return (
    <div className="flex flex-wrap gap-2" data-testid="form-due-dates">
      {rows.map((r) => (
        <span key={`${r.reportingYear}-${r.periodKey}`} className="inline-flex items-center gap-1.5 rounded-full bg-warning/10 px-2.5 py-1 text-[11px] font-semibold text-foreground">
          <CalendarClock size={12} className="text-warning" />
          {r.periodLabel || r.periodKey}: due {formatDueDate(r.dueDate)}
        </span>
      ))}
    </div>
  );
}

function Result({ status, message }) {
  if (!message) return null;
  return (
    <p className={`mt-3 rounded-[12px] px-3.5 py-2.5 text-[12px] ${status === "error" ? "bg-error/10 text-error" : "bg-success/10 text-success"}`}>
      {message}
    </p>
  );
}

function GenerateButton({ busy, disabled, onClick, label }) {
  return (
    <button
      onClick={onClick}
      disabled={busy || disabled}
      className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
    >
      {busy && <Loader2 size={14} className="animate-spin" />}
      {busy ? "Generating…" : label}
    </button>
  );
}

function useYear(form) {
  const years = form.years.map((y) => y.reportingYear);
  const [year, setYear] = useState(years[0] || "");
  const selected = form.years.find((y) => y.reportingYear === year) || form.years[0] || null;
  return { years, year, setYear, selected };
}

function YearSelect({ years, year, setYear }) {
  return (
    <Field label="Reporting year">
      <select className={inputClass} value={year} onChange={(e) => setYear(e.target.value)}>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
    </Field>
  );
}

function RunFormPanel({ form, country, runs, onGenerated }) {
  const { years, year, setYear, selected } = useYear(form);
  const countryRuns = useMemo(
    () => runs.filter((r) => FINALIZED.includes(r.status)
      && (!(r.totalsByCountry || []).length || r.totalsByCountry.some((t) => t.country === country))),
    [runs, country],
  );
  const [runId, setRunId] = useState("");
  const run = countryRuns.find((r) => String(r.id) === String(runId)) || null;
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const payload = { reportTemplateId: selected.templateId, payrollRunId: Number(runId) };
      const report = form.generator === "au_superstream"
        ? await generateAuSuperstream(payload)
        : await generateReport({ ...payload, reportingPeriod: run?.period });
      setStatus("done");
      setMessage(`Generated — report #${report.id}. It is listed in Report History.`);
      onGenerated?.(report);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this report.");
    }
  }

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <YearSelect years={years} year={year} setYear={setYear} />
        <Field label="Period (finalized payroll run)">
          <select className={inputClass} value={runId} onChange={(e) => setRunId(e.target.value)}>
            <option value="">{countryRuns.length ? "Select a run…" : "No finalized runs for this country"}</option>
            {countryRuns.map((r) => (
              <option key={r.id} value={r.id}>{r.period || r.runCode} · {r.runCode} · {r.status}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="mt-4 flex justify-end">
        <GenerateButton busy={status === "generating"} disabled={!runId || !selected} onClick={handleGenerate} label={`Generate ${form.name}`} />
      </div>
      <Result status={status} message={message} />
    </>
  );
}

function EmployeeFormPanel({ form, country, onGenerated }) {
  const { years, year, setYear, selected } = useYear(form);
  const [employees, setEmployees] = useState(null);
  const [employeeId, setEmployeeId] = useState("");
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    getEmployees({ limit: 1000 }).then((list) => {
      if (!cancelled) setEmployees(list.filter((e) => (e.countryCode || "").toUpperCase() === country));
    });
    return () => { cancelled = true; };
  }, [country]);

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const base = { reportTemplateId: selected.templateId, employeeId: Number(employeeId) };
      const startYear = Number((year || "").split("-")[0]);
      const report = form.generator === "in_form_123"
        ? await generateIndiaForm123({ ...base, taxYear: year })
        : await generateIndiaForm130({ ...base, asOfDate: startYear ? `${startYear + 1}-03-31` : undefined });
      setStatus("done");
      setMessage(`Generated — report #${report.id} for this employee. It is listed in Report History.`);
      onGenerated?.(report);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this form.");
    }
  }

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <YearSelect years={years} year={year} setYear={setYear} />
        <Field label="Employee">
          <select className={inputClass} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} disabled={employees == null}>
            <option value="">
              {employees == null ? "Loading employees…" : employees.length ? "Select an employee…" : "No employees in this country"}
            </option>
            {(employees || []).map((e) => (
              <option key={e.id} value={e.id}>{e.name}{e.employeeCode ? ` (${e.employeeCode})` : ""}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="mt-4 flex justify-end">
        <GenerateButton busy={status === "generating"} disabled={!employeeId || !selected} onClick={handleGenerate} label={`Generate ${form.name}`} />
      </div>
      <Result status={status} message={message} />
    </>
  );
}

export default function StatutoryFormPanel({ form, country, countryName, runs = [], onGenerated }) {
  const [year, setYear] = useState(form.years[0]?.reportingYear || "");

  if (form.generator === "in_form_138") {
    return (
      <INForm138Panel
        years={form.years.map((y) => y.reportingYear)}
        filingCalendar={form.filingCalendar}
      />
    );
  }

  const perEmployee = form.generator === "in_form_130" || form.generator === "in_form_123";
  return (
    <div className="max-w-3xl rounded-[14px] border border-border bg-surface p-5 space-y-4" data-testid={`statutory-form-${form.reportType}`}>
      <div>
        <h3 className="flex items-center gap-2 text-[15px] font-bold text-foreground">
          <FileText size={16} className="text-primary" /> {form.name}
        </h3>
        <p className="mt-1 text-[12px] text-foreground-secondary">
          {form.description || `${countryName} statutory report`}
          {form.regulatoryAuthority ? ` · ${form.regulatoryAuthority}` : ""}
          {` · ${perEmployee || form.documentScope === "PER_EMPLOYEE" ? "one document per employee" : "employer-level"}`}
        </p>
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Due dates</p>
        <DueDates calendar={form.filingCalendar} year={form.generator === "dedicated" ? year : undefined} />
      </div>

      {form.generator === "dedicated" ? (
        <div className="rounded-[12px] border border-border bg-background p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <YearSelect years={form.years.map((y) => y.reportingYear)} year={year} setYear={setYear} />
          </div>
          <p className="mt-3 text-[12px] text-foreground-secondary">
            {form.name} has its own {countryName} generator with statutory checks that a payroll-register report
            cannot apply. Generate it from the {countryName} compliance centre.
          </p>
          <Link to="/payroll/compliances" className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary hover:underline">
            Open Compliance <ExternalLink size={13} />
          </Link>
        </div>
      ) : perEmployee ? (
        <EmployeeFormPanel form={form} country={country} onGenerated={onGenerated} />
      ) : (
        <RunFormPanel form={form} country={country} runs={runs} onGenerated={onGenerated} />
      )}
    </div>
  );
}
