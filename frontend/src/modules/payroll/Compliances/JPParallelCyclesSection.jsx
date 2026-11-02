import { useState } from "react";
import {
  acceptJpParallelDifference, acceptJpParallelImport, createJpParallelImport, explainJpParallelDifference,
  getJpParallelImport, listJpParallelImports, withdrawJpParallelImport,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { formatJpyAuto } from "../../../components/jurisdiction/japan/jpComponentConfig";

// Japan parallel cycles (release gate G7). The incumbent payroll's figures
// for a committed run are compared with Zoiko's, tolerance zero. Each
// difference is explained, then accepted by a different person; a clean
// cycle is accepted by someone other than its importer. The file must carry
// no identifiers — the server refuses it otherwise.

const CONCEPTS = ["gross", "withholding", "social_insurance_employee", "employment_insurance_employee",
  "resident_tax", "net_pay"];
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px]";

function errorText(e) {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string" ? detail : "The action failed.";
}

function Cycle({ id, onChanged }) {
  const [data, error, loading, reload] = useLoad(() => getJpParallelImport(id));
  const [reasons, setReasons] = useState({});
  const [state, setState] = useState({ busy: false, error: null });
  const act = async (fn) => {
    setState({ busy: true, error: null });
    try {
      await fn();
      setState({ busy: false, error: null });
      reload();
      onChanged();
    } catch (e) {
      setState({ busy: false, error: errorText(e) });
    }
  };
  if (loading) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  return (
    <div className="mt-3 rounded-lg border border-border p-3" data-testid="jp-parallel-cycle">
      <p className="text-[12px]">
        {data.source_label} · {data.period} · matched {data.matched_count}, unmatched {data.unmatched_count} · {data.status}
      </p>
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      <Table rows={data.differences} empty="No differences."
        columns={[
          { label: "Employee", key: "employee_id" },
          { label: "Concept", key: "concept" },
          { label: "Zoiko", render: (r) => formatJpyAuto(r.zoiko_amount) },
          { label: "Incumbent", render: (r) => formatJpyAuto(r.incumbent_amount) },
          { label: "Status", render: (r) => `${r.status}${r.reason ? ` — ${r.reason}` : ""}` },
          {
            label: "Actions",
            render: (r) => (
              <div className="flex flex-wrap gap-1">
                {r.status === "UNEXPLAINED" && (
                  <>
                    <input className={input} placeholder="Reason" value={reasons[r.id] || ""}
                      onChange={(e) => setReasons((v) => ({ ...v, [r.id]: e.target.value }))} />
                    <button type="button" className={btn} disabled={state.busy || !(reasons[r.id] || "").trim()}
                      onClick={() => act(() => explainJpParallelDifference(r.id, reasons[r.id]))}>Explain</button>
                  </>)}
                {r.status === "EXPLAINED" && (
                  <button type="button" className={btn} disabled={state.busy}
                    onClick={() => act(() => acceptJpParallelDifference(r.id))}>Accept (another user)</button>)}
              </div>
            ),
          },
        ]} />
      {data.status === "OPEN" && (
        <div className="mt-2 flex gap-2">
          <button type="button" className={btn} disabled={state.busy || !data.clean}
            onClick={() => act(() => acceptJpParallelImport(id))} data-testid="jp-parallel-accept">Accept cycle (not the importer)</button>
          <button type="button" className={btn} disabled={state.busy}
            onClick={() => act(() => withdrawJpParallelImport(id))}>Withdraw</button>
        </div>
      )}
    </div>
  );
}

export default function JPParallelCyclesSection() {
  const [rows, error, loading, reload] = useLoad(() => listJpParallelImports());
  const [form, setForm] = useState({ payrollRunId: "", sourceLabel: "", csv: "", employeeCode: "" });
  const [mapping, setMapping] = useState({});
  const [open, setOpen] = useState(null);
  const [state, setState] = useState({ busy: false, error: null });

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, error: null });
    try {
      const columnMapping = { employeeCode: form.employeeCode, ...Object.fromEntries(
        Object.entries(mapping).filter(([, v]) => v)) };
      await createJpParallelImport({ payrollRunId: Number(form.payrollRunId), sourceLabel: form.sourceLabel,
        csv: form.csv, columnMapping });
      setForm({ payrollRunId: "", sourceLabel: "", csv: "", employeeCode: "" });
      setMapping({});
      setState({ busy: false, error: null });
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err) });
    }
  };

  return (
    <section className={card} data-testid="jp-parallel-cycles">
      <h3 className="text-[14px] font-semibold text-foreground">Parallel cycles (release gate G7)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Compare a committed run with the current provider&apos;s figures. Export the provider file WITHOUT any identifier
        column — a file carrying one, or a 12-digit value, is refused.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No parallel cycles yet."
          columns={[
            { label: "Period", key: "period" }, { label: "Source", key: "source_label" },
            { label: "Run", key: "payroll_run_id" }, { label: "Status", key: "status" },
            { label: "", render: (r) => <button type="button" className={btn} onClick={() => setOpen(r.id)}>Open</button> },
          ]} />
      )}
      {open && <Cycle key={open} id={open} onChanged={reload} />}
      <form onSubmit={submit} className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3" aria-label="Import a parallel cycle">
        <input className={input} required placeholder="Committed run #" value={form.payrollRunId}
          onChange={(e) => setForm((f) => ({ ...f, payrollRunId: e.target.value.replace(/\D/g, "") }))} />
        <input className={input} required placeholder="Incumbent payroll name" value={form.sourceLabel}
          onChange={(e) => setForm((f) => ({ ...f, sourceLabel: e.target.value }))} />
        <input className={input} required placeholder="Employee-code column" value={form.employeeCode}
          onChange={(e) => setForm((f) => ({ ...f, employeeCode: e.target.value }))} />
        {CONCEPTS.map((concept) => (
          <input key={concept} className={input} placeholder={`Column for ${concept.replaceAll("_", " ")}`}
            value={mapping[concept] || ""} onChange={(e) => setMapping((m) => ({ ...m, [concept]: e.target.value }))} />
        ))}
        <textarea className={`${input} sm:col-span-3`} rows={5} required placeholder="Paste the CSV"
          value={form.csv} onChange={(e) => setForm((f) => ({ ...f, csv: e.target.value }))} />
        <div><button type="submit" className={btn} disabled={state.busy}>Import and compare</button></div>
      </form>
    </section>
  );
}
