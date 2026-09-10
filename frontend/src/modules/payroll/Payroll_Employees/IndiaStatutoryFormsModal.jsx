import { useEffect, useState } from "react";
import Modal from "../../../components/Modal";
import {
  calculateIndiaGratuity,
  listIndiaSalaryTdsDeclarations, createIndiaSalaryTdsDeclaration, submitIndiaSalaryTdsDeclaration, approveIndiaSalaryTdsDeclaration,
  listIndiaSalaryTdsClaims, createIndiaSalaryTdsClaim, submitIndiaSalaryTdsClaim, approveIndiaSalaryTdsClaim, rejectIndiaSalaryTdsClaim,
  listIndiaEmployeeBenefitValuations, createIndiaEmployeeBenefitValuation, issueIndiaEmployeeBenefitValuation,
  getApplicableReportTemplate, generateIndiaForm130, generateIndiaForm123,
} from "../../../service/payrollService";

// India Forms 122/123/124 + Gratuity (ZP-TAX-IN-2026-27-001 §6.2/§11,
// gap-closure Phases D/E, 2026-09-10) management UI. The backend has had a
// complete calculate/CRUD/status API for all four since this session's own
// gap-closure work, with NO frontend anywhere until now — a payroll operator
// had no way to actually enter a prior-employer declaration, a Chapter VIII
// claim, a perquisite value, or calculate gratuity despite the engine being
// fully built. This is that missing screen.

const TABS = [
  { key: "gratuity", label: "Gratuity" },
  { key: "declaration", label: "Form 122 — Declaration" },
  { key: "claims", label: "Form 124 — Claims" },
  { key: "benefits", label: "Form 123 — Benefits" },
];

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";
const selectClass = inputClass;

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

function StatusBadge({ status }) {
  const classes = {
    Draft: "bg-foreground-muted/10 text-foreground-muted",
    Submitted: "bg-warning/10 text-warning",
    Approved: "bg-success/10 text-success",
    Issued: "bg-success/10 text-success",
    Rejected: "bg-error/10 text-error",
    Superseded: "bg-foreground-disabled/10 text-foreground-disabled",
  };
  return (
    <span className={`shrink-0 inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${classes[status] || ""}`}>
      {status}
    </span>
  );
}

function currentIndiaTaxYear() {
  const now = new Date();
  const startYear = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  return `${startYear}-${String(startYear + 1).slice(-2)}`;
}

// "2026-27" -> "2027-03-31" — the FY-end date Form 130's own SUM_YTD
// fields resolve their year-to-date boundary against (india_tax_year_
// for_date's inverse, on the frontend side).
function fyEndDateFor(taxYear) {
  const startYear = Number((taxYear || "").split("-")[0]);
  if (!startYear) return null;
  return `${startYear + 1}-03-31`;
}

// ── Shared: generate a Form 130/123 certificate for this employee ───────
// Resolves the applicable Published/Active template for (reportType,
// taxYear) first — no template picker, matching how the org-facing
// Reports screen already auto-resolves one rather than asking the user
// to pick a template id by hand.
function GenerateCertificateBlock({ reportType, taxYear, buttonLabel, hint, onGenerate }) {
  const [status, setStatus] = useState("idle"); // idle | generating | done | error
  const [message, setMessage] = useState("");

  async function handleGenerate() {
    setStatus("generating");
    setMessage("");
    try {
      const { template } = await getApplicableReportTemplate({ reportingYear: taxYear, reportType });
      if (!template) {
        setStatus("error");
        setMessage(`No Published/Active ${reportType.replace("FORM_", "Form ")} template found for ${taxYear} — a Super Admin needs to author and activate one first (Super Admin > Report Templates).`);
        return;
      }
      const generated = await onGenerate(template.id);
      setStatus("done");
      setMessage(`Generated — report #${generated.id}. See it under this org's Reports screen.`);
    } catch (err) {
      setStatus("error");
      setMessage(err.message || "Could not generate this report.");
    }
  }

  return (
    <div className="mt-4 rounded-[14px] border border-border-light bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[12px] text-foreground-secondary">{hint}</p>
        <button
          onClick={handleGenerate} disabled={status === "generating"}
          className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
        >
          {status === "generating" ? "Generating…" : buttonLabel}
        </button>
      </div>
      {message && <p className={`mt-2 text-[11px] ${status === "error" ? "text-error" : "text-success"}`}>{message}</p>}
    </div>
  );
}

// ── Gratuity ───────────────────────────────────────────────────────────

function GratuitySection({ employee }) {
  const [eligibilityEvent, setEligibilityEvent] = useState("RESIGNATION");
  const [isFixedTerm, setIsFixedTerm] = useState(false);
  const [dateOfLeaving, setDateOfLeaving] = useState("");
  const [lastDrawnWage, setLastDrawnWage] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [calculating, setCalculating] = useState(false);

  async function handleCalculate() {
    setError("");
    setResult(null);
    setCalculating(true);
    try {
      const data = await calculateIndiaGratuity({
        employeeId: employee.id,
        eligibilityEvent,
        isFixedTerm,
        dateOfLeaving: dateOfLeaving || null,
        lastDrawnMonthlyWage: lastDrawnWage || null,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || "Could not calculate gratuity.");
    } finally {
      setCalculating(false);
    }
  }

  return (
    <div>
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        Gratuity is an employer termination liability, not a routine payroll deduction — calculating it here does
        not create a payslip line. Uses the employee's own date of joining and, unless overridden below, their
        stored monthly Basic.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Eligibility event">
          <select className={selectClass} value={eligibilityEvent} onChange={(e) => setEligibilityEvent(e.target.value)}>
            <option value="RETIREMENT">Retirement</option>
            <option value="RESIGNATION">Resignation</option>
            <option value="TERMINATION">Termination</option>
            <option value="DEATH">Death</option>
            <option value="DISABLEMENT">Disablement</option>
            <option value="FIXED_TERM_END">Fixed-term end</option>
          </select>
        </Field>
        <Field label="Fixed-term employee">
          <label className="flex items-center gap-2 pt-2.5 text-[13px] text-foreground">
            <input type="checkbox" checked={isFixedTerm} onChange={(e) => setIsFixedTerm(e.target.checked)} />
            Use pro-rata fixed-term calculation
          </label>
        </Field>
        <Field label="Date of leaving (optional override)" hint="Defaults to the employee's own record if left blank.">
          <input type="date" className={inputClass} value={dateOfLeaving} onChange={(e) => setDateOfLeaving(e.target.value)} />
        </Field>
        <Field label="Last-drawn monthly wage (optional override)" hint="Defaults to the employee's own stored monthly Basic.">
          <input type="number" min="0" step="0.01" className={inputClass} value={lastDrawnWage} onChange={(e) => setLastDrawnWage(e.target.value)} />
        </Field>
      </div>

      {error && <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}

      {result && (
        <div className="mt-4 rounded-[14px] border border-border bg-surface-muted p-4">
          {result.eligible ? (
            <>
              <p className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Gratuity amount</p>
              <p className="mt-1 text-2xl font-bold text-foreground">₹{Number(result.gratuityAmount || result.gratuity_amount || 0).toLocaleString("en-IN")}</p>
            </>
          ) : (
            <p className="text-[13px] font-semibold text-error">Not eligible — {result.reason}</p>
          )}
        </div>
      )}

      <div className="mt-4 flex justify-end">
        <button
          onClick={handleCalculate} disabled={calculating}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {calculating ? "Calculating…" : "Calculate gratuity"}
        </button>
      </div>
    </div>
  );
}

// ── Form 122: Salary TDS Declaration ─────────────────────────────────────

function DeclarationSection({ employee, taxYear }) {
  const [declarations, setDeclarations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ priorEmployerSalary: "", priorEmployerTdsDeducted: "", otherIncome: "", housePropertyLoss: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState(null);

  async function refresh() {
    setLoading(true);
    try {
      const data = await listIndiaSalaryTdsDeclarations(employee.id, taxYear);
      setDeclarations(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Could not load declarations.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employee.id, taxYear]);

  async function handleCreate() {
    setError("");
    setSubmitting(true);
    try {
      await createIndiaSalaryTdsDeclaration({ employeeId: employee.id, taxYear, ...form });
      setForm({ priorEmployerSalary: "", priorEmployerTdsDeducted: "", otherIncome: "", housePropertyLoss: "" });
      setShowForm(false);
      refresh();
    } catch (err) {
      setError(err.message || "Could not save this declaration.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAction(id, action) {
    setBusyId(id);
    try {
      if (action === "submit") await submitIndiaSalaryTdsDeclaration(id);
      else await approveIndiaSalaryTdsDeclaration(id);
      refresh();
    } catch (err) {
      setError(err.message || "Could not update this declaration.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        Prior-employer salary/TDS, other specified income, and house-property loss for {taxYear} — feeds the salary
        TDS projection once Approved. Only the most recently Approved declaration for this tax year is used;
        approving a new one supersedes the last.
      </p>
      {error && <div className="mb-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {loading ? (
        <p className="text-[13px] text-foreground-muted">Loading…</p>
      ) : declarations.length === 0 ? (
        <p className="text-[13px] text-foreground-muted">No declarations recorded for {taxYear}.</p>
      ) : (
        <div className="space-y-2.5 mb-4">
          {declarations.map((d) => (
            <div key={d.id} className="rounded-[14px] border border-border bg-surface-muted p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[12px] text-foreground-secondary">
                  <p>Prior-employer salary: ₹{Number(d.priorEmployerSalary).toLocaleString("en-IN")} · TDS deducted: ₹{Number(d.priorEmployerTdsDeducted).toLocaleString("en-IN")}</p>
                  <p>Other income: ₹{Number(d.otherIncome).toLocaleString("en-IN")} · House-property loss: ₹{Number(d.housePropertyLoss).toLocaleString("en-IN")}</p>
                </div>
                <StatusBadge status={d.status} />
              </div>
              {d.status === "Draft" && (
                <div className="mt-3 flex gap-2 border-t border-border-light pt-3">
                  <button onClick={() => handleAction(d.id, "submit")} disabled={busyId === d.id} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50">
                    Submit
                  </button>
                </div>
              )}
              {d.status === "Submitted" && (
                <div className="mt-3 flex gap-2 border-t border-border-light pt-3">
                  <button onClick={() => handleAction(d.id, "approve")} disabled={busyId === d.id} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-success hover:border-success disabled:opacity-50">
                    Approve
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!showForm ? (
        <button onClick={() => setShowForm(true)} className="w-full rounded-[12px] border border-dashed border-border px-4 py-2.5 text-[13px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary">
          + Add declaration
        </button>
      ) : (
        <div className="rounded-[14px] border border-border p-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Prior-employer salary this year">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.priorEmployerSalary} onChange={(e) => setForm((p) => ({ ...p, priorEmployerSalary: e.target.value }))} />
            </Field>
            <Field label="Prior-employer TDS already deducted">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.priorEmployerTdsDeducted} onChange={(e) => setForm((p) => ({ ...p, priorEmployerTdsDeducted: e.target.value }))} />
            </Field>
            <Field label="Other specified income">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.otherIncome} onChange={(e) => setForm((p) => ({ ...p, otherIncome: e.target.value }))} />
            </Field>
            <Field label="House-property loss">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.housePropertyLoss} onChange={(e) => setForm((p) => ({ ...p, housePropertyLoss: e.target.value }))} />
            </Field>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={handleCreate} disabled={submitting} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {submitting ? "Saving…" : "Save declaration"}
            </button>
          </div>
        </div>
      )}

      <GenerateCertificateBlock
        reportType="FORM_130" taxYear={taxYear} buttonLabel="Generate Form 130 Certificate"
        hint={`Form 130 salary TDS certificate for ${taxYear}, as of FY-end (${fyEndDateFor(taxYear)}).`}
        onGenerate={(templateId) => generateIndiaForm130({ reportTemplateId: templateId, employeeId: employee.id, asOfDate: fyEndDateFor(taxYear) })}
      />
    </div>
  );
}

// ── Form 124: Salary TDS Claims ───────────────────────────────────────────

const CLAIM_TYPES = [
  { value: "SECTION_80C", label: "Section 80C" },
  { value: "HRA_EXEMPTION", label: "HRA Exemption" },
  { value: "HOME_LOAN_INTEREST", label: "Home Loan Interest" },
  { value: "LTA", label: "LTA" },
  { value: "OTHER", label: "Other" },
];

function ClaimsSection({ employee, taxYear }) {
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ claimType: "SECTION_80C", claimedAmount: "", evidenceReference: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [rejectingId, setRejectingId] = useState(null);
  const [rejectReason, setRejectReason] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const data = await listIndiaSalaryTdsClaims(employee.id, taxYear);
      setClaims(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Could not load claims.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employee.id, taxYear]);

  async function handleCreate() {
    setError("");
    if (!form.claimedAmount) { setError("Enter a claimed amount."); return; }
    setSubmitting(true);
    try {
      await createIndiaSalaryTdsClaim({ employeeId: employee.id, taxYear, ...form });
      setForm({ claimType: "SECTION_80C", claimedAmount: "", evidenceReference: "" });
      setShowForm(false);
      refresh();
    } catch (err) {
      setError(err.message || "Could not save this claim.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmitClaim(id) {
    setBusyId(id);
    try { await submitIndiaSalaryTdsClaim(id); refresh(); }
    catch (err) { setError(err.message || "Could not submit this claim."); }
    finally { setBusyId(null); }
  }

  async function handleApprove(id) {
    setBusyId(id);
    try { await approveIndiaSalaryTdsClaim(id); refresh(); }
    catch (err) { setError(err.message || "Could not approve this claim."); }
    finally { setBusyId(null); }
  }

  async function handleReject(id) {
    setBusyId(id);
    try {
      await rejectIndiaSalaryTdsClaim(id, rejectReason || "Not specified");
      setRejectingId(null);
      setRejectReason("");
      refresh();
    } catch (err) {
      setError(err.message || "Could not reject this claim.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        Chapter VIII claims/evidence for {taxYear} — Old Regime only, no per-claim-type ceiling is enforced here
        (the statutory pack gives none). evidence_reference is a free-text pointer — no file upload.
      </p>
      {error && <div className="mb-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {loading ? (
        <p className="text-[13px] text-foreground-muted">Loading…</p>
      ) : claims.length === 0 ? (
        <p className="text-[13px] text-foreground-muted">No claims recorded for {taxYear}.</p>
      ) : (
        <div className="space-y-2.5 mb-4">
          {claims.map((c) => (
            <div key={c.id} className="rounded-[14px] border border-border bg-surface-muted p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[13px] font-bold text-foreground">
                    {CLAIM_TYPES.find((t) => t.value === c.claimType)?.label || c.claimType} — ₹{Number(c.claimedAmount).toLocaleString("en-IN")}
                  </p>
                  {c.evidenceReference && <p className="mt-0.5 text-[12px] text-foreground-muted">Evidence: {c.evidenceReference}</p>}
                  {c.rejectionReason && <p className="mt-0.5 text-[12px] text-error">Rejected: {c.rejectionReason}</p>}
                </div>
                <StatusBadge status={c.status} />
              </div>
              {c.status === "Draft" && (
                <div className="mt-3 flex gap-2 border-t border-border-light pt-3">
                  <button onClick={() => handleSubmitClaim(c.id)} disabled={busyId === c.id} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50">Submit</button>
                </div>
              )}
              {c.status === "Submitted" && (
                <div className="mt-3 border-t border-border-light pt-3">
                  {rejectingId === c.id ? (
                    <div className="flex gap-2">
                      <input className={inputClass} placeholder="Reason for rejection" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
                      <button onClick={() => handleReject(c.id)} disabled={busyId === c.id} className="rounded-lg border border-error px-3 py-1.5 text-[12px] font-semibold text-error disabled:opacity-50">Confirm</button>
                      <button onClick={() => setRejectingId(null)} className="rounded-lg border border-border px-3 py-1.5 text-[12px] text-foreground-secondary">Cancel</button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <button onClick={() => handleApprove(c.id)} disabled={busyId === c.id} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-success hover:border-success disabled:opacity-50">Approve</button>
                      <button onClick={() => setRejectingId(c.id)} disabled={busyId === c.id} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-error hover:border-error disabled:opacity-50">Reject</button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!showForm ? (
        <button onClick={() => setShowForm(true)} className="w-full rounded-[12px] border border-dashed border-border px-4 py-2.5 text-[13px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary">
          + Add claim
        </button>
      ) : (
        <div className="rounded-[14px] border border-border p-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Claim type">
              <select className={selectClass} value={form.claimType} onChange={(e) => setForm((p) => ({ ...p, claimType: e.target.value }))}>
                {CLAIM_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </Field>
            <Field label="Claimed amount">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.claimedAmount} onChange={(e) => setForm((p) => ({ ...p, claimedAmount: e.target.value }))} />
            </Field>
            <div className="col-span-2">
              <Field label="Evidence reference (optional)" hint="Receipt number/description — no file attachment in this build.">
                <input className={inputClass} value={form.evidenceReference} onChange={(e) => setForm((p) => ({ ...p, evidenceReference: e.target.value }))} />
              </Field>
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={handleCreate} disabled={submitting} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {submitting ? "Saving…" : "Save claim"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Form 123: Employee Benefit Valuation ──────────────────────────────────

const BENEFIT_TYPES = [
  { value: "CAR", label: "Car" },
  { value: "ACCOMMODATION", label: "Accommodation" },
  { value: "STOCK_BENEFIT", label: "Stock Benefit" },
  { value: "EMPLOYER_PAID_OBLIGATION", label: "Employer-Paid Obligation" },
  { value: "OTHER", label: "Other" },
];

function BenefitsSection({ employee, taxYear }) {
  const [benefits, setBenefits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ benefitType: "CAR", taxableValue: "", description: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState(null);

  async function refresh() {
    setLoading(true);
    try {
      const data = await listIndiaEmployeeBenefitValuations(employee.id, taxYear);
      setBenefits(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Could not load benefit valuations.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employee.id, taxYear]);

  async function handleCreate() {
    setError("");
    if (!form.taxableValue) { setError("Enter a taxable value."); return; }
    setSubmitting(true);
    try {
      await createIndiaEmployeeBenefitValuation({ employeeId: employee.id, taxYear, ...form });
      setForm({ benefitType: "CAR", taxableValue: "", description: "" });
      setShowForm(false);
      refresh();
    } catch (err) {
      setError(err.message || "Could not save this benefit valuation.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleIssue(id) {
    setBusyId(id);
    try { await issueIndiaEmployeeBenefitValuation(id); refresh(); }
    catch (err) { setError(err.message || "Could not issue this valuation."); }
    finally { setBusyId(null); }
  }

  return (
    <div>
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        Perquisite/profit-in-lieu-of-salary values for {taxYear} — Zoiko does not compute a perquisite's taxable
        value (the statutory pack gives no valuation formula); enter your own already-determined amount. Feeds
        both regimes' taxable income once Issued, and Form 123 generation.
      </p>
      {error && <div className="mb-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{error}</div>}
      {loading ? (
        <p className="text-[13px] text-foreground-muted">Loading…</p>
      ) : benefits.length === 0 ? (
        <p className="text-[13px] text-foreground-muted">No benefit valuations recorded for {taxYear}.</p>
      ) : (
        <div className="space-y-2.5 mb-4">
          {benefits.map((b) => (
            <div key={b.id} className="rounded-[14px] border border-border bg-surface-muted p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[13px] font-bold text-foreground">
                    {BENEFIT_TYPES.find((t) => t.value === b.benefitType)?.label || b.benefitType} — ₹{Number(b.taxableValue).toLocaleString("en-IN")}
                  </p>
                  {b.description && <p className="mt-0.5 text-[12px] text-foreground-muted">{b.description}</p>}
                </div>
                <StatusBadge status={b.status} />
              </div>
              {b.status === "Draft" && (
                <div className="mt-3 flex gap-2 border-t border-border-light pt-3">
                  <button onClick={() => handleIssue(b.id)} disabled={busyId === b.id} className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-success hover:border-success disabled:opacity-50">
                    Issue
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!showForm ? (
        <button onClick={() => setShowForm(true)} className="w-full rounded-[12px] border border-dashed border-border px-4 py-2.5 text-[13px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary">
          + Add benefit valuation
        </button>
      ) : (
        <div className="rounded-[14px] border border-border p-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Benefit type">
              <select className={selectClass} value={form.benefitType} onChange={(e) => setForm((p) => ({ ...p, benefitType: e.target.value }))}>
                {BENEFIT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </Field>
            <Field label="Taxable value">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.taxableValue} onChange={(e) => setForm((p) => ({ ...p, taxableValue: e.target.value }))} />
            </Field>
            <div className="col-span-2">
              <Field label="Description (optional)">
                <input className={inputClass} value={form.description} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} />
              </Field>
            </div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={handleCreate} disabled={submitting} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {submitting ? "Saving…" : "Save valuation"}
            </button>
          </div>
        </div>
      )}

      <GenerateCertificateBlock
        reportType="FORM_123" taxYear={taxYear} buttonLabel="Generate Form 123 Statement"
        hint={`Form 123 employer perquisite statement for ${taxYear}, from Issued valuations above.`}
        onGenerate={(templateId) => generateIndiaForm123({ reportTemplateId: templateId, employeeId: employee.id, taxYear })}
      />
    </div>
  );
}

export default function IndiaStatutoryFormsModal({ employee, onClose }) {
  const [activeTab, setActiveTab] = useState("gratuity");
  const [taxYear] = useState(currentIndiaTaxYear());

  return (
    <Modal title={`India Statutory Forms — ${employee.name}`} onClose={onClose} maxWidth="max-w-2xl">
      <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.key} onClick={() => setActiveTab(t.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${activeTab === t.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "gratuity" && <GratuitySection employee={employee} />}
      {activeTab === "declaration" && <DeclarationSection employee={employee} taxYear={taxYear} />}
      {activeTab === "claims" && <ClaimsSection employee={employee} taxYear={taxYear} />}
      {activeTab === "benefits" && <BenefitsSection employee={employee} taxYear={taxYear} />}

      <div className="mt-5 flex justify-end">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Close</button>
      </div>
    </Modal>
  );
}
