import { useState } from "react";
import {
  acceptBeParallelDifference, acceptBeParallelImport, createBeParallelImport, explainBeParallelDifference,
  getBeParallelImport, listBeParallelImports, withdrawBeParallelImport,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Belgium parallel cycles (ZP-BE-ENG-001 §16, Block C2, release gate G4).
// An independent Belgian payroll's figures for a committed run are compared
// with Zoiko's frozen payslips per employee and concept. The tolerance per
// concept comes only from signed content (exact while unsigned) — the server
// decides, this page computes nothing. Each difference is explained, then
// accepted by a different person; a clean cycle is accepted by someone other
// than its importer. G4 needs two accepted cycles in different pay months for
// every launch design partner. The file must carry NO identifier: the server
// refuses any NISS / BIS, enterprise-number or IBAN column or value.

const CONCEPTS = [["gross", "Gross"], ["withholding", "Professional withholding"],
  ["onss_employee", "ONSS (employee)"], ["work_bonus_social", "Social work bonus"], ["net", "Net pay"],
  ["employer_onss", "Employer contributions"]];
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function Cycle({ id, onChanged }) {
  const [data, error, loading, reload] = useLoad(() => getBeParallelImport(id));
  const [state, setState] = useState({ busy: false, error: null });
  const act = async (fn) => {
    setState({ busy: true, error: null });
    try {
      await fn();
      setState({ busy: false, error: null });
      reload();
      onChanged();
    } catch (err) {
      setState({ busy: false, error: errorText(err) });
    }
  };
  if (loading) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  return (
    <div className="mt-3 rounded-lg border border-border p-3" data-testid="be-parallel-cycle">
      <p className="text-[12px] text-foreground">
        {data.sourceName} · pay date {data.payDate} · matched {data.matchedCount}, unmatched {data.unmatchedCount} · {data.status}
        {data.legalEntityId ? ` · legal entity #${data.legalEntityId}` : " · organisation-wide"}
      </p>
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      <Table rows={data.differences} empty="No differences — every compared figure matches."
        columns={[
          { label: "Employee", render: (r) => `#${r.employeeId}` }, { label: "Concept", key: "concept" },
          { label: "Zoiko", key: "zoikoAmount" }, { label: "Independent", key: "incumbentAmount" },
          { label: "Difference", key: "difference" },
          { label: "Status", render: (r) => `${r.status}${r.explanation ? ` — ${r.explanation}` : ""}` },
          { label: "Actions", render: (r) => (
            <div className="flex flex-wrap gap-1">
              {r.status !== "ACCEPTED" && (
                <button type="button" className={btn} disabled={state.busy} onClick={() => {
                  const reason = ask("Why does this figure differ?");
                  if (reason) act(() => explainBeParallelDifference(r.id, reason));
                }}>Explain</button>
              )}
              {r.status === "EXPLAINED" && (
                <button type="button" className={btn} disabled={state.busy}
                  onClick={() => act(() => acceptBeParallelDifference(r.id))}>Accept (another user)</button>
              )}
            </div>
          ) },
        ]} />
      {data.status === "OPEN" && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className={btn} disabled={state.busy || !data.clean} data-testid="be-parallel-accept"
            onClick={() => act(() => acceptBeParallelImport(id))}>Accept cycle (not the importer)</button>
          <button type="button" className={btn} disabled={state.busy} onClick={() => {
            const reason = ask("Why is this import withdrawn?");
            if (reason) act(() => withdrawBeParallelImport(id, reason));
          }}>Withdraw</button>
        </div>
      )}
    </div>
  );
}

export default function BEParallelCyclesSection() {
  const [rows, error, loading, reload] = useLoad(() => listBeParallelImports());
  const [form, setForm] = useState({ runId: "", sourceName: "", employeeCode: "", reason: "", csv: "" });
  const [columns, setColumns] = useState({});
  const [open, setOpen] = useState(null);
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const readFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setForm((f) => ({ ...f, csv: text }));
  };

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null, notice: null });
    try {
      const columnMap = { employeeCode: form.employeeCode,
        ...Object.fromEntries(Object.entries(columns).filter(([, v]) => v)) };
      const summary = await createBeParallelImport({ runId: Number(form.runId), sourceName: form.sourceName,
        csv: form.csv, columnMap, reason: form.reason });
      setForm({ runId: "", sourceName: "", employeeCode: "", reason: "", csv: "" });
      setColumns({});
      setState({ busy: false, error: null,
        notice: `Imported: ${summary?.differences?.length ?? 0} difference(s), ${summary?.unmatchedCount ?? 0} unmatched.` });
      setOpen(summary?.id ?? null);
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };

  return (
    <section className={card} data-testid="be-parallel-cycles">
      <h3 className="text-[14px] font-semibold text-foreground">Parallel cycles (release gate G4)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Compare a committed run with an independent Belgian payroll&apos;s figures. Export that file WITHOUT NISS / BIS
        numbers, enterprise numbers or IBANs — a file carrying any of them is refused before anything is saved. Only the
        employee code links a row to a payslip. Every unexplained difference blocks the release.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No parallel cycles yet."
          columns={[
            { label: "Pay month", key: "cycleMonth" }, { label: "Source", key: "sourceName" },
            { label: "Run", render: (r) => `#${r.runId}` }, { label: "Status", key: "status" },
            { label: "", render: (r) => (
              <button type="button" className={btn} onClick={() => setOpen(open === r.id ? null : r.id)}>
                {open === r.id ? "Hide" : "Open"}
              </button>
            ) },
          ]} />
      )}
      {open && <Cycle key={open} id={open} onChanged={reload} />}
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Import a parallel cycle">
        <label className={labelCls}>Committed run id *<input className={input} required inputMode="numeric" value={form.runId}
          onChange={(e) => setForm((f) => ({ ...f, runId: e.target.value.replace(/\D/g, "") }))} /></label>
        <label className={labelCls}>Independent payroll *<input className={input} required value={form.sourceName} onChange={set("sourceName")} /></label>
        <label className={labelCls}>Employee-code column *<input className={input} required value={form.employeeCode} onChange={set("employeeCode")} /></label>
        {CONCEPTS.map(([key, label]) => (
          <label key={key} className={labelCls}>Column for {label}
            <input className={input} value={columns[key] || ""}
              onChange={(e) => setColumns((c) => ({ ...c, [key]: e.target.value }))} />
          </label>
        ))}
        <label className={`${labelCls} sm:col-span-3`}>Independent payroll CSV file
          <input type="file" accept=".csv,text/csv" onChange={readFile} className="text-[12px]" />
        </label>
        <label className={`${labelCls} sm:col-span-3`}>…or paste the CSV *
          <textarea className={input} rows={5} required value={form.csv} onChange={set("csv")} />
        </label>
        <label className={labelCls}>Reason *<input className={input} required value={form.reason} onChange={set("reason")} /></label>
        <div className="flex items-end"><button type="submit" className={btn} disabled={state.busy}>Import and compare</button></div>
      </form>
    </section>
  );
}
