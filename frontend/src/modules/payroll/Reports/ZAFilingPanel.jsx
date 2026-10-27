import { useState } from "react";
import {
  approveZaArtifact, approveZaVariance, getZaCoidaEvidence, listZaArtifacts, listZaSarsPayments, listZaVariances,
  previewZaCertificates, previewZaEmp201, previewZaReconciliation, proposeZaVariance, recordZaArtifactReceipt,
  recordZaEmp201, recordZaReconciliation, recordZaSarsPayment, reverseZaSarsPayment, submitZaArtifact,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/southAfrica/zaFormat";
import { Table } from "../../../components/jurisdiction/southAfrica/zaShared";

// South Africa SARS filing (ZP-ZA-ENG-001 Phase 8; "ZA" — "SA" is Saudi Arabia).
// Export-and-evidence only (ZA-002): nothing here talks to SARS. Declarations
// are built from committed payroll; every artefact is versioned and approved by
// a second person; SARS's answer is recorded, never invented (ZA-019/ZA-020).
// ETI is the employer's incentive — never an employee deduction (ZA-010).

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const btnPrimary = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const MEASURES = ["PAYROLL_VS_EMP201", "EMP201_VS_PAYMENT", "CERTIFICATES_VS_EMP201"];

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function currentTaxYear() {
  const d = new Date();
  return String(d.getMonth() >= 2 ? d.getFullYear() + 1 : d.getFullYear());
}

function useRun(onDone) {
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const run = async (fn, ok) => {
    setState({ busy: true, error: null, notice: null });
    try {
      const result = await fn();
      setState({ busy: false, error: null, notice: ok });
      onDone?.();
      return result;
    } catch (e) {
      setState({ busy: false, error: e?.message || "The action failed.", notice: null });
      return null;
    }
  };
  return [state, run];
}

function Status({ state }) {
  return (
    <>
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </>
  );
}

function Section({ title, hint, children, testId }) {
  return (
    <section className={card} data-testid={testId}>
      <h3 className="text-[14px] font-semibold text-foreground">{title}</h3>
      {hint && <p className="mb-3 text-[12px] text-foreground-muted">{hint}</p>}
      {children}
    </section>
  );
}

function Emp201Section({ onRecorded }) {
  const [month, setMonth] = useState(thisMonth());
  const [preview, setPreview] = useState(null);
  const [state, run] = useRun(onRecorded);
  const load = () => run(async () => setPreview(await previewZaEmp201(month)), null);
  return (
    <Section testId="za-emp201" title="EMP201 — monthly declaration"
      hint="Built from approved (committed) payroll only. Due on the 7th of the following month, moved to the preceding business day; without a South African public-holiday calendar the due date is blocked, never assumed.">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelCls}>Month<input type="month" className={input} value={month} onChange={(e) => setMonth(e.target.value)} /></label>
        <button type="button" className={btn} disabled={state.busy} onClick={load}>Preview</button>
        <button type="button" className={btnPrimary} disabled={state.busy || !preview}
          onClick={() => run(() => recordZaEmp201(month), "EMP201 recorded — a second person must approve it.")}>
          Record declaration
        </button>
      </div>
      <div className="mt-3"><Status state={state} /></div>
      {preview && (
        <dl className="mt-3 grid grid-cols-2 gap-2 text-[12px] sm:grid-cols-4">
          {[["PAYE", preview.paye], ["SDL (employer)", preview.sdl], ["UIF (employee + employer)", preview.uif],
            ["ETI available (employer)", preview.etiAvailable], ["ETI utilised", preview.etiUtilised],
            ["Amount due", preview.amountDue], ["Due date", preview.dueDate || "BLOCKED"],
            ["Employees", preview.employeeCount]].map(([k, v]) => (
            <div key={k}><dt className="text-foreground-muted">{k}</dt><dd className="font-mono text-foreground">{v}</dd></div>
          ))}
        </dl>
      )}
      {preview?.dueDateBlockedReason && <p className="mt-2 text-[12px] text-error">{preview.dueDateBlockedReason}</p>}
      {(preview?.warnings || []).map((w) => <p key={w} className="mt-1 text-[12px] text-foreground-muted">{w}</p>)}
    </Section>
  );
}

function ArtifactsSection() {
  const [rows, error, loading, reload] = useLoad(() => listZaArtifacts());
  const [state, run] = useRun(reload);
  const [receipt, setReceipt] = useState({});
  return (
    <Section testId="za-artifacts" title="SARS artefacts — every version"
      hint="A correction is a new version that supersedes the old one; a submitted or rejected payload is never edited.">
      <Status state={state} />
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No artefacts yet."
          columns={[
            { label: "Type", key: "artifact_type" },
            { label: "Period", key: "period_key" },
            { label: "Version", key: "version" },
            { label: "Validation", render: (r) => r.validation_status + ((r.validation_errors || []).length ? ` — ${r.validation_errors.map((e) => e.code).join(", ")}` : "") },
            { label: "Status", key: "status" },
            { label: "Channel", key: "submission_channel" },
            { label: "Receipt", key: "receipt_ref" },
            {
              label: "",
              render: (r) => (
                <div className="flex flex-wrap gap-2">
                  {r.status === "VALIDATED" && (
                    <button type="button" className={btn} disabled={state.busy}
                      onClick={() => run(() => approveZaArtifact(r.id), "Approved.")}>Approve</button>
                  )}
                  {r.status === "APPROVED" && ["EASYFILE", "EFILING"].map((c) => (
                    <button key={c} type="button" className={btn} disabled={state.busy}
                      onClick={() => run(() => submitZaArtifact(r.id, c), `Recorded as submitted via ${c}.`)}>Submitted via {c}</button>
                  ))}
                  {r.status === "SUBMITTED" && (
                    <>
                      <input className={input} placeholder="SARS receipt reference" value={receipt[r.id] || ""}
                        onChange={(e) => setReceipt((s) => ({ ...s, [r.id]: e.target.value }))} />
                      <button type="button" className={btn} disabled={state.busy}
                        onClick={() => run(() => recordZaArtifactReceipt(r.id, { accepted: true, receiptRef: receipt[r.id] }), "Accepted by SARS.")}>Accepted</button>
                      <button type="button" className={btn} disabled={state.busy}
                        onClick={() => run(() => recordZaArtifactReceipt(r.id, { accepted: false, rawResponse: { note: receipt[r.id] || "rejected" } }), "Rejection recorded — prepare a corrected version.")}>Rejected</button>
                    </>
                  )}
                </div>
              ),
            },
          ]} />
      )}
    </Section>
  );
}

const PAY_BLANK = { periodKey: thisMonth(), paidOn: "", amount: "", paymentReference: "", paye: "", sdl: "", uif: "", evidenceRef: "" };

function PaymentsSection({ onChanged }) {
  const [rows, error, loading, reload] = useLoad(listZaSarsPayments);
  const [form, setForm] = useState(PAY_BLANK);
  const [state, run] = useRun(() => { reload(); onChanged?.(); });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      await recordZaSarsPayment({
        periodKey: form.periodKey, paidOn: form.paidOn, amount: form.amount, paymentReference: form.paymentReference,
        evidenceRef: form.evidenceRef || null,
        allocation: Object.fromEntries(["paye", "sdl", "uif"].filter((k) => form[k] !== "").map((k) => [k, form[k]])),
      });
      setForm(PAY_BLANK);
    }, "Payment recorded.");
  };
  return (
    <Section testId="za-sars-payments" title="Payments to SARS"
      hint="Record each payment with its PRN; the PAYE / SDL / UIF allocation must add up to the amount. A mistake is reversed, never edited.">
      <Status state={state} />
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No payments recorded."
          columns={[
            { label: "Period", key: "period_key" }, { label: "Paid on", key: "paid_on" },
            { label: "Amount", key: "amount" }, { label: "PRN", key: "payment_reference" },
            { label: "Allocation", render: (r) => Object.entries(r.allocation || {}).map(([k, v]) => `${k.toUpperCase()} ${v}`).join(" · ") },
            { label: "Status", key: "status" },
            { label: "", render: (r) => (r.status !== "REVERSED" ? (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => run(() => reverseZaSarsPayment(r.id), "Payment reversed.")}>Reverse</button>) : null) },
          ]} />
      )}
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-4" aria-label="Record a SARS payment">
        <label className={labelCls}>Period<input type="month" required className={input} value={form.periodKey} onChange={set("periodKey")} /></label>
        <label className={labelCls}>Paid on<input type="date" required className={input} value={form.paidOn} onChange={set("paidOn")} /></label>
        <label className={labelCls}>Amount (ZAR)<input type="number" min="0.01" step="0.01" required className={input} value={form.amount} onChange={set("amount")} /></label>
        <label className={labelCls}>PRN<input required className={input} value={form.paymentReference} onChange={set("paymentReference")} /></label>
        <label className={labelCls}>PAYE part<input type="number" step="0.01" className={input} value={form.paye} onChange={set("paye")} /></label>
        <label className={labelCls}>SDL part<input type="number" step="0.01" className={input} value={form.sdl} onChange={set("sdl")} /></label>
        <label className={labelCls}>UIF part<input type="number" step="0.01" className={input} value={form.uif} onChange={set("uif")} /></label>
        <label className={labelCls}>Evidence reference<input className={input} value={form.evidenceRef} onChange={set("evidenceRef")} /></label>
        <div className="flex items-end"><button type="submit" className={btnPrimary} disabled={state.busy}>Record payment</button></div>
      </form>
    </Section>
  );
}

function ReconciliationSection({ onRecorded }) {
  const [year, setYear] = useState(currentTaxYear());
  const [kind, setKind] = useState("INTERIM");
  const period = `${year}-${kind}`;
  const [report, setReport] = useState(null);
  const [variances, setVariances] = useState([]);
  const [variance, setVariance] = useState({ monthKey: "", measure: MEASURES[1], amount: "", reason: "" });
  const refresh = async () => {
    setReport(await previewZaReconciliation(period));
    setVariances(await listZaVariances(period));
  };
  const [state, run] = useRun(refresh);
  return (
    <Section testId="za-reconciliation" title="EMP501 reconciliation"
      hint="Payroll = EMP201 = payment = certificates for every month, or an explained variance approved by a second person. Only a READY reconciliation can be recorded.">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelCls}>Tax year (ending Feb)<input className={input} value={year} onChange={(e) => setYear(e.target.value)} /></label>
        <label className={labelCls}>Kind
          <select className={input} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="INTERIM">Interim (Mar–Aug)</option><option value="ANNUAL">Annual (Mar–Feb)</option>
          </select>
        </label>
        <button type="button" className={btn} disabled={state.busy} onClick={() => run(refresh, null)}>Check balance</button>
        <button type="button" className={btnPrimary} disabled={state.busy || report?.status !== "READY"}
          onClick={() => run(async () => { await recordZaReconciliation(period); onRecorded?.(); }, "EMP501 recorded — a second person must approve it.")}>
          Record EMP501
        </button>
      </div>
      <div className="mt-3"><Status state={state} /></div>
      {report && (
        <>
          <p className={`mt-2 text-[13px] font-semibold ${report.status === "READY" ? "text-success" : "text-error"}`}>{report.status}</p>
          <Table rows={report.months} rowKey={(r) => r.month}
            columns={[
              { label: "Month", key: "month" }, { label: "Payroll", key: "payroll" }, { label: "EMP201", key: "emp201" },
              { label: "Amount due", key: "emp201AmountDue" }, { label: "Paid", key: "paid" },
              { label: "Differences", render: (r) => Object.entries(r.differences).filter(([, v]) => Number(v) !== 0).map(([k, v]) => `${k} ${v}`).join(" · ") || "—" },
            ]} />
          <p className="mt-2 text-[12px] text-foreground-muted">
            Certificates PAYE {report.certificatesPaye} vs EMP201 PAYE {report.emp201PayeTotal} ({report.certificateCount} certificates)
          </p>
          {report.issues.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-[12px] text-error">
              {report.issues.map((i) => <li key={`${i.month}-${i.measure}`}>{i.month} · {i.measure} {i.difference ?? (i.employees || []).join(", ")}</li>)}
            </ul>
          )}
        </>
      )}
      <h4 className="mt-4 text-[12px] font-semibold text-foreground">Variances for {period}</h4>
      <Table rows={variances} empty="No variances."
        columns={[
          { label: "Month", key: "month_key" }, { label: "Measure", key: "measure" }, { label: "Amount", key: "amount" },
          { label: "Reason", key: "reason" }, { label: "Status", key: "status" },
          { label: "", render: (v) => (v.status === "PROPOSED" ? (
            <button type="button" className={btn} disabled={state.busy}
              onClick={() => run(() => approveZaVariance(v.id), "Variance approved.")}>Approve</button>) : null) },
        ]} />
      <form className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-5" aria-label="Propose a variance"
        onSubmit={(e) => { e.preventDefault(); run(() => proposeZaVariance(period, variance), "Variance proposed — a second person must approve it."); }}>
        <label className={labelCls}>Month (YYYY-MM or ALL)<input required className={input} value={variance.monthKey} onChange={(e) => setVariance((v) => ({ ...v, monthKey: e.target.value }))} /></label>
        <label className={labelCls}>Measure
          <select className={input} value={variance.measure} onChange={(e) => setVariance((v) => ({ ...v, measure: e.target.value }))}>
            {MEASURES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <label className={labelCls}>Difference<input type="number" step="0.01" required className={input} value={variance.amount} onChange={(e) => setVariance((v) => ({ ...v, amount: e.target.value }))} /></label>
        <label className={labelCls}>Explanation<input required className={input} value={variance.reason} onChange={(e) => setVariance((v) => ({ ...v, reason: e.target.value }))} /></label>
        <div className="flex items-end"><button type="submit" className={btn} disabled={state.busy}>Propose variance</button></div>
      </form>
    </Section>
  );
}

function CertificatesSection() {
  const [period, setPeriod] = useState(`${currentTaxYear()}-ANNUAL`);
  const [data, setData] = useState(null);
  const [state, run] = useRun(null);
  return (
    <Section testId="za-certificates" title="IRP5 / IT3(a) certificates"
      hint="Canonical certificate lines only. SARS source codes come from the official BRS catalogue and are never guessed.">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelCls}>Period<input className={input} value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2027-ANNUAL" /></label>
        <button type="button" className={btn} disabled={state.busy} onClick={() => run(async () => setData(await previewZaCertificates(period)), null)}>Preview</button>
      </div>
      <div className="mt-3"><Status state={state} /></div>
      {data?.brs?.status === "BLOCKED" && (
        <p className="mt-2 rounded-lg border border-dashed border-border bg-surface-muted p-2 text-[12px] text-error" data-testid="za-brs-blocked">
          SARS BRS mapping blocked: {data.brs.reason}
        </p>
      )}
      {data && (
        <Table rows={data.certificates} rowKey={(c) => c.employeeId}
          columns={[
            { label: "Employee", key: "employeeName" }, { label: "Tax number", key: "taxNumberMasked" },
            { label: "Type", key: "certificateType" },
            { label: "Lines", render: (c) => Object.entries(c.lines).filter(([, v]) => Number(v) !== 0).map(([k, v]) => `${k} ${v}`).join(" · ") },
            { label: "Validation", render: (c) => c.validation + (c.errors.length ? ` — ${c.errors.join("; ")}` : "") },
          ]} />
      )}
    </Section>
  );
}

function CoidaSection() {
  const [year, setYear] = useState(currentTaxYear());
  const [data, setData] = useState(null);
  const [state, run] = useRun(null);
  const download = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `za-coida-roe-evidence-${year}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Section testId="za-coida" title="COIDA return-of-earnings evidence"
      hint="Earnings and worker counts for the March–February assessment year. Evidence only — no assessment rate is applied.">
      <div className="flex flex-wrap items-end gap-3">
        <label className={labelCls}>Assessment year (ending Feb)<input className={input} value={year} onChange={(e) => setYear(e.target.value)} /></label>
        <button type="button" className={btn} disabled={state.busy} onClick={() => run(async () => setData(await getZaCoidaEvidence(year)), null)}>Build</button>
        <button type="button" className={btn} disabled={!data} onClick={download}>Download JSON</button>
      </div>
      <div className="mt-3"><Status state={state} /></div>
      {data && (
        <p className="mt-2 text-[12px] text-foreground">
          Total earnings {data.totalEarnings} · COIDA reference {data.coidaReference || "not recorded"}
          {Object.keys(data.unclassifiedEarnings || {}).length > 0 && (
            <span className="text-error"> · unclassified: {Object.entries(data.unclassifiedEarnings).map(([k, v]) => `${k} ${v}`).join(", ")}</span>
          )}
        </p>
      )}
    </Section>
  );
}

export default function ZAFilingPanel() {
  const [reloadKey, setReloadKey] = useState(0);
  const bump = () => setReloadKey((k) => k + 1);
  return (
    <div className="flex flex-col gap-4" data-testid="za-filing-panel">
      <div>
        <h2 className="text-[16px] font-semibold text-foreground">South Africa — SARS filing</h2>
        <p className="text-[12px] text-foreground-muted">
          Prepare and evidence your EMP201, EMP501 and certificates here; submit them yourself through e@syFile or eFiling
          and record SARS&apos;s answer. South African payroll stays blocked until the platform release gates are signed.
        </p>
      </div>
      <Emp201Section onRecorded={bump} />
      {/* remounted on every recorded artefact / payment so the list refreshes */}
      <ArtifactsSection key={reloadKey} />
      <PaymentsSection onChanged={bump} />
      <ReconciliationSection onRecorded={bump} />
      <CertificatesSection />
      <CoidaSection />
    </div>
  );
}
