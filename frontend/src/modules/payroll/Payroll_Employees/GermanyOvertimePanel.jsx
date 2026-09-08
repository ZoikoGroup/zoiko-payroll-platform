import React, { useEffect, useState } from "react";
import { X, Clock, ChevronRight } from "lucide-react";
import {
  listGermanyOvertimeWorkRecords, createGermanyOvertimeWorkRecord, setGermanyOvertimeWorkRecordApproval,
  classifyGermanyOvertimeWorkRecord, getGermanyOvertimeClassification,
  calculateGermanyOvertimeWageTax, getGermanyOvertimeWageTaxResult,
  calculateGermanyOvertimeSocialInsurance, getGermanyOvertimeSocialInsuranceResult,
  buildGermanyOvertimePremiumComponents, getGermanyOvertimePremiumComponents,
  attachGermanyOvertimePremiumComponentToPayslip, detachGermanyOvertimePremiumComponentFromPayslip, getPayslips,
  listGermanyOvertimePremiumComponentsForBatchAttach, batchAttachGermanyOvertimePremiumComponentsToPayslips,
} from "../../../service/payrollService";
import { describeLoadError } from "../../../service/errorClassification";
import { describeOvertimeFinancialIntegration } from "../../../service/germanyOvertimeFinancialDisplay";

// Phase 8AI — Germany overtime operator UI. Reads/writes the Phase
// 8AC-8AH backend exactly as built: work-record fact capture →
// statutory classification (no money) → wage-tax calculation (Phase
// 8AF, independent) → social-insurance calculation (Phase 8AG,
// independent) → premium component (Phase 8AH, combines the two) →
// EXPLICIT attach-to-payslip action. Automatic inclusion during
// payroll-run generation is NOT implemented anywhere in this UI — that
// remains a deliberate, disclosed scope boundary (see Phase 8AH/8AI
// reports: the manual-vs-attendance work-record precedence and
// auto-inclusion-policy product decisions remain open). This panel only
// ever calls the EXISTING attach endpoint; it never writes to
// gross pay or any payslip field directly.

const inputCls = "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[12px] text-foreground outline-none focus:border-primary";
const btnPrimary = "rounded-[10px] bg-primary px-3 py-1.5 text-[12px] font-bold text-white transition-colors hover:bg-primary-hover disabled:opacity-50";
const btnSecondary = "rounded-[10px] border border-border bg-surface-muted px-3 py-1.5 text-[12px] font-semibold text-foreground-muted transition-colors hover:border-primary disabled:opacity-50";

function Th({ children }) { return <th className="px-2 py-1.5 text-left font-semibold text-foreground-muted">{children}</th>; }
function Td({ children, className = "" }) { return <td className={`px-2 py-1.5 text-foreground ${className}`}>{children}</td>; }

function StatusPill({ value, tone }) {
  const t = tone || (
    value === "PUBLISHED" || value === "CALCULATED" || value === "COMPLETE" || value === "APPROVED" || value === "CONFIGURED"
      ? "bg-primary/10 text-primary"
      : value === "REJECTED"
      ? "bg-error/10 text-error"
      : "bg-warning/10 text-warning"
  );
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold ${t}`}>{value || "—"}</span>;
}

function ErrorBanner({ message }) {
  if (!message) return null;
  if (typeof message === "object" && message.schemaUnavailable) {
    return (
      <div className="mb-3 rounded-[10px] bg-warning/10 px-3 py-2 text-[12px] text-warning border border-warning/20">
        <span className="font-bold">Configuration unavailable — </span>{message.message}
      </div>
    );
  }
  const text = typeof message === "object" ? message.message : message;
  return <div className="mb-3 rounded-[10px] bg-error/10 px-3 py-2 text-[12px] text-error border border-error/20">{text}</div>;
}

function Section({ title, action, children }) {
  return (
    <div className="rounded-[16px] border border-border bg-surface p-4 mb-4">
      <div className="flex items-center justify-between mb-2.5">
        <h4 className="text-[12px] font-bold uppercase tracking-wide text-foreground-muted">{title}</h4>
        {action}
      </div>
      {children}
    </div>
  );
}

function defaultWorkRecordForm() {
  const today = new Date().toISOString().slice(0, 10);
  return { workDate: today, startTime: "20:00", endTime: "23:30", hours: "3.5" };
}

// ── Work record list + create form ──────────────────────────────────

function WorkRecordsSection({ employeeId, selectedId, onSelect }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(defaultWorkRecordForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [approvalError, setApprovalError] = useState("");

  async function reload() {
    setLoading(true);
    setError("");
    try {
      const data = await listGermanyOvertimeWorkRecords(employeeId);
      setRows(data);
    } catch (err) {
      setError(describeLoadError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employeeId]);

  async function handleCreate(e) {
    e.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      const startDatetime = `${form.workDate}T${form.startTime}:00`;
      // A work record may cross midnight (e.g. 22:00 -> 02:00) — the end
      // date is the day after workDate whenever the end clock time is
      // earlier than the start clock time.
      const crossesMidnight = form.endTime <= form.startTime;
      const endDateObj = new Date(`${form.workDate}T00:00:00`);
      if (crossesMidnight) endDateObj.setDate(endDateObj.getDate() + 1);
      const endDatetime = `${endDateObj.toISOString().slice(0, 10)}T${form.endTime}:00`;
      await createGermanyOvertimeWorkRecord(employeeId, {
        workDate: form.workDate,
        startDatetime,
        endDatetime,
        hours: form.hours,
        entrySource: "MANUAL",
      });
      setShowForm(false);
      setForm(defaultWorkRecordForm());
      await reload();
    } catch (err) {
      setFormError(err.message || "Could not save this work record.");
    } finally {
      setSaving(false);
    }
  }

  async function handleApproval(recordId, status) {
    setApprovalError("");
    try {
      await setGermanyOvertimeWorkRecordApproval(employeeId, recordId, status);
      await reload();
    } catch (err) {
      setApprovalError(err.message || "Could not update approval status.");
    }
  }

  return (
    <Section
      title="Overtime work records"
      action={
        <button type="button" className={btnSecondary} onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New work record"}
        </button>
      }
    >
      <ErrorBanner message={approvalError} />
      {showForm && (
        <form onSubmit={handleCreate} className="mb-3 grid grid-cols-2 gap-2 rounded-[10px] border border-border p-3">
          <ErrorBanner message={formError} />
          <label className="col-span-2">
            <span className="mb-1 block text-[11px] font-semibold text-foreground-muted">Work date</span>
            <input type="date" required className={inputCls} value={form.workDate} onChange={(e) => setForm((s) => ({ ...s, workDate: e.target.value }))} />
          </label>
          <label>
            <span className="mb-1 block text-[11px] font-semibold text-foreground-muted">Start time (local)</span>
            <input type="time" required className={inputCls} value={form.startTime} onChange={(e) => setForm((s) => ({ ...s, startTime: e.target.value }))} />
          </label>
          <label>
            <span className="mb-1 block text-[11px] font-semibold text-foreground-muted">End time (local)</span>
            <input type="time" required className={inputCls} value={form.endTime} onChange={(e) => setForm((s) => ({ ...s, endTime: e.target.value }))} />
          </label>
          <label className="col-span-2">
            <span className="mb-1 block text-[11px] font-semibold text-foreground-muted">Hours worked</span>
            <input type="number" step="0.01" min="0" required className={inputCls} value={form.hours} onChange={(e) => setForm((s) => ({ ...s, hours: e.target.value }))} />
          </label>
          <p className="col-span-2 text-[11px] text-foreground-muted">
            Manual entry only — attendance-derived work records are created automatically elsewhere and are read-only here.
            An end time earlier than the start time is treated as crossing into the next calendar day.
          </p>
          <button type="submit" disabled={saving} className={`${btnPrimary} col-span-2`}>{saving ? "Saving…" : "Save work record"}</button>
        </form>
      )}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">No overtime work records yet.</p>}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr><Th>Date</Th><Th>Start</Th><Th>End</Th><Th>Hours</Th><Th>Source</Th><Th>HR approval</Th><Th>Overlap</Th><Th></Th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={`border-t border-border ${selectedId === r.id ? "bg-primary/5" : ""}`}>
                  <Td>{r.workDate}</Td>
                  <Td>{new Date(r.startDatetime).toLocaleString()}</Td>
                  <Td>{new Date(r.endDatetime).toLocaleString()}</Td>
                  <Td>{r.hours}</Td>
                  <Td>{r.entrySource}</Td>
                  <Td><StatusPill value={r.hrApprovalStatus} /></Td>
                  <Td>
                    {r.overlapStatus === "AMBIGUOUS_OVERLAP" ? (
                      <span
                        className="inline-flex items-center rounded-full bg-error/10 px-2 py-0.5 text-[11px] font-bold text-error"
                        title="This record's time range overlaps another non-rejected overtime record for this employee. The platform never picks a source automatically — reject the incorrect record below to resolve it. Classification is blocked until resolved."
                      >
                        Precedence required
                      </span>
                    ) : (
                      <span className="text-[11px] text-foreground-muted">—</span>
                    )}
                  </Td>
                  <Td>
                    <div className="flex items-center gap-1.5">
                      {r.hrApprovalStatus !== "APPROVED" && (
                        <button className={btnSecondary} onClick={() => handleApproval(r.id, "APPROVED")}>Approve</button>
                      )}
                      {r.hrApprovalStatus !== "REJECTED" && (
                        <button className={btnSecondary} onClick={() => handleApproval(r.id, "REJECTED")}>Reject</button>
                      )}
                      <button className={btnPrimary} onClick={() => onSelect(r.id)}>
                        Review <ChevronRight size={12} className="inline -mt-0.5" />
                      </button>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

// ── Classification / wage-tax / SI / premium-component review ──────────

function ClassificationSection({ employeeId, recordId }) {
  const [segments, setSegments] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  async function reload() {
    setLoading(true);
    setError("");
    try {
      setSegments(await getGermanyOvertimeClassification(employeeId, recordId));
    } catch (err) {
      setError(describeLoadError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employeeId, recordId]);

  async function runClassification() {
    setRunning(true);
    setError("");
    try {
      setSegments(await classifyGermanyOvertimeWorkRecord(employeeId, recordId));
    } catch (err) {
      setError({ message: err.message || "Classification failed.", schemaUnavailable: err.status === 503 });
    } finally {
      setRunning(false);
    }
  }

  return (
    <Section title="Statutory time-window classification (§3b EStG — no money calculated)" action={
      <button className={btnSecondary} disabled={running} onClick={runClassification}>{running ? "Classifying…" : "Classify"}</button>
    }>
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {segments && segments.length === 0 && <p className="text-[12px] text-foreground-muted">Not yet classified.</p>}
      {segments && segments.length > 0 && (
        <table className="w-full text-[12px]">
          <thead><tr><Th>Segment</Th><Th>Hours</Th><Th>Category</Th><Th>Status</Th></tr></thead>
          <tbody>
            {segments.map((s) => (
              <tr key={s.id} className="border-t border-border">
                <Td>{new Date(s.segmentStart).toLocaleTimeString()} – {new Date(s.segmentEnd).toLocaleTimeString()}</Td>
                <Td>{s.hours}</Td>
                <Td>{s.premiumCategory}</Td>
                <Td><StatusPill value={s.classificationStatus} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function WageTaxSection({ employeeId, recordId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  async function reload() {
    setLoading(true); setError("");
    try { setRows(await getGermanyOvertimeWageTaxResult(employeeId, recordId)); }
    catch (err) { setError(describeLoadError(err)); }
    finally { setLoading(false); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employeeId, recordId]);

  async function run() {
    setRunning(true); setError("");
    try { setRows(await calculateGermanyOvertimeWageTax(employeeId, recordId)); }
    catch (err) { setError({ message: err.message || "Calculation failed.", schemaUnavailable: err.status === 503 }); }
    finally { setRunning(false); }
  }

  return (
    <Section title="Wage-tax treatment (§3b EStG — WAGE TAX ONLY)" action={
      <button className={btnSecondary} disabled={running} onClick={run}>{running ? "Calculating…" : "Calculate wage tax"}</button>
    }>
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">Not yet calculated — classify this work record first.</p>}
      {rows && rows.length > 0 && (
        <table className="w-full text-[12px]">
          <thead><tr><Th>Segment</Th><Th>Gross</Th><Th>Tax-free</Th><Th>Taxable</Th><Th>Status</Th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-border">
                <Td>{new Date(r.segmentStart).toLocaleTimeString()} – {new Date(r.segmentEnd).toLocaleTimeString()}</Td>
                <Td>{r.grossQualifyingPremiumAmount ?? "—"}</Td>
                <Td>{r.taxFreePremiumAmount ?? "—"}</Td>
                <Td>{r.taxablePremiumAmount ?? "—"}</Td>
                <Td><StatusPill value={r.calculationStatus} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function SocialInsuranceSection({ employeeId, recordId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  async function reload() {
    setLoading(true); setError("");
    try { setRows(await getGermanyOvertimeSocialInsuranceResult(employeeId, recordId)); }
    catch (err) { setError(describeLoadError(err)); }
    finally { setLoading(false); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employeeId, recordId]);

  async function run() {
    setRunning(true); setError("");
    try { setRows(await calculateGermanyOvertimeSocialInsurance(employeeId, recordId)); }
    catch (err) { setError({ message: err.message || "Calculation failed.", schemaUnavailable: err.status === 503 }); }
    finally { setRunning(false); }
  }

  return (
    <Section title="Social-insurance treatment (§1 SvEV — INDEPENDENT of wage tax)" action={
      <button className={btnSecondary} disabled={running} onClick={run}>{running ? "Calculating…" : "Calculate social insurance"}</button>
    }>
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">Not yet calculated — classify this work record first.</p>}
      {rows && rows.length > 0 && (
        <table className="w-full text-[12px]">
          <thead><tr><Th>Segment</Th><Th>Gross</Th><Th>SI-exempt</Th><Th>SI-contributory</Th><Th>Status</Th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-border">
                <Td>{new Date(r.segmentStart).toLocaleTimeString()} – {new Date(r.segmentEnd).toLocaleTimeString()}</Td>
                <Td>{r.grossQualifyingPremiumAmount ?? "—"}</Td>
                <Td>{r.siFreePremiumAmount ?? "—"}</Td>
                <Td>{r.siContributoryPremiumAmount ?? "—"}</Td>
                <Td><StatusPill value={r.calculationStatus} /></Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}

function AttachRow({ employeeId, recordId, component, onAttached }) {
  const [payslips, setPayslips] = useState(null);
  const [selected, setSelected] = useState("");
  const [attaching, setAttaching] = useState(false);
  const [detaching, setDetaching] = useState(false);
  const [error, setError] = useState("");
  const [showPicker, setShowPicker] = useState(false);

  async function openPicker() {
    setShowPicker(true);
    setError("");
    if (payslips === null) {
      const list = await getPayslips({ employeeId });
      setPayslips(list);
    }
  }

  async function attach() {
    if (!selected) return;
    setAttaching(true);
    setError("");
    try {
      const updated = await attachGermanyOvertimePremiumComponentToPayslip(employeeId, recordId, component.id, Number(selected));
      setShowPicker(false);
      onAttached(updated);
    } catch (err) {
      setError(err.message || "Could not attach this component to the selected payslip.");
    } finally {
      setAttaching(false);
    }
  }

  // Phase 8AQ — attachmentStatus (NEVER_ATTACHED/ATTACHED/DETACHED) is
  // authoritative; payslipAllowanceItemId is a historical pointer only
  // (it stays set even after detach, so it must never be used alone to
  // decide "is this currently attached").
  async function detach() {
    setDetaching(true);
    setError("");
    try {
      const updated = await detachGermanyOvertimePremiumComponentFromPayslip(employeeId, recordId, component.id);
      onAttached(updated);
    } catch (err) {
      setError(err.message || "Could not detach this component from its payslip.");
    } finally {
      setDetaching(false);
    }
  }

  if (component.attachmentStatus === "ATTACHED") {
    // Phase 8AT: surface the financial-integration outcome the backend has
    // computed since Phase 8AR (financialIntegrationStatus/appliedGrossDelta/
    // appliedPfDelta/appliedEsiDelta were already returned by the API but
    // never rendered here) — an operator could previously see only "Active"
    // with no way to tell, from this panel, whether the payslip's gross/SI
    // were actually updated or whether wage tax is still pending PAP. Phase
    // 8AU: extracted into the shared FinancialIntegrationSummary component
    // so the batch attach view (further down this file) shows the same
    // information rather than duplicating this markup.
    return (
      <div>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold text-primary">Active (payslip line #{component.payslipAllowanceItemId})</span>
          <button className={btnSecondary} disabled={detaching} onClick={detach}>{detaching ? "Detaching…" : "Detach"}</button>
        </div>
        <FinancialIntegrationSummary component={component} />
        <ErrorBanner message={error} />
      </div>
    );
  }
  if (component.combinationStatus !== "COMPLETE") {
    return <span className="text-[11px] text-foreground-muted" title="Only a COMPLETE component (both wage-tax and social-insurance dimensions calculated and reconciled) may be attached">Not attachable</span>;
  }
  return (
    <div>
      {component.attachmentStatus === "DETACHED" && (
        <p className="mb-1 text-[11px] text-warning">Previously detached — attaching again starts a new attach record.</p>
      )}
      {!showPicker ? (
        <button className={btnSecondary} onClick={openPicker}>Attach to payslip</button>
      ) : (
        <div className="flex items-center gap-1.5">
          <select className={inputCls} value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">Select payslip…</option>
            {(payslips || []).map((p) => (
              <option key={p.id} value={p.id}>{p.period} — {p.payslipNumber || `#${p.id}`}</option>
            ))}
          </select>
          <button className={btnPrimary} disabled={attaching || !selected} onClick={attach}>{attaching ? "Attaching…" : "Confirm"}</button>
          <button className={btnSecondary} onClick={() => setShowPicker(false)}>Cancel</button>
        </div>
      )}
      <ErrorBanner message={error} />
    </div>
  );
}

function PremiumComponentsSection({ employeeId, recordId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  async function reload() {
    setLoading(true); setError("");
    try { setRows(await getGermanyOvertimePremiumComponents(employeeId, recordId)); }
    catch (err) { setError(describeLoadError(err)); }
    finally { setLoading(false); }
  }
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employeeId, recordId]);

  async function run() {
    setRunning(true); setError("");
    try { setRows(await buildGermanyOvertimePremiumComponents(employeeId, recordId)); }
    catch (err) { setError({ message: err.message || "Could not build premium components.", schemaUnavailable: err.status === 503 }); }
    finally { setRunning(false); }
  }

  function replaceRow(updated) {
    setRows((prev) => (prev || []).map((r) => (r.id === updated.id ? updated : r)));
  }

  return (
    <Section title="Overtime premium components (combines wage-tax + social-insurance)" action={
      <button className={btnSecondary} disabled={running} onClick={run}>{running ? "Building…" : "Build / rebuild"}</button>
    }>
      <p className="mb-2 text-[11px] text-foreground-muted">
        Attaching to a payslip is always an explicit action here — this platform does not automatically include
        overtime premiums when a payroll run is generated. Only a work record with HR approval status
        <span className="font-semibold"> APPROVED</span>, and a component whose wage-tax and social-insurance
        results agree (status <span className="font-semibold">COMPLETE</span>), can be attached.
      </p>
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">No premium components yet — calculate wage tax and/or social insurance first, then build.</p>}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr>
                <Th>Segment</Th><Th>Gross</Th><Th>Wage-tax free</Th><Th>Wage-taxable</Th><Th>SI-exempt</Th><Th>SI-contributory</Th><Th>Status</Th><Th>Payslip</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t border-border">
                  <Td>{new Date(c.segmentStart).toLocaleTimeString()} – {new Date(c.segmentEnd).toLocaleTimeString()}</Td>
                  <Td>{c.grossPremiumAmount ?? "—"}</Td>
                  <Td>{c.wageTaxFreeAmount ?? "—"}</Td>
                  <Td>{c.wageTaxableAmount ?? "—"}</Td>
                  <Td>{c.siExemptAmount ?? "—"}</Td>
                  <Td>{c.siContributoryAmount ?? "—"}</Td>
                  <Td><StatusPill value={c.combinationStatus} /></Td>
                  <Td><AttachRow employeeId={employeeId} recordId={recordId} component={c} onAttached={replaceRow} /></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

// ── Batch attach across employees (Phase 8AO) ───────────────────────
// Still explicit/operator-initiated — nothing here is automatic. The
// operator reviews a filtered list of eligible components (across
// employees, unlike PremiumComponentsSection above which is scoped to
// one work record), picks which ones to attach and to which payslip,
// then confirms — every pair is re-validated server-side exactly like
// the single-attach action, regardless of what this screen displays.

// Phase 8AU — shared with both the single-attach AttachRow and the batch
// views below: renders the financial-integration outcome
// (financialIntegrationStatus/appliedGrossDelta/appliedPfDelta/
// appliedEsiDelta) the backend has returned since Phase 8AR but which,
// until now, only the single-attach view (fixed in Phase 8AT) displayed.
function FinancialIntegrationSummary({ component }) {
  const info = describeOvertimeFinancialIntegration(component);
  if (!info.hasData) return null;
  return (
    <div>
      {!info.isReversed && (
        <p className="text-[11px] text-foreground-muted">
          Applied: gross +{info.appliedGrossDelta ?? "0.00"}, RV +{info.appliedPfDelta ?? "0.00"}, ALV/GKV +{info.appliedEsiDelta ?? "0.00"}
        </p>
      )}
      {info.isPendingPap && (
        <p className="text-[11px] text-warning" title="Social insurance is fully applied; wage tax cannot be finalized while PAP is unavailable">
          Wage tax pending PAP
        </p>
      )}
      {info.isReversed && <p className="text-[11px] text-foreground-muted">Financially reversed</p>}
    </div>
  );
}

function BatchResultSummary({ result }) {
  if (!result) return null;
  const buckets = [
    ["attached", "Attached", "text-primary"],
    ["alreadyAttached", "Already attached", "text-foreground-muted"],
    ["rejected", "Rejected", "text-warning"],
    ["invalid", "Invalid", "text-error"],
    ["failed", "Failed", "text-error"],
  ];
  return (
    <div className="mb-3 rounded-[10px] border border-border p-3">
      <p className="mb-2 text-[12px] font-bold text-foreground">Batch result</p>
      <div className="mb-2 flex flex-wrap gap-3 text-[12px]">
        {buckets.map(([key, label, cls]) => (
          <span key={key} className={`font-semibold ${cls}`}>{label}: {(result[key] || []).length}</span>
        ))}
      </div>
      {/* Phase 8AU: the "attached" bucket's rows already carry the full
          component payload (result.attached[i].component) — including
          financialIntegrationStatus/appliedGrossDelta/appliedPfDelta/
          appliedEsiDelta since Phase 8AR — but it was never rendered here. */}
      {(result.attached || []).length > 0 && (
        <div className="mb-1.5">
          <p className="text-[11px] font-semibold text-foreground-muted">Attached:</p>
          <ul className="ml-3 list-disc text-[11px] text-foreground-muted">
            {result.attached.map((row, i) => (
              <li key={i}>
                Component #{row.componentId} → payslip #{row.payslipItemId}
                <FinancialIntegrationSummary component={row.component} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {buckets
        .filter(([key]) => key !== "attached" && (result[key] || []).length > 0)
        .map(([key, label]) => (
          <div key={key} className="mb-1.5">
            <p className="text-[11px] font-semibold text-foreground-muted">{label}:</p>
            <ul className="ml-3 list-disc text-[11px] text-foreground-muted">
              {result[key].map((row, i) => (
                <li key={i}>Component #{row.componentId} → payslip #{row.payslipItemId}: {row.reason}</li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  );
}

function BatchAttachSection({ employee }) {
  const [scopeAllEmployees, setScopeAllEmployees] = useState(false);
  const [attachmentState, setAttachmentState] = useState("UNATTACHED");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState({}); // componentId -> true
  const [payslipChoice, setPayslipChoice] = useState({}); // componentId -> payslipItemId
  const [payslipsByEmployee, setPayslipsByEmployee] = useState({}); // employeeId -> [payslip]
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  async function reload() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await listGermanyOvertimePremiumComponentsForBatchAttach({
        employeeId: scopeAllEmployees ? undefined : employee.id,
        attachmentState: attachmentState || undefined,
      });
      setRows(data);
      setSelected({});
    } catch (err) {
      setError(describeLoadError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [scopeAllEmployees, attachmentState]);

  async function ensurePayslipsLoaded(employeeId) {
    if (payslipsByEmployee[employeeId]) return payslipsByEmployee[employeeId];
    const list = await getPayslips({ employeeId });
    setPayslipsByEmployee((prev) => ({ ...prev, [employeeId]: list }));
    return list;
  }

  function toggleRow(row) {
    setSelected((prev) => ({ ...prev, [row.id]: !prev[row.id] }));
    if (!payslipsByEmployee[row.employeeId]) ensurePayslipsLoaded(row.employeeId);
  }

  async function submit() {
    const items = (rows || [])
      .filter((r) => selected[r.id] && payslipChoice[r.id])
      .map((r) => ({ componentId: r.id, payslipItemId: Number(payslipChoice[r.id]) }));
    if (items.length === 0) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await batchAttachGermanyOvertimePremiumComponentsToPayslips(items);
      setResult(res);
      await reload();
    } catch (err) {
      setError(err.message || "Batch attach failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const selectedCount = Object.values(selected).filter(Boolean).length;
  const readyCount = (rows || []).filter((r) => selected[r.id] && payslipChoice[r.id]).length;

  return (
    <Section
      title="Batch attach to payslips"
      action={<button className={btnSecondary} disabled={loading} onClick={reload}>{loading ? "Loading…" : "Refresh"}</button>}
    >
      <p className="mb-2 text-[11px] text-foreground-muted">
        Review eligible overtime premium components and explicitly attach the ones you select to a payslip.
        This is still an explicit, operator-initiated action for every component — the platform never attaches
        anything automatically, and every selection is re-validated on the server regardless of what this screen shows.
      </p>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-[11px] font-semibold text-foreground-muted">
          <input type="checkbox" checked={scopeAllEmployees} onChange={(e) => setScopeAllEmployees(e.target.checked)} />
          All employees in this organization
        </label>
        <label className="flex items-center gap-1.5 text-[11px] font-semibold text-foreground-muted">
          Attachment state
          <select className={inputCls} style={{ width: "auto" }} value={attachmentState} onChange={(e) => setAttachmentState(e.target.value)}>
            <option value="UNATTACHED">Unattached only (never attached or detached)</option>
            <option value="ATTACHED">Active only</option>
            <option value="DETACHED">Detached only</option>
            <option value="">All</option>
          </select>
        </label>
      </div>

      <ErrorBanner message={error} />
      <BatchResultSummary result={result} />

      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">No components match this filter.</p>}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr>
                <Th></Th><Th>Employee</Th><Th>Date</Th><Th>Gross</Th><Th>Status</Th><Th>Attachment</Th><Th>Payslip</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                // Phase 8AQ — attachmentStatus is authoritative (ATTACHED
                // means currently on a payslip; DETACHED means it was,
                // but no longer is, and is once again eligible to attach).
                const attachable = r.combinationStatus === "COMPLETE" && r.attachmentStatus !== "ATTACHED";
                return (
                  <tr key={r.id} className="border-t border-border">
                    <Td>
                      <input
                        type="checkbox" disabled={!attachable}
                        checked={!!selected[r.id]} onChange={() => toggleRow(r)}
                      />
                    </Td>
                    <Td>{r.employeeName || `Employee #${r.employeeId}`}</Td>
                    <Td>{r.workDateLocal}</Td>
                    <Td>{r.grossPremiumAmount ?? "—"}</Td>
                    <Td><StatusPill value={r.combinationStatus} /></Td>
                    <Td>
                      {r.attachmentStatus === "ATTACHED" && (
                        <div>
                          <span className="text-[11px] font-semibold text-primary">Active (line #{r.payslipAllowanceItemId})</span>
                          <FinancialIntegrationSummary component={r} />
                        </div>
                      )}
                      {r.attachmentStatus === "DETACHED" && (
                        <div>
                          <span className="text-[11px] font-semibold text-warning">Detached</span>
                          <FinancialIntegrationSummary component={r} />
                        </div>
                      )}
                      {(!r.attachmentStatus || r.attachmentStatus === "NEVER_ATTACHED") && (
                        <span className="text-[11px] text-foreground-muted">Unattached</span>
                      )}
                    </Td>
                    <Td>
                      {attachable && selected[r.id] && (
                        <select
                          className={inputCls}
                          value={payslipChoice[r.id] || ""}
                          onChange={(e) => setPayslipChoice((prev) => ({ ...prev, [r.id]: e.target.value }))}
                        >
                          <option value="">Select payslip…</option>
                          {(payslipsByEmployee[r.employeeId] || []).map((p) => (
                            <option key={p.id} value={p.id}>{p.period} — {p.payslipNumber || `#${p.id}`}</option>
                          ))}
                        </select>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          <button className={btnPrimary} disabled={submitting || readyCount === 0} onClick={submit}>
            {submitting ? "Attaching…" : `Attach selected (${readyCount})`}
          </button>
          {selectedCount > readyCount && (
            <span className="text-[11px] text-warning">{selectedCount - readyCount} selected but missing a payslip choice.</span>
          )}
        </div>
      )}
    </Section>
  );
}

// ── Panel shell ──────────────────────────────────────────────────────

export default function GermanyOvertimePanel({ employee, onClose }) {
  const [selectedRecordId, setSelectedRecordId] = useState(null);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-3xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <h2 className="flex items-center gap-2 text-[15px] font-bold text-foreground">
            <Clock size={16} /> Germany overtime / shift premium — {employee.name}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="border border-border bg-surface-muted rounded-[12px] p-2 text-foreground-muted transition-all duration-200 hover:border-primary hover:text-primary"
          >
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          <WorkRecordsSection employeeId={employee.id} selectedId={selectedRecordId} onSelect={setSelectedRecordId} />
          {selectedRecordId && (
            <>
              <ClassificationSection employeeId={employee.id} recordId={selectedRecordId} />
              <WageTaxSection employeeId={employee.id} recordId={selectedRecordId} />
              <SocialInsuranceSection employeeId={employee.id} recordId={selectedRecordId} />
              <PremiumComponentsSection employeeId={employee.id} recordId={selectedRecordId} />
            </>
          )}
          <BatchAttachSection employee={employee} />
        </div>
      </div>
    </div>
  );
}
