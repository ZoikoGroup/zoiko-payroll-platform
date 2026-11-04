import { useState } from "react";
import {
  applyNzCorrection, approveNzCorrection, createNzCorrection, createNzSpecialRun, listNzCorrections, voidNzCorrection,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// New Zealand non-standard payments and corrections (ZP-NZ-ENG-001 §10,
// NZ-006). A special run (out-of-cycle, lump sum, holiday pay in advance,
// final pay) is its own payment beside the regular run and goes through the
// normal run approval. A correction never touches the paid payslip: its frozen
// calculation is replayed with the corrected inputs and a CORRECTION run
// carries only the differences. Both block while their rules are unsigned.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const KINDS = ["OUT_OF_CYCLE", "LUMP_SUM", "HOLIDAY_PAY_ADVANCE", "FINAL"];
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function SpecialRun() {
  const [v, setV] = useState({ kind: "LUMP_SUM" });
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const set = (key) => (e) => setV({ ...v, [key]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    const options = {};
    if (v.kind === "LUMP_SUM" && v.lumpSumComponent) options.lumpSumComponent = v.lumpSumComponent;
    if (v.kind === "HOLIDAY_PAY_ADVANCE") {
      if (v.holidayAdvanceMethod) options.holidayAdvanceMethod = v.holidayAdvanceMethod;
      if (v.advancePeriods) options.advancePeriods = Number(v.advancePeriods);
    }
    if (v.kind === "FINAL" && v.finalPayCaseId) options.finalPayCaseId = Number(v.finalPayCaseId);
    const employeeIds = String(v.employeeIds || "").split(/[,\s]+/).filter(Boolean).map(Number);
    setState({ busy: true, error: null, notice: null });
    try {
      const run = await createNzSpecialRun({
        kind: v.kind, payDate: v.payDate, periodStart: v.periodStart || undefined, periodEnd: v.periodEnd || undefined,
        employeeIds, options, reason: v.reason,
      });
      setState({ busy: false, error: null, notice: `Run ${run?.runCode || run?.id} created (${run?.status}). Review it in Payroll Runs.` });
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };

  return (
    <section className={card} data-testid="nz-special-runs">
      <h3 className="text-[14px] font-semibold text-foreground">Special payments</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Out-of-cycle, lump sum / bonus (taxed by the signed extra-pay method), holiday pay in advance (standard or
        alternative method) and final pay (needs the employee&apos;s approved final pay case).
      </p>
      <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Create a special run">
        <label className={labelCls}>Kind *
          <select className={input} value={v.kind} onChange={set("kind")}>
            {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label className={labelCls}>Payday *<input className={input} type="date" required value={v.payDate || ""} onChange={set("payDate")} /></label>
        <label className={labelCls}>Employee ids * (comma-separated)
          <input className={input} required value={v.employeeIds || ""} onChange={set("employeeIds")} />
        </label>
        <label className={labelCls}>Period start<input className={input} type="date" value={v.periodStart || ""} onChange={set("periodStart")} /></label>
        <label className={labelCls}>Period end<input className={input} type="date" value={v.periodEnd || ""} onChange={set("periodEnd")} /></label>
        {v.kind === "LUMP_SUM" && (
          <label className={labelCls}>Component
            <select className={input} value={v.lumpSumComponent || ""} onChange={set("lumpSumComponent")}>
              <option value="">LUMP_SUM</option><option value="BONUS">BONUS</option>
            </select>
          </label>
        )}
        {v.kind === "HOLIDAY_PAY_ADVANCE" && (
          <>
            <label className={labelCls}>Method *
              <select className={input} required value={v.holidayAdvanceMethod || ""} onChange={set("holidayAdvanceMethod")}>
                <option value="">—</option><option value="STANDARD">STANDARD</option><option value="ALTERNATIVE">ALTERNATIVE</option>
              </select>
            </label>
            <label className={labelCls}>Periods covered (standard)
              <input className={input} inputMode="numeric" value={v.advancePeriods || ""} onChange={set("advancePeriods")} />
            </label>
          </>
        )}
        {v.kind === "FINAL" && (
          <label className={labelCls}>Final pay case id *
            <input className={input} required inputMode="numeric" value={v.finalPayCaseId || ""} onChange={set("finalPayCaseId")} />
          </label>
        )}
        <label className={labelCls}>Reason *<input className={input} required value={v.reason || ""} onChange={set("reason")} /></label>
        <div className="flex items-end"><button type="submit" className={btn} disabled={state.busy}>Create run</button></div>
      </form>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="mt-2 text-[12px] text-success">{state.notice}</p>}
    </section>
  );
}

const DELTA_FIELDS = [["gross", "Corrected gross"], ["basic", "Corrected salary"], ["overtime", "Corrected overtime"],
  ["additional_compensation", "Corrected additional pay"], ["nz_hours", "Corrected hours"]];

function Corrections() {
  const [rows, loadError, loading, reload] = useLoad(() => listNzCorrections());
  const [v, setV] = useState({});
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const set = (key) => (e) => setV({ ...v, [key]: e.target.value });

  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };

  const submit = (e) => {
    e.preventDefault();
    const inputDelta = Object.fromEntries(DELTA_FIELDS.map(([k]) => [k, v[k]]).filter(([, x]) => x !== undefined && x !== ""));
    run(async () => {
      await createNzCorrection(Number(v.itemId), { inputDelta, reason: v.reason });
      setV({});
    }, "Correction drafted — a second user must approve it.");
  };

  return (
    <section className={card} data-testid="nz-corrections">
      <h3 className="text-[14px] font-semibold text-foreground">Corrections of paid payslips</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        The original payslip is never changed. Refused while the signed correction policy is pending.
      </p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No corrections."
          columns={[
            { label: "Payslip", render: (r) => `#${r.originalPayslipItemId}` }, { label: "Employee", key: "employeeId" },
            { label: "Changed inputs", render: (r) => Object.keys(r.inputDelta || {}).join(", ") },
            { label: "Net difference", render: (r) => r.resultDelta?.netPay ?? "—" },
            { label: "Correction run", render: (r) => (r.correctionRunId ? `#${r.correctionRunId}` : "—") },
            { label: "Status", key: "status" },
            { label: "Actions", render: (r) => (
              <div className="flex flex-wrap gap-1">
                {r.status === "DRAFT" && (
                  <button type="button" className={btn} disabled={state.busy}
                    onClick={() => run(() => approveNzCorrection(r.id), "Correction approved.")}>Approve</button>
                )}
                {r.status === "APPROVED" && (
                  <button type="button" className={btn} disabled={state.busy} onClick={() => {
                    const payDate = ask("Payday of the correction run (YYYY-MM-DD)");
                    if (payDate) run(() => applyNzCorrection(r.id, payDate), "Correction run created — approve it in Payroll Runs.");
                  }}>Apply</button>
                )}
                {["DRAFT", "APPROVED"].includes(r.status) && (
                  <button type="button" className={btn} disabled={state.busy} onClick={() => {
                    const reason = ask("Why is the correction voided?");
                    if (reason) run(() => voidNzCorrection(r.id, reason), "Correction voided.");
                  }}>Void</button>
                )}
              </div>
            ) },
          ]} />
      )}
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Draft a correction">
        <label className={labelCls}>Paid payslip id *
          <input className={input} required inputMode="numeric" value={v.itemId || ""} onChange={set("itemId")} />
        </label>
        {DELTA_FIELDS.map(([key, label]) => (
          <label key={key} className={labelCls}>{label}
            <input className={input} inputMode="decimal" value={v[key] || ""} onChange={set(key)} />
          </label>
        ))}
        <label className={labelCls}>Reason *<input className={input} required value={v.reason || ""} onChange={set("reason")} /></label>
        <div className="flex items-end"><button type="submit" className={btn} disabled={state.busy}>Draft correction</button></div>
      </form>
    </section>
  );
}

export default function NZPaymentsSection() {
  return (
    <div className="space-y-4">
      <SpecialRun />
      <Corrections />
    </div>
  );
}
