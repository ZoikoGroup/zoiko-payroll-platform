import { useState } from "react";
import {
  approveZaOverride, approveZaRunException, createZaCorrection, getZaRunJournal, listZaOverrides,
  listZaRunExceptions, proposeZaOverride, withdrawZaOverride,
} from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/southAfrica/zaFormat";
import { Table } from "../../../components/jurisdiction/southAfrica/zaShared";

// South Africa approval checks (ZP-ZA-ENG-001 Phase 9; "ZA" — "SA" is Saudi
// Arabia). The server decides everything: it lists the ZA-016 exceptions,
// refuses run approval until a SECOND person has approved each one, refuses
// self-approval of exceptions and overrides, and blocks a stale override. This
// panel only shows that state and submits the operator's decision.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const btnPrimary = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const OVERRIDE_FIELDS = [
  ["za_paye", "PAYE"], ["za_uif_employee", "UIF (employee)"], ["za_uif_employer", "UIF (employer)"],
  ["za_sdl", "SDL"], ["za_other_deductions", "Other deductions"],
];
const OPEN = ["Draft", "Review"];
const COMMITTED = ["Paid", "Closed"];

function useAction(onDone) {
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const act = async (fn, ok) => {
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
  return [state, act];
}

function Status({ state }) {
  return (
    <>
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </>
  );
}

function Exceptions({ runId, runStatus }) {
  const [rows, error, loading, reload] = useLoad(() => listZaRunExceptions(runId));
  const [state, act] = useAction(reload);
  const open = (rows || []).filter((e) => !e.approved).length;
  return (
    <div data-testid="za-run-exceptions">
      <p className="mb-2 text-[12px] text-foreground-muted">
        {loading ? "Loading…" : error ? null : open
          ? `${open} exception(s) need a second person's approval before this run can be approved (ZA-016).`
          : "Every exception is approved."}
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      <Table rows={rows || []} rowKey={(r) => r.key} empty="No exceptions for this run." columns={[
        { label: "Exception", render: (r) => r.code.replaceAll("_", " ").toLowerCase() },
        { label: "Employee", render: (r) => (r.employeeId ? `#${r.employeeId}` : "Run") },
        { label: "Detail", key: "detail" },
        { label: "Approval", render: (r) => (r.approved
          ? `Approved by #${r.approved.approvedBy}`
          : OPEN.includes(runStatus)
            ? <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => approveZaRunException(runId, r.key), "Exception approved.")}>Approve</button>
            : "Not approved") },
      ]} />
      <Status state={state} />
    </div>
  );
}

function Overrides({ runId, runStatus, items }) {
  const [rows, error, , reload] = useLoad(() => listZaOverrides(runId));
  const [state, act] = useAction(reload);
  const zaItems = items.filter((i) => (i.country || i.countryCode) === "ZA");
  const [form, setForm] = useState({ employeeId: "", field: "za_paye", after: "", reasonCode: "", reason: "",
    evidenceRef: "", expiresOn: "" });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const selected = zaItems.find((i) => String(i.employeeId) === String(form.employeeId));
  const before = selected?.zaCalculationSnapshot?.[form.field];
  const submit = () => act(() => proposeZaOverride(runId, { ...form, employeeId: Number(form.employeeId) }),
    "Override recorded — a second person must approve it, then recalculate the run.");
  return (
    <div data-testid="za-run-overrides">
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      <Table rows={rows || []} empty="No overrides recorded." columns={[
        { label: "Employee", render: (r) => `#${r.employee_id}` },
        { label: "Field", key: "field" },
        { label: "Before → after", render: (r) => `${r.before_value} → ${r.after_value}` },
        { label: "Reason", render: (r) => `${r.reason_code}: ${r.reason}` },
        { label: "Expires", key: "expires_on" },
        { label: "Status", key: "status" },
        { label: "", render: (r) => (
          <div className="flex gap-1">
            {r.status === "PROPOSED" && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => approveZaOverride(r.id), "Override approved.")}>Approve</button>
            )}
            {["PROPOSED", "APPROVED"].includes(r.status) && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => withdrawZaOverride(r.id), "Override withdrawn.")}>Withdraw</button>
            )}
          </div>
        ) },
      ]} />
      {OPEN.includes(runStatus) && zaItems.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
          <label className={labelCls}>Employee
            <select className={input} value={form.employeeId} onChange={set("employeeId")}>
              <option value="">Select…</option>
              {zaItems.map((i) => <option key={i.id} value={i.employeeId}>{i.employee}</option>)}
            </select>
          </label>
          <label className={labelCls}>Field
            <select className={input} value={form.field} onChange={set("field")}>
              {OVERRIDE_FIELDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className={labelCls}>Computed (before)
            <input className={input} value={before ?? "—"} readOnly />
          </label>
          <label className={labelCls}>Override (after)
            <input className={input} value={form.after} onChange={set("after")} inputMode="decimal" />
          </label>
          <label className={labelCls}>Reason code
            <input className={input} value={form.reasonCode} onChange={set("reasonCode")} maxLength={40} />
          </label>
          <label className={labelCls}>Reason
            <input className={input} value={form.reason} onChange={set("reason")} maxLength={500} />
          </label>
          <label className={labelCls}>Evidence reference
            <input className={input} value={form.evidenceRef} onChange={set("evidenceRef")} maxLength={300} />
          </label>
          <label className={labelCls}>Expires on
            <input className={input} type="date" value={form.expiresOn} onChange={set("expiresOn")} />
          </label>
          <div className="col-span-2 md:col-span-4">
            <button type="button" className={btnPrimary} onClick={submit}
              disabled={state.busy || !form.employeeId || !form.after}>Record override</button>
          </div>
        </div>
      )}
      <Status state={state} />
    </div>
  );
}

function Journal({ runId }) {
  const [data, error, loading] = useLoad(() => getZaRunJournal(runId));
  if (loading) return <p className="text-[12px] text-foreground-muted">Building journal…</p>;
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  if (data?.status !== "READY") {
    return <p className="text-[12px] text-warning" data-testid="za-journal-blocked">Journal blocked: {data?.reason}</p>;
  }
  return (
    <div data-testid="za-journal">
      <Table rows={data.lines} rowKey={(l) => `${l.accountKey}-${l.side}`} columns={[
        { label: "Account", render: (l) => `${l.account} (${l.accountKey.replaceAll("_", " ")})` },
        { label: "Debit", render: (l) => (l.side === "DEBIT" ? l.amount : "") },
        { label: "Credit", render: (l) => (l.side === "CREDIT" ? l.amount : "") },
      ]} />
      <p className="mt-1 text-[12px] text-foreground-muted">Debits {data.debitTotal} · Credits {data.creditTotal}</p>
    </div>
  );
}

function Corrections({ items }) {
  const zaItems = items.filter((i) => (i.country || i.countryCode) === "ZA");
  const [form, setForm] = useState({ payslipId: "", reason: "", gross: "", basic: "", etiHours: "" });
  const [state, act] = useAction();
  const [result, setResult] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const changes = {
    ...(form.gross ? { gross: form.gross } : {}),
    ...(form.basic ? { basic: form.basic } : {}),
    ...(form.etiHours ? { za_eti_paid_hours: form.etiHours } : {}),
  };
  const submit = async () => {
    const out = await act(() => createZaCorrection(Number(form.payslipId), { reason: form.reason, changes }),
      "Correction booked as a linked delta payslip; the original is unchanged.");
    if (out) setResult(out);
  };
  return (
    <div data-testid="za-corrections">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <label className={labelCls}>Payslip
          <select className={input} value={form.payslipId} onChange={set("payslipId")}>
            <option value="">Select…</option>
            {zaItems.map((i) => <option key={i.id} value={i.id}>{i.employee}</option>)}
          </select>
        </label>
        <label className={labelCls}>Corrected gross
          <input className={input} value={form.gross} onChange={set("gross")} inputMode="decimal" />
        </label>
        <label className={labelCls}>Corrected basic
          <input className={input} value={form.basic} onChange={set("basic")} inputMode="decimal" />
        </label>
        <label className={labelCls}>Corrected ETI paid hours
          <input className={input} value={form.etiHours} onChange={set("etiHours")} inputMode="decimal" />
        </label>
        <label className={labelCls}>Reason
          <input className={input} value={form.reason} onChange={set("reason")} />
        </label>
      </div>
      <button type="button" className={`${btnPrimary} mt-2`} onClick={submit}
        disabled={state.busy || !form.payslipId || !form.reason || !Object.keys(changes).length}>
        Book correction
      </button>
      {result && (
        <p className="mt-1 text-[12px] text-foreground-muted">
          Correction run #{result.correctionRunId}, payslip #{result.payslipId} · PAYE Δ {result.deltas.za_paye}
          {result.eti ? ` · ETI ledger: reversed #${result.eti.reversedEntryId ?? "—"}, recorded #${result.eti.recordedEntryId ?? "—"}` : ""}
        </p>
      )}
      <Status state={state} />
    </div>
  );
}

export default function ZARunExceptionsPanel({ runId, runStatus, items }) {
  return (
    <section className="mb-5 space-y-4 rounded-[18px] border border-border p-5" aria-labelledby="za-checks-heading"
      data-testid="za-run-checks">
      <h4 id="za-checks-heading" className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
        South Africa approval checks
      </h4>
      <Exceptions key={`exc-${runId}-${runStatus}`} runId={runId} runStatus={runStatus} />
      <div>
        <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Manual overrides (ZA-017)</p>
        <Overrides key={`ovr-${runId}-${runStatus}`} runId={runId} runStatus={runStatus} items={items} />
      </div>
      <div>
        <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Payroll journal</p>
        <Journal key={`jrn-${runId}-${runStatus}`} runId={runId} />
      </div>
      {COMMITTED.includes(runStatus) && (
        <div>
          <p className="mb-1 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Corrections</p>
          <Corrections items={items} />
        </div>
      )}
    </section>
  );
}
